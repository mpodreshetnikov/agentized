"""Hard gates for e2e and DB tests when those layers are auto-detected.

When a repo has Playwright/Cypress (etc.) or a DB migration/ORM/pgTAP layer,
the suite must exist (real specs, not placeholders). Changed product areas
must ship matching test updates. Absent layers → skip (pass).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

_SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "mutants",
    "coverage",
    "reports",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".tox",
    ".next",
    ".turbo",
    "vendor",
}

# Only applied when the host looks like the Agentized dogfood repo, or when
# quality.json sets skip_rel_prefixes explicitly. Never hide a user's templates/.
_AGENTIZED_SKIP_REL_PREFIXES = (
    "templates/",
    "tests/fixtures/",
)

E2E_CONFIG_NAMES = (
    "playwright.config.ts",
    "playwright.config.js",
    "playwright.config.mjs",
    "playwright.config.cjs",
    "cypress.config.ts",
    "cypress.config.js",
    "cypress.config.mjs",
    "nightwatch.conf.js",
    "wdio.conf.js",
    "wdio.conf.ts",
)

E2E_PKG_DEPS = (
    "@playwright/test",
    "playwright",
    "cypress",
    "nightwatch",
    "webdriverio",
)

E2E_DIR_NAMES = ("e2e", "playwright")

DB_DIR_SUFFIXES = (
    "/migrations",
    "/db/migrations",
    "/supabase/migrations",
    "/prisma/migrations",
    "/alembic/versions",
    "/flyway/sql",
    "/pgtap",
    "/db/tests",
    "/tests/db",
    "/tests/sql",
)

DB_DIR_ROOT_NAMES = (
    "migrations",
    "db/migrations",
    "supabase/migrations",
    "prisma/migrations",
    "alembic/versions",
    "flyway/sql",
    "liquibase",
    "pgtap",
    "db/tests",
    "tests/db",
    "tests/sql",
)

DB_FILE_MARKERS = ("alembic.ini", "schema.sql")

ORM_JS_DEPS = (
    "prisma",
    "@prisma/client",
    "drizzle-orm",
    "typeorm",
    "sequelize",
    "knex",
)

ORM_PY_DEPS = (
    "sqlalchemy",
    "django",
    "alembic",
)

PLACEHOLDER_NAMES = {".gitkeep", ".keep"}

DEFAULT_E2E_SOURCE_GLOBS = (
    "app/**",
    "apps/**",
    "src/**",
    "pages/**",
    "components/**",
    "web/**",
    "frontend/**",
    "ui/**",
    "client/**",
)

DEFAULT_E2E_TEST_GLOBS = (
    "e2e/**",
    "**/e2e/**",
    "tests/e2e/**",
    "cypress/e2e/**",
    "playwright/**",
    "**/*.e2e.ts",
    "**/*.e2e.js",
    "**/*.e2e.tsx",
)

DEFAULT_DB_SOURCE_GLOBS = (
    "**/migrations/**",
    "**/db/migrations/**",
    "**/alembic/versions/**",
    "**/prisma/migrations/**",
    "**/supabase/migrations/**",
    "db/**/*.sql",
    "sql/**",
    "schema.sql",
    "**/schema/**",
)

DEFAULT_DB_TEST_GLOBS = (
    "**/tests/db/**",
    "**/db/tests/**",
    "**/pgtap/**",
    "**/test_*.sql",
    "**/*_test.sql",
    "tests/sql/**",
)

LAYER_GATE_NAMES = ("e2e", "db_tests")

# AGE-29/31: human disable_decision must expire within this many days.
DISABLE_DECISION_MAX_DAYS = 14


class GitDiffError(RuntimeError):
    """Raised when git diff cannot be resolved for a present layer."""


def _glob_match(rel: str, pattern: str) -> bool:
    rel = rel.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    if fnmatch.fnmatch(rel, pattern):
        return True
    if "**" not in pattern:
        return False
    if pattern.startswith("**/"):
        rest = pattern[3:]
        if fnmatch.fnmatch(rel, rest):
            return True
        return any(
            fnmatch.fnmatch(rel[i + 1 :], rest) for i, ch in enumerate(rel) if ch == "/"
        )
    if pattern.endswith("/**"):
        prefix = pattern[: -len("/**")]
        return rel == prefix or rel.startswith(prefix + "/")
    simplified = pattern.replace("/**/", "/").replace("**/", "").replace("**", "*")
    return fnmatch.fnmatch(rel, simplified)


def _matches_any(rel: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(_glob_match(rel, p) for p in patterns)


def _iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        base = Path(dirpath)
        for name in filenames:
            out.append(base / name)
    return out


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_agentized_repo(root: Path) -> bool:
    """True for the Agentized dogfood layout (not a random user repo).

    mutmut copies sources as top-level ``agentized/`` (not ``runtime/agentized/``)
    while still also_copy-ing ``templates/quality`` — accept either layout.
    """
    has_pkg = (root / "runtime" / "agentized").is_dir() or (root / "agentized").is_dir()
    has_quality_templates = (root / "templates" / "quality").is_dir()
    return has_pkg and has_quality_templates


def skip_rel_prefixes(root: Path, section: dict[str, Any] | None = None) -> tuple[str, ...]:
    section = section or {}
    configured = section.get("skip_rel_prefixes")
    if isinstance(configured, list):
        return tuple(str(p) for p in configured)
    if is_agentized_repo(root):
        return _AGENTIZED_SKIP_REL_PREFIXES
    return ()


def _is_skipped_rel(rel: str, prefixes: tuple[str, ...]) -> bool:
    rel = rel.replace("\\", "/")
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in prefixes)


def _changed_files(root: Path, base_ref: str) -> list[str]:
    """List changed paths vs base. Fail closed on git errors (never silent [])."""
    filters = "ACMRD"
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"--diff-filter={filters}", f"{base_ref}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"--diff-filter={filters}", base_ref],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "git diff failed").strip()
            raise GitDiffError(
                f"git diff failed for base_ref={base_ref!r}: {err[:500]}"
            )
    return sorted(
        {
            line.strip().replace("\\", "/")
            for line in proc.stdout.splitlines()
            if line.strip()
        }
    )


_JSON_ENCODING = "utf-8"


def _read_package_deps(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_bytes().decode(_JSON_ENCODING))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    names: set[str] = set()
    for key in (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    ):
        block = data.get(key)
        if isinstance(block, dict):
            names.update(str(k) for k in block)
    return names


def _read_python_deps(root: Path, prefixes: tuple[str, ...]) -> list[tuple[str, set[str]]]:
    found: list[tuple[str, set[str]]] = []
    candidates = [root / "pyproject.toml", *sorted(root.glob("requirements*.txt"))]
    for path in candidates:
        if not path.is_file():
            continue
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        try:
            text = path.read_bytes().decode(_JSON_ENCODING, errors="ignore")
        except OSError:
            continue
        names: set[str] = set()
        lower = text.lower()
        for dep in ORM_PY_DEPS:
            if (
                re.search(rf"(?m)^\s*{re.escape(dep)}\b", lower)
                or f'"{dep}"' in lower
                or f"'{dep}'" in lower
            ):
                names.add(dep)
        if names:
            found.append((rel, names))
    return found


def _dir_has_real_files(root: Path, rel_dir: str, prefixes: tuple[str, ...]) -> bool:
    base = root / rel_dir
    if not base.is_dir():
        return False
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        parts = set(Path(rel).parts)
        if parts & _SKIP_DIR_NAMES:
            continue
        if path.name in PLACEHOLDER_NAMES:
            continue
        try:
            if path.stat().st_size == 0:
                continue
            if not path.read_text(encoding="utf-8", errors="ignore").strip():
                continue
        except OSError:
            continue
        return True
    return False


def _normalize_rel(rel: str) -> str:
    """Normalize path separators and strip trailing slashes (keep leading)."""
    return rel.replace("\\", "/").rstrip("/")


def _looks_like_db_dir(rel: str) -> str | None:
    """Return evidence kind if rel path is a DB marker directory."""
    rel = _normalize_rel(rel)
    if rel in DB_DIR_ROOT_NAMES or any(rel.endswith(suf) for suf in DB_DIR_SUFFIXES):
        if rel.endswith("pgtap") or rel == "pgtap":
            return "pgtap_dir"
        if rel.endswith(("db/tests", "tests/db", "tests/sql")):
            return "db_tests_dir"
        return "migrations_dir"
    return None


def detect_e2e(root: Path, *, skip_prefixes: tuple[str, ...] | None = None) -> dict[str, Any]:
    if skip_prefixes is None:
        prefixes = skip_rel_prefixes(root)
    else:
        prefixes = skip_prefixes
    evidence: list[dict[str, str]] = []

    for path in _iter_files(root):
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        if path.name in E2E_CONFIG_NAMES:
            evidence.append({"kind": "config", "path": rel})
        if path.name == "package.json":
            deps = _read_package_deps(path)
            hit = sorted(d for d in E2E_PKG_DEPS if d in deps)
            if hit:
                evidence.append(
                    {"kind": "package_dep", "path": rel, "detail": ",".join(hit)}
                )
        # Nested e2e / playwright / cypress/e2e dirs — only if they hold real specs.
        parts = Path(rel).parts
        for i, part in enumerate(parts[:-1]):
            if part in E2E_DIR_NAMES or (
                part == "cypress" and i + 1 < len(parts) - 1 and parts[i + 1] == "e2e"
            ):
                if part == "cypress":
                    dir_rel = "/".join(parts[: i + 2])
                else:
                    dir_rel = "/".join(parts[: i + 1])
                if not _dir_has_real_files(root, dir_rel, prefixes):
                    continue
                # Ignore artifact dumps accidentally named e2e (e.g. reports/e2e).
                if dir_rel == "reports/e2e" or dir_rel.startswith("reports/"):
                    continue
                evidence.append({"kind": "tests_dir", "path": dir_rel})

    seen: set[tuple[str, str]] = set()
    uniq: list[dict[str, str]] = []
    for item in evidence:
        key = (item.get("kind", ""), item.get("path", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return {"present": bool(uniq), "evidence": uniq, "framework": _e2e_framework(uniq)}


def detect_db_layer(root: Path, *, skip_prefixes: tuple[str, ...] | None = None) -> dict[str, Any]:
    if skip_prefixes is None:
        prefixes = skip_rel_prefixes(root)
    else:
        prefixes = skip_prefixes
    evidence: list[dict[str, str]] = []

    # Root-relative classic markers
    for marker in DB_DIR_ROOT_NAMES:
        if _is_skipped_rel(marker, prefixes):
            continue
        if _dir_has_real_files(root, marker, prefixes):
            kind = _looks_like_db_dir(marker)
            if kind is None:
                continue
            evidence.append({"kind": kind, "path": marker})

    for name in DB_FILE_MARKERS:
        if (root / name).is_file() and not _is_skipped_rel(name, prefixes):
            evidence.append({"kind": "marker_file", "path": name})

    # Repo-wide walk: apps/*/migrations, services/*/db/migrations, nested ORM dirs
    seen_dirs: set[str] = set()
    for path in _iter_files(root):
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        parent = Path(rel).parent.as_posix()
        kind = _looks_like_db_dir(parent)
        if kind and parent not in seen_dirs:
            if path.name in PLACEHOLDER_NAMES:
                continue
            try:
                if path.stat().st_size == 0 or not path.read_text(
                    encoding="utf-8", errors="ignore"
                ).strip():
                    continue
            except OSError:
                continue
            seen_dirs.add(parent)
            evidence.append({"kind": kind, "path": parent})
        if path.name == "schema.prisma":
            evidence.append({"kind": "marker_file", "path": rel})
        if path.name == "package.json":
            deps = _read_package_deps(path)
            hit = sorted(d for d in ORM_JS_DEPS if d in deps)
            if hit:
                evidence.append(
                    {"kind": "orm_dep", "path": rel, "detail": ",".join(hit)}
                )
        if path.suffix == ".sql":
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:4000].lower()
            except OSError:
                continue
            if "select plan(" in head or "pgtap" in head or "tap:" in head:
                evidence.append({"kind": "pgtap_sql", "path": rel})

    for rel, names in _read_python_deps(root, prefixes):
        evidence.append(
            {"kind": "orm_dep", "path": rel, "detail": ",".join(sorted(names))}
        )

    seen: set[tuple[str, str]] = set()
    uniq: list[dict[str, str]] = []
    for item in evidence:
        key = (item.get("kind", ""), item.get("path", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return {"present": bool(uniq), "evidence": uniq, "framework": _db_framework(uniq)}


def _e2e_framework(evidence: list[dict[str, str]]) -> str | None:
    blob = " ".join(f"{e.get('path','')} {e.get('detail','')}" for e in evidence).lower()
    if "playwright" in blob:
        return "playwright"
    if "cypress" in blob:
        return "cypress"
    if "nightwatch" in blob:
        return "nightwatch"
    if "wdio" in blob or "webdriverio" in blob:
        return "webdriverio"
    return None


def _db_framework(evidence: list[dict[str, str]]) -> str | None:
    kinds = {e.get("kind") for e in evidence}
    if "pgtap_sql" in kinds or "pgtap_dir" in kinds:
        return "pgtap"
    blob = " ".join(f"{e.get('path','')} {e.get('detail','')}" for e in evidence).lower()
    if "prisma" in blob:
        return "prisma"
    if "drizzle" in blob:
        return "drizzle"
    if "alembic" in blob or "sqlalchemy" in blob:
        return "alembic"
    if "django" in blob:
        return "django"
    if kinds & {"migrations_dir", "orm_dep", "marker_file", "db_tests_dir"}:
        return "sql"
    return None


def _has_supabase(root: Path) -> bool:
    """True only when supabase/config.toml exists (CLI project marker)."""
    return (root / "supabase" / "config.toml").is_file()


def default_test_command(
    gate_name: str, detection: dict[str, Any], *, root: Path | None = None
) -> str | None:
    """Autodetect a runnable command for a present layer, or None (fail closed)."""
    framework = detection.get("framework")
    if gate_name == "e2e":
        if framework == "playwright":
            return "npx playwright test"
        if framework == "cypress":
            return "npx cypress run"
        if framework == "nightwatch":
            return "npx nightwatch"
        if framework == "webdriverio":
            return "npx wdio run"
        return None
    if gate_name == "db_tests":
        if root is not None and _has_supabase(root):
            return "supabase test db"
        if framework == "pgtap":
            return "pg_prove db/tests/*.sql tests/db/*.sql pgtap/*.sql"
        # sql/ORM without supabase or pgtap → caller must set test_command
        return None
    return None


def _enabled_mode(raw: Any) -> str:
    if raw is True or str(raw).lower() == "true":
        return "true"
    if raw is False or str(raw).lower() == "false":
        return "false"
    return "auto"


def disable_decision_valid(
    section: dict[str, Any],
    *,
    now: datetime | None = None,
    max_days: int = DISABLE_DECISION_MAX_DAYS,
) -> bool:
    """AGE-29/31: reason + approved_by + unexpired expires within max_days (human-only)."""
    decision = section.get("disable_decision")
    if not isinstance(decision, dict):
        return False
    reason = str(decision.get("reason") or "").strip()
    approved_by = str(decision.get("approved_by") or "").strip()
    expires_val = decision.get("expires")
    if not isinstance(expires_val, str):
        return False
    expires_raw = expires_val.strip()
    if not reason or not approved_by or not expires_raw:
        return False
    try:
        # Python 3.11+ accepts trailing Z; offset form also fine.
        expires = datetime.fromisoformat(expires_raw)
    except ValueError:
        return False
    # Naive datetimes are rejected — callers must supply an offset / Z.
    if expires.tzinfo is None:
        return False
    clock = now if now is not None else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        return False
    remaining = (expires - clock).total_seconds()
    if remaining <= 0:
        return False
    if remaining > timedelta(days=max_days).total_seconds():
        return False
    return True


def _is_real_test_file(path: Path) -> bool:
    if path.name in PLACEHOLDER_NAMES:
        return False
    try:
        if path.stat().st_size == 0:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(text.strip())


def _collect_real_tests(
    root: Path, patterns: list[str] | tuple[str, ...], prefixes: tuple[str, ...]
) -> list[str]:
    hits: list[str] = []
    for path in _iter_files(root):
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        if not _matches_any(rel, patterns):
            continue
        if _is_real_test_file(path):
            hits.append(rel)
    return sorted(hits)


_CMD_OUTPUT_LIMIT = 4000


def _run_command(root: Path, command: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["bash", "-lc", command],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    out = str(proc.stdout or "").strip()
    return int(proc.returncode), out[:_CMD_OUTPUT_LIMIT]


def _write_report(root: Path, kind: str, payload: dict[str, Any]) -> Path:
    out_dir = root / "reports" / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{kind}-summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _finalize(
    root: Path,
    gate_name: str,
    mode: str,
    payload: dict[str, Any],
    findings: list[dict[str, str]],
) -> int:
    payload = dict(payload)
    payload["findings"] = findings
    payload["passed"] = True if mode == "warn" else not findings
    payload["generatedAt"] = datetime.now(timezone.utc).isoformat()
    _write_report(root, gate_name, payload)
    if findings:
        print(f"[{gate_name}] {len(findings)} finding(s) (mode={mode})")
        for item in findings[:20]:
            print(f"  {item['kind']}: {item['detail'][:240]}")
    elif payload.get("skipped"):
        print(f"[{gate_name}] {payload.get('reason', 'skip')}")
    else:
        print(f"[{gate_name}] PASS")
    if mode == "warn":
        print(f"[{gate_name}] warn mode — not failing the gate")
        return 0
    return 0 if not findings else 1


def _evaluate_layer(
    root: Path,
    *,
    gate_name: str,
    section: dict[str, Any],
    detection: dict[str, Any],
) -> int:
    if gate_name == "e2e":
        default_source_globs = DEFAULT_E2E_SOURCE_GLOBS
        default_test_globs = DEFAULT_E2E_TEST_GLOBS
    elif gate_name == "db_tests":
        default_source_globs = DEFAULT_DB_SOURCE_GLOBS
        default_test_globs = DEFAULT_DB_TEST_GLOBS
    else:
        raise ValueError(f"unknown layer gate: {gate_name}")
    enabled = _enabled_mode(section.get("enabled", "auto"))
    mode = str(section.get("mode") or "hard").lower()
    present = bool(detection.get("present"))
    prefixes = skip_rel_prefixes(root, section)
    findings: list[dict[str, str]] = []

    # enabled=false with a present layer requires disable_decision (AGE-29/31).
    if enabled == "false":
        if present and not disable_decision_valid(section):
            findings.append(
                {
                    "kind": "disabled_without_decision",
                    "detail": (
                        f"{gate_name}.enabled=false without valid disable_decision "
                        "(reason + approved_by + expires ≤14d). Set enabled=auto|true "
                        "or record a human disable_decision."
                    ),
                }
            )
            return _finalize(
                root,
                gate_name,
                mode,
                {
                    "schemaVersion": 1,
                    "gate": gate_name,
                    "enabled": enabled,
                    "mode": mode,
                    "present": present,
                    "evidence": detection.get("evidence") or [],
                    "skipped": False,
                    "reason": "disabled_without_decision",
                },
                findings,
            )
        return _finalize(
            root,
            gate_name,
            mode,
            {
                "schemaVersion": 1,
                "gate": gate_name,
                "enabled": enabled,
                "mode": mode,
                "present": present,
                "skipped": True,
                "reason": "disabled" if not present else "disabled_by_decision",
            },
            [],
        )

    if enabled == "auto" and not present:
        return _finalize(
            root,
            gate_name,
            mode,
            {
                "schemaVersion": 1,
                "gate": gate_name,
                "enabled": enabled,
                "mode": mode,
                "present": False,
                "evidence": detection.get("evidence") or [],
                "skipped": True,
                "reason": "layer_absent",
            },
            [],
        )

    require_for_changed = bool(section.get("require_tests_for_changed", True))
    if present and not require_for_changed and not disable_decision_valid(section):
        findings.append(
            {
                "kind": "require_disabled_without_decision",
                "detail": (
                    f"{gate_name}: require_tests_for_changed=false while layer present "
                    "needs disable_decision (reason + approved_by + expires ≤14d)"
                ),
            }
        )
        return _finalize(
            root,
            gate_name,
            mode,
            {
                "schemaVersion": 1,
                "gate": gate_name,
                "enabled": enabled,
                "mode": mode,
                "present": True,
                "evidence": detection.get("evidence") or [],
                "skipped": False,
                "reason": "require_disabled_without_decision",
            },
            findings,
        )

    source_globs = list(section.get("source_globs") or default_source_globs)
    test_globs = list(section.get("test_globs") or default_test_globs)
    existing_tests = _collect_real_tests(root, test_globs, prefixes)

    # Missing suite is checked BEFORE the no-source-change shortcut.
    if not existing_tests:
        findings.append(
            {
                "kind": "missing_tests",
                "detail": (
                    f"{gate_name} layer present but no real (non-empty, non-placeholder) "
                    f"test files match {test_globs}"
                ),
            }
        )
        return _finalize(
            root,
            gate_name,
            mode,
            {
                "schemaVersion": 1,
                "gate": gate_name,
                "enabled": enabled,
                "mode": mode,
                "present": True,
                "evidence": detection.get("evidence") or [],
                "skipped": False,
                "existingTests": [],
                "reason": "missing_tests",
            },
            findings,
        )

    base = (
        os.environ.get("LAYER_GATES_BASE")
        or os.environ.get("MUTATION_BASE")
        or section.get("base_ref")
        or "origin/main"
    )
    try:
        changed = _changed_files(root, str(base))
    except GitDiffError as exc:
        findings.append({"kind": "git_diff_failed", "detail": str(exc)})
        return _finalize(
            root,
            gate_name,
            mode,
            {
                "schemaVersion": 1,
                "gate": gate_name,
                "enabled": enabled,
                "mode": mode,
                "present": True,
                "evidence": detection.get("evidence") or [],
                "skipped": False,
                "baseRef": base,
                "reason": "git_diff_failed",
            },
            findings,
        )

    source_changed = [
        p for p in changed if _matches_any(p, source_globs) and not _matches_any(p, test_globs)
    ]
    # LIMITATION: any matching test_globs path counts — not mapped 1:1 to the
    # specific source file that changed (document in QUALITY.md / skill).
    tests_changed = [p for p in changed if _matches_any(p, test_globs)]

    if require_for_changed and source_changed and not tests_changed:
        findings.append(
            {
                "kind": "tests_not_updated",
                "detail": (
                    f"Changed {gate_name} sources require matching test updates "
                    f"(changed sources: {', '.join(source_changed[:8])})"
                ),
            }
        )

    configured_cmd = section.get("test_command")
    if configured_cmd is None or (
        isinstance(configured_cmd, str) and not configured_cmd.strip()
    ):
        cmd = default_test_command(gate_name, detection, root=root)
        if not cmd:
            findings.append(
                {
                    "kind": "test_command_required",
                    "detail": (
                        f"{gate_name}: test_command is null/empty and no autodetect for "
                        f"framework={detection.get('framework')!r} "
                        "(try playwright / supabase test db / pg_prove)"
                    ),
                }
            )
            cmd = None
    else:
        cmd = str(configured_cmd)

    # Detected layer must RUN tests (Lead #23) — always execute when we have a command.
    cmd_out = ""
    if cmd:
        cmd_rc, cmd_out = _run_command(root, cmd)
        if cmd_rc != 0:
            findings.append(
                {
                    "kind": "test_command_failed",
                    "detail": f"test_command exit {cmd_rc}: {cmd_out or '(no output)'}",
                }
            )

    return _finalize(
        root,
        gate_name,
        mode,
        {
            "schemaVersion": 1,
            "gate": gate_name,
            "enabled": enabled,
            "mode": mode,
            "present": True,
            "evidence": detection.get("evidence") or [],
            "skipped": False,
            "baseRef": base,
            "changedSources": source_changed,
            "changedTests": tests_changed,
            "existingTests": existing_tests[:50],
            "requireTestsForChanged": require_for_changed,
            "testCommandNote": cmd_out,
            "testCommand": cmd,
            "note": (
                "tests_changed matches any test_globs path in the diff — "
                "not a per-source-file mapping"
            ),
        },
        findings,
    )


def _ensure_gate_list(gates: list[Any], name: str) -> bool:
    """Insert gate name before mutation (or append). Return True if changed."""
    as_str = [str(g) for g in gates]
    if name in as_str:
        return False
    if "mutation" in as_str:
        idx = as_str.index("mutation")
        gates.insert(idx, name)
    else:
        gates.append(name)
    return True


def upgrade_layer_gate_config(data: dict[str, Any]) -> list[str]:
    """Reconnect upgrades for e2e/db_tests (AGE-31).

    - warn → hard
    - enabled false → auto
    - ensure gates.pre_push / gates.ci include e2e and db_tests before mutation
    """
    upgraded: list[str] = []
    for section_name in LAYER_GATE_NAMES:
        section = data.get(section_name)
        if not isinstance(section, dict):
            # Ensure section exists with safe auto defaults
            data[section_name] = {
                "enabled": "auto",
                "mode": "hard",
                "require_tests_for_changed": True,
            }
            upgraded.append(f"{section_name}.created")
            section = data[section_name]
        mode_raw = section.get("mode")
        if isinstance(mode_raw, str) and mode_raw.lower() == "warn":
            section["mode"] = "hard"
            upgraded.append(f"{section_name}.mode")
        # Only flip explicit false — missing enabled stays untouched (still auto via defaults).
        if "enabled" in section and _enabled_mode(section.get("enabled")) == "false":
            section["enabled"] = "auto"
            upgraded.append(f"{section_name}.enabled")

    gates = data.get("gates")
    if not isinstance(gates, dict):
        gates = {}
        data["gates"] = gates
    for list_name in ("pre_push", "ci"):
        raw = gates.get(list_name)
        if not isinstance(raw, list):
            raw = []
            gates[list_name] = raw
        before = list(raw)
        for name in LAYER_GATE_NAMES:
            _ensure_gate_list(raw, name)
        if raw != before:
            upgraded.append(f"gates.{list_name}")
    return upgraded


def run_e2e_gate(root: Path | None = None, *, context: str = DEFAULT_CONTEXT) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg["e2e"]
    prefixes = skip_rel_prefixes(root, section)
    detection = detect_e2e(root, skip_prefixes=prefixes)
    return _evaluate_layer(
        root,
        gate_name="e2e",
        section=section,
        detection=detection,
    )


def run_db_tests_gate(root: Path | None = None, *, context: str = DEFAULT_CONTEXT) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg["db_tests"]
    prefixes = skip_rel_prefixes(root, section)
    detection = detect_db_layer(root, skip_prefixes=prefixes)
    return _evaluate_layer(
        root,
        gate_name="db_tests",
        section=section,
        detection=detection,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    which = "all"
    if "--e2e" in args:
        which = "e2e"
    elif "--db" in args:
        which = "db"
    root = find_repo_root()
    rc = 0
    if which in {"all", "e2e"}:
        rc = run_e2e_gate(root, context=context) or rc
    if which in {"all", "db"}:
        rc = run_db_tests_gate(root, context=context) or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
