"""Hard gates for e2e and DB tests when those layers are auto-detected."""
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

_SKIP_DIR_NAMES = {
    ".git", "node_modules", "mutants", "coverage", "reports", ".venv", "venv",
    "dist", "build", "__pycache__", ".tox", ".next", ".turbo", "vendor",
}
_AGENTIZED_SKIP_REL_PREFIXES = ("templates/", "tests/fixtures/")
E2E_CONFIG_NAMES = (
    "playwright.config.ts", "playwright.config.js", "playwright.config.mjs",
    "playwright.config.cjs", "cypress.config.ts", "cypress.config.js", "cypress.config.mjs",
)
E2E_PKG_DEPS = ("@playwright/test", "playwright", "cypress")
E2E_DIR_NAMES = ("e2e", "playwright")
DB_DIR_SUFFIXES = (
    "/migrations", "/db/migrations", "/supabase/migrations", "/prisma/migrations",
    "/alembic/versions", "/flyway/sql", "/pgtap", "/db/tests", "/tests/db", "/tests/sql",
)
DB_DIR_ROOT_NAMES = (
    "migrations", "db/migrations", "supabase/migrations", "prisma/migrations",
    "alembic/versions", "flyway/sql", "liquibase", "pgtap", "db/tests", "tests/db", "tests/sql",
)
DB_FILE_MARKERS = ("alembic.ini", "schema.sql")
ORM_JS_DEPS = ("prisma", "@prisma/client", "drizzle-orm", "typeorm", "sequelize", "knex")
ORM_PY_DEPS = ("sqlalchemy", "django", "alembic")
PLACEHOLDER_NAMES = {".gitkeep", ".keep"}
DEFAULT_E2E_SOURCE_GLOBS = (
    "app/**", "apps/**", "src/**", "pages/**", "components/**", "web/**",
    "frontend/**", "ui/**", "client/**",
)
DEFAULT_E2E_TEST_GLOBS = (
    "e2e/**", "**/e2e/**", "tests/e2e/**", "cypress/e2e/**", "playwright/**",
    "**/*.e2e.ts", "**/*.e2e.js", "**/*.e2e.tsx",
)
DEFAULT_DB_SOURCE_GLOBS = (
    "**/migrations/**", "**/db/migrations/**", "**/alembic/versions/**",
    "**/prisma/migrations/**", "**/supabase/migrations/**", "db/**/*.sql",
    "sql/**", "schema.sql", "**/schema/**",
)
DEFAULT_DB_TEST_GLOBS = (
    "**/tests/db/**", "**/db/tests/**", "**/pgtap/**", "**/test_*.sql",
    "**/*_test.sql", "tests/sql/**",
)
LAYER_GATE_NAMES = ("e2e", "db_tests")
DISABLE_DECISION_MAX_DAYS = 14
_JSON_ENCODING = "utf-8"
_CMD_OUTPUT_LIMIT = 4000

class GitDiffError(RuntimeError):
    """Raised when git diff cannot be resolved for a present layer."""

def _glob_match(rel: str, pattern: str) -> bool:
    rel, pattern = rel.replace("\\", "/"), pattern.replace("\\", "/")
    if fnmatch.fnmatch(rel, pattern):
        return True
    if "**" not in pattern:
        return False
    if pattern.startswith("**/"):
        rest = pattern[3:]
        return fnmatch.fnmatch(rel, rest) or any(
            fnmatch.fnmatch(rel[i + 1 :], rest) for i, ch in enumerate(rel) if ch == "/"
        )
    if pattern.endswith("/**"):
        prefix = pattern[: -len("/**")]
        return rel == prefix or rel.startswith(prefix + "/")
    return fnmatch.fnmatch(
        rel, pattern.replace("/**/", "/").replace("**/", "").replace("**", "*")
    )

def _matches_any(rel: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(_glob_match(rel, p) for p in patterns)

def _iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        base = Path(dirpath)
        out.extend(base / name for name in filenames)
    return out

def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()

def is_agentized_repo(root: Path) -> bool:
    has_pkg = (root / "runtime" / "agentized").is_dir() or (root / "agentized").is_dir()
    return has_pkg and (root / "templates" / "quality").is_dir()

def skip_rel_prefixes(root: Path, section: dict[str, Any] | None = None) -> tuple[str, ...]:
    section = section or {}
    configured = section.get("skip_rel_prefixes")
    if isinstance(configured, list):
        return tuple(str(p) for p in configured)
    return _AGENTIZED_SKIP_REL_PREFIXES if is_agentized_repo(root) else ()

def _is_skipped_rel(rel: str, prefixes: tuple[str, ...]) -> bool:
    rel = rel.replace("\\", "/")
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in prefixes)

def _changed_files(root: Path, base_ref: str) -> list[str]:
    filters = "ACMRD"
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"--diff-filter={filters}", f"{base_ref}...HEAD"],
        cwd=root, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"--diff-filter={filters}", base_ref],
            cwd=root, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "git diff failed").strip()
            raise GitDiffError(f"git diff failed for base_ref={base_ref!r}: {err[:500]}")
    return sorted({
        line.strip().replace("\\", "/")
        for line in proc.stdout.splitlines() if line.strip()
    })

def _read_package_deps(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_bytes().decode(_JSON_ENCODING))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            names.update(str(k) for k in block)
    return names

def _read_python_deps(root: Path, prefixes: tuple[str, ...]) -> list[tuple[str, set[str]]]:
    found: list[tuple[str, set[str]]] = []
    for path in [root / "pyproject.toml", *sorted(root.glob("requirements*.txt"))]:
        if not path.is_file():
            continue
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        try:
            lower = path.read_bytes().decode(_JSON_ENCODING, errors="ignore").lower()
        except OSError:
            continue
        names = {
            dep for dep in ORM_PY_DEPS
            if re.search(rf"(?m)^\s*{re.escape(dep)}\b", lower)
            or f'"{dep}"' in lower or f"'{dep}'" in lower
        }
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
        if _is_skipped_rel(rel, prefixes) or set(Path(rel).parts) & _SKIP_DIR_NAMES:
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
    return rel.replace("\\", "/").rstrip("/")

def _looks_like_db_dir(rel: str) -> str | None:
    rel = _normalize_rel(rel)
    if rel not in DB_DIR_ROOT_NAMES and not any(rel.endswith(suf) for suf in DB_DIR_SUFFIXES):
        return None
    if rel.endswith("pgtap") or rel == "pgtap":
        return "pgtap_dir"
    if rel.endswith(("db/tests", "tests/db", "tests/sql")):
        return "db_tests_dir"
    return "migrations_dir"

def _uniq_evidence(evidence: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    uniq: list[dict[str, str]] = []
    for item in evidence:
        key = (item.get("kind", ""), item.get("path", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq

def detect_e2e(root: Path, *, skip_prefixes: tuple[str, ...] | None = None) -> dict[str, Any]:
    prefixes = skip_rel_prefixes(root) if skip_prefixes is None else skip_prefixes
    evidence: list[dict[str, str]] = []
    for path in _iter_files(root):
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        if path.name in E2E_CONFIG_NAMES:
            evidence.append({"kind": "config", "path": rel})
        if path.name == "package.json":
            hit = sorted(d for d in E2E_PKG_DEPS if d in _read_package_deps(path))
            if hit:
                evidence.append({"kind": "package_dep", "path": rel, "detail": ",".join(hit)})
        parts = Path(rel).parts
        for i, part in enumerate(parts[:-1]):
            cypress_e2e = part == "cypress" and i + 1 < len(parts) - 1 and parts[i + 1] == "e2e"
            if part not in E2E_DIR_NAMES and not cypress_e2e:
                continue
            dir_rel = "/".join(parts[: i + 2] if part == "cypress" else parts[: i + 1])
            if dir_rel.startswith("reports/") or not _dir_has_real_files(root, dir_rel, prefixes):
                continue
            evidence.append({"kind": "tests_dir", "path": dir_rel})
    uniq = _uniq_evidence(evidence)
    return {"present": bool(uniq), "evidence": uniq, "framework": _e2e_framework(uniq)}

def detect_db_layer(root: Path, *, skip_prefixes: tuple[str, ...] | None = None) -> dict[str, Any]:
    prefixes = skip_rel_prefixes(root) if skip_prefixes is None else skip_prefixes
    evidence: list[dict[str, str]] = []
    for marker in DB_DIR_ROOT_NAMES:
        if _is_skipped_rel(marker, prefixes):
            continue
        if _dir_has_real_files(root, marker, prefixes):
            kind = _looks_like_db_dir(marker)
            if kind is not None:
                evidence.append({"kind": kind, "path": marker})
    for name in DB_FILE_MARKERS:
        if (root / name).is_file() and not _is_skipped_rel(name, prefixes):
            evidence.append({"kind": "marker_file", "path": name})
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
            hit = sorted(d for d in ORM_JS_DEPS if d in _read_package_deps(path))
            if hit:
                evidence.append({"kind": "orm_dep", "path": rel, "detail": ",".join(hit)})
        if path.suffix == ".sql":
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:4000].lower()
            except OSError:
                continue
            if "select plan(" in head or "pgtap" in head or "tap:" in head:
                evidence.append({"kind": "pgtap_sql", "path": rel})
    for rel, names in _read_python_deps(root, prefixes):
        evidence.append({"kind": "orm_dep", "path": rel, "detail": ",".join(sorted(names))})
    uniq = _uniq_evidence(evidence)
    return {"present": bool(uniq), "evidence": uniq, "framework": _db_framework(uniq)}

def _e2e_framework(evidence: list[dict[str, str]]) -> str | None:
    blob = " ".join(f"{e.get('path', '')} {e.get('detail', '')}" for e in evidence).lower()
    if "playwright" in blob:
        return "playwright"
    if "cypress" in blob:
        return "cypress"
    return None

def _db_framework(evidence: list[dict[str, str]]) -> str | None:
    kinds = {e.get("kind") for e in evidence}
    if "pgtap_sql" in kinds or "pgtap_dir" in kinds:
        return "pgtap"
    blob = " ".join(f"{e.get('path', '')} {e.get('detail', '')}" for e in evidence).lower()
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
    return (root / "supabase" / "config.toml").is_file()

def default_test_command(
    gate_name: str, detection: dict[str, Any], *, root: Path | None = None
) -> str | None:
    framework = detection.get("framework")
    if gate_name == "e2e":
        if framework == "playwright":
            return "npx playwright test"
        if framework == "cypress":
            return "npx cypress run"
        return None
    if gate_name == "db_tests":
        if root is not None and _has_supabase(root):
            return "supabase test db"
        if framework == "pgtap":
            return "pg_prove db/tests/*.sql tests/db/*.sql pgtap/*.sql"
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
        expires = datetime.fromisoformat(expires_raw)
    except ValueError:
        return False
    if expires.tzinfo is None:
        return False
    clock = now if now is not None else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        return False
    remaining = (expires - clock).total_seconds()
    if remaining <= 0:
        return False
    return remaining <= timedelta(days=max_days).total_seconds()

def _is_real_test_file(path: Path) -> bool:
    if path.name in PLACEHOLDER_NAMES:
        return False
    try:
        if path.stat().st_size == 0:
            return False
        return bool(path.read_text(encoding="utf-8", errors="ignore").strip())
    except OSError:
        return False

def _collect_real_tests(
    root: Path, patterns: list[str] | tuple[str, ...], prefixes: tuple[str, ...]
) -> list[str]:
    return sorted(
        _rel(root, path)
        for path in _iter_files(root)
        if not _is_skipped_rel(_rel(root, path), prefixes)
        and _matches_any(_rel(root, path), patterns)
        and _is_real_test_file(path)
    )

def _run_command(root: Path, command: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["bash", "-lc", command],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return int(proc.returncode), str(proc.stdout or "").strip()[:_CMD_OUTPUT_LIMIT]

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

def _payload(gate_name: str, enabled: str, mode: str, **extra: Any) -> dict[str, Any]:
    base = {"schemaVersion": 1, "gate": gate_name, "enabled": enabled, "mode": mode}
    base.update(extra)
    return base

def _evaluate_layer(
    root: Path,
    *,
    gate_name: str,
    section: dict[str, Any],
    detection: dict[str, Any],
) -> int:
    if gate_name == "e2e":
        default_source_globs, default_test_globs = DEFAULT_E2E_SOURCE_GLOBS, DEFAULT_E2E_TEST_GLOBS
    elif gate_name == "db_tests":
        default_source_globs, default_test_globs = DEFAULT_DB_SOURCE_GLOBS, DEFAULT_DB_TEST_GLOBS
    else:
        raise ValueError(f"unknown layer gate: {gate_name}")
    enabled = _enabled_mode(section.get("enabled", "auto"))
    mode = str(section.get("mode") or "hard").lower()
    present = bool(detection.get("present"))
    prefixes = skip_rel_prefixes(root, section)
    evidence = detection.get("evidence") or []

    if enabled == "false":
        if present and not disable_decision_valid(section):
            return _finalize(
                root, gate_name, mode,
                _payload(
                    gate_name, enabled, mode, present=present, evidence=evidence,
                    skipped=False, reason="disabled_without_decision",
                ),
                [{
                    "kind": "disabled_without_decision",
                    "detail": (
                        f"{gate_name}.enabled=false without valid disable_decision "
                        "(reason + approved_by + expires ≤14d)."
                    ),
                }],
            )
        return _finalize(
            root, gate_name, mode,
            _payload(
                gate_name, enabled, mode, present=present, skipped=True,
                reason="disabled" if not present else "disabled_by_decision",
            ),
            [],
        )

    if enabled == "auto" and not present:
        return _finalize(
            root, gate_name, mode,
            _payload(
                gate_name, enabled, mode, present=False, evidence=evidence,
                skipped=True, reason="layer_absent",
            ),
            [],
        )

    findings: list[dict[str, str]] = []
    require_for_changed = bool(section.get("require_tests_for_changed", True))
    if present and not require_for_changed and not disable_decision_valid(section):
        return _finalize(
            root, gate_name, mode,
            _payload(
                gate_name, enabled, mode, present=True, evidence=evidence,
                skipped=False, reason="require_disabled_without_decision",
            ),
            [{
                "kind": "require_disabled_without_decision",
                "detail": (
                    f"{gate_name}: require_tests_for_changed=false while layer present "
                    "needs disable_decision (reason + approved_by + expires ≤14d)"
                ),
            }],
        )

    source_globs = list(section.get("source_globs") or default_source_globs)
    test_globs = list(section.get("test_globs") or default_test_globs)
    existing_tests = _collect_real_tests(root, test_globs, prefixes)
    if not existing_tests:
        return _finalize(
            root, gate_name, mode,
            _payload(
                gate_name, enabled, mode, present=True, evidence=evidence,
                skipped=False, existingTests=[], reason="missing_tests",
            ),
            [{
                "kind": "missing_tests",
                "detail": (
                    f"{gate_name} layer present but no real test files match {test_globs}"
                ),
            }],
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
        return _finalize(
            root, gate_name, mode,
            _payload(
                gate_name, enabled, mode, present=True, evidence=evidence,
                skipped=False, baseRef=base, reason="git_diff_failed",
            ),
            [{"kind": "git_diff_failed", "detail": str(exc)}],
        )

    source_changed = [
        p for p in changed
        if _matches_any(p, source_globs) and not _matches_any(p, test_globs)
    ]
    # LIMITATION: any test_globs path counts — not mapped 1:1 to a source file.
    tests_changed = [p for p in changed if _matches_any(p, test_globs)]
    if require_for_changed and source_changed and not tests_changed:
        findings.append({
            "kind": "tests_not_updated",
            "detail": (
                f"Changed {gate_name} sources require matching test updates "
                f"(changed sources: {', '.join(source_changed[:8])})"
            ),
        })

    configured_cmd = section.get("test_command")
    if configured_cmd is None or (isinstance(configured_cmd, str) and not configured_cmd.strip()):
        cmd = default_test_command(gate_name, detection, root=root)
        if not cmd:
            findings.append({
                "kind": "test_command_required",
                "detail": (
                    f"{gate_name}: test_command null/empty and no autodetect for "
                    f"framework={detection.get('framework')!r}"
                ),
            })
    else:
        cmd = str(configured_cmd)

    cmd_out = ""
    if cmd:
        cmd_rc, cmd_out = _run_command(root, cmd)
        if cmd_rc != 0:
            findings.append({
                "kind": "test_command_failed",
                "detail": f"test_command exit {cmd_rc}: {cmd_out or '(no output)'}",
            })

    return _finalize(
        root, gate_name, mode,
        _payload(
            gate_name, enabled, mode, present=True, evidence=evidence, skipped=False,
            baseRef=base, changedSources=source_changed, changedTests=tests_changed,
            existingTests=existing_tests[:50], requireTestsForChanged=require_for_changed,
            testCommandNote=cmd_out, testCommand=cmd,
            note="tests_changed matches any test_globs path — not per-source mapping",
        ),
        findings,
    )

def _ensure_gate_list(gates: list[Any], name: str) -> bool:
    as_str = [str(g) for g in gates]
    if name in as_str:
        return False
    if "mutation" in as_str:
        gates.insert(as_str.index("mutation"), name)
    else:
        gates.append(name)
    return True

def upgrade_layer_gate_config(data: dict[str, Any]) -> list[str]:
    upgraded: list[str] = []
    for section_name in LAYER_GATE_NAMES:
        section = data.get(section_name)
        if not isinstance(section, dict):
            data[section_name] = {
                "enabled": "auto", "mode": "hard", "require_tests_for_changed": True,
            }
            upgraded.append(f"{section_name}.created")
            section = data[section_name]
        mode_raw = section.get("mode")
        if isinstance(mode_raw, str) and mode_raw.lower() == "warn":
            section["mode"] = "hard"
            upgraded.append(f"{section_name}.mode")
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

def _section_or_default(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    section = cfg.get(name)
    if isinstance(section, dict):
        return section
    return {"enabled": "auto", "mode": "hard", "require_tests_for_changed": True}

def apply_layer_upgrades_to_repo(root: Path, context_rel: str = DEFAULT_CONTEXT) -> list[str]:
    """Persist AGE-31 layer upgrades into quality.json when needed."""
    from . import quality as quality_mod

    data = quality_mod.load_quality(root, context_rel)
    upgrades = upgrade_layer_gate_config(data)
    if upgrades:
        quality_mod.save_quality(root, data, context_rel)
    return upgrades

def install_ensure_quality_hook() -> None:
    """Wrap connect.ensure_quality_config; quality import installs (connect.py untouched)."""
    from . import connect as connect_mod

    current = connect_mod.ensure_quality_config
    if hasattr(current, "_age31_layer_hook") and current._age31_layer_hook is True:
        current = current._age31_orig  # type: ignore[attr-defined]

    def ensure_quality_config(
        root: Path,
        context_rel: str,
        coverage_pct: float | int | None = None,
    ) -> dict[str, Any]:
        result = current(root, context_rel, coverage_pct=coverage_pct)
        upgrades = apply_layer_upgrades_to_repo(root, context_rel)
        if not upgrades:
            return result
        prior = result["upgraded_modes"] if "upgraded_modes" in result else []
        modes = list(prior)
        modes.extend(upgrades)
        out = dict(result)
        out["upgraded_modes"] = modes
        return out

    ensure_quality_config._age31_layer_hook = True  # type: ignore[attr-defined]
    ensure_quality_config._age31_orig = current  # type: ignore[attr-defined]
    connect_mod.ensure_quality_config = ensure_quality_config  # type: ignore[assignment]

def run_e2e_gate(root: Path | None = None, *, context: str = DEFAULT_CONTEXT) -> int:
    from .quality import load_quality

    root = root or find_repo_root()
    section = _section_or_default(load_quality(root, context), "e2e")
    return _evaluate_layer(
        root, gate_name="e2e", section=section,
        detection=detect_e2e(root, skip_prefixes=skip_rel_prefixes(root, section)),
    )

def run_db_tests_gate(root: Path | None = None, *, context: str = DEFAULT_CONTEXT) -> int:
    from .quality import load_quality

    root = root or find_repo_root()
    section = _section_or_default(load_quality(root, context), "db_tests")
    return _evaluate_layer(
        root, gate_name="db_tests", section=section,
        detection=detect_db_layer(root, skip_prefixes=skip_rel_prefixes(root, section)),
    )

