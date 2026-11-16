"""Hard gates for e2e and DB tests when those layers are auto-detected.

When a repo has Playwright/Cypress (etc.) or a DB migration/pgTAP layer,
changed product areas must ship matching tests. Absent layers → skip (pass).
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

_SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "mutants",
    "coverage",
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

# Example trees shipped with Agentized — never count as the host project's layers.
_SKIP_REL_PREFIXES = (
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

E2E_DIR_MARKERS = ("e2e", "tests/e2e", "cypress/e2e", "playwright")

DB_DIR_MARKERS = (
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

DEFAULT_E2E_SOURCE_GLOBS = (
    "app/**",
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


def _is_skipped_rel(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in _SKIP_REL_PREFIXES)


def _changed_files(root: Path, base_ref: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            # No git / bad base → treat as empty change set (skip enforce).
            return []
    return sorted(
        {
            line.strip().replace("\\", "/")
            for line in proc.stdout.splitlines()
            if line.strip()
        }
    )


def _read_package_deps(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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


def _dir_has_files(root: Path, rel_dir: str) -> bool:
    base = root / rel_dir
    if not base.is_dir():
        return False
    for path in base.rglob("*"):
        if path.is_file():
            # skip nested junk
            parts = set(path.relative_to(root).parts)
            if parts & _SKIP_DIR_NAMES:
                continue
            return True
    return False


def detect_e2e(root: Path) -> dict[str, Any]:
    evidence: list[dict[str, str]] = []
    for name in E2E_CONFIG_NAMES:
        path = root / name
        if path.is_file():
            evidence.append({"kind": "config", "path": name})
    # Nested configs (monorepo apps), bounded walk — skip Agentized example fixtures.
    for path in _iter_files(root):
        rel = _rel(root, path)
        if _is_skipped_rel(rel):
            continue
        if path.name in E2E_CONFIG_NAMES and rel not in {e["path"] for e in evidence}:
            evidence.append({"kind": "config", "path": rel})
    for marker in E2E_DIR_MARKERS:
        if _is_skipped_rel(marker):
            continue
        if _dir_has_files(root, marker):
            evidence.append({"kind": "tests_dir", "path": marker})
    # package.json deps (root + one-level packages/*)
    pkg_paths = [root / "package.json"]
    packages = root / "packages"
    if packages.is_dir():
        for child in packages.iterdir():
            cand = child / "package.json"
            if cand.is_file():
                pkg_paths.append(cand)
    for pkg in pkg_paths:
        rel = _rel(root, pkg) if pkg.is_relative_to(root) else pkg.name
        if _is_skipped_rel(rel):
            continue
        deps = _read_package_deps(pkg)
        hit = sorted(d for d in E2E_PKG_DEPS if d in deps)
        if hit:
            evidence.append(
                {
                    "kind": "package_dep",
                    "path": rel,
                    "detail": ",".join(hit),
                }
            )
    # Unique by path+kind
    seen: set[tuple[str, str]] = set()
    uniq: list[dict[str, str]] = []
    for item in evidence:
        key = (item.get("kind", ""), item.get("path", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return {"present": bool(uniq), "evidence": uniq}


def detect_db_layer(root: Path) -> dict[str, Any]:
    evidence: list[dict[str, str]] = []
    for marker in DB_DIR_MARKERS:
        if _is_skipped_rel(marker):
            continue
        if not _dir_has_files(root, marker):
            continue
        if marker == "pgtap":
            kind = "pgtap_dir"
        elif marker in {"db/tests", "tests/db", "tests/sql"}:
            kind = "db_tests_dir"
        else:
            kind = "migrations_dir"
        evidence.append({"kind": kind, "path": marker})
    for name in DB_FILE_MARKERS:
        if (root / name).is_file():
            evidence.append({"kind": "marker_file", "path": name})
    # prisma schema often pairs with migrations
    prisma = root / "prisma" / "schema.prisma"
    if prisma.is_file():
        evidence.append({"kind": "marker_file", "path": "prisma/schema.prisma"})
    # Lightweight pgTAP content sniff on *.sql under common test dirs only
    for rel_dir in ("pgtap", "db/tests", "tests/db", "tests/sql"):
        if _is_skipped_rel(rel_dir):
            continue
        base = root / rel_dir
        if not base.is_dir():
            continue
        for path in base.rglob("*.sql"):
            rel = _rel(root, path)
            if _is_skipped_rel(rel):
                continue
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:4000]
            except OSError:
                continue
            lower = head.lower()
            if "select plan(" in lower or "pgtap" in lower or "tap:" in lower:
                evidence.append({"kind": "pgtap_sql", "path": rel})
                break
    seen: set[tuple[str, str]] = set()
    uniq: list[dict[str, str]] = []
    for item in evidence:
        key = (item.get("kind", ""), item.get("path", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return {"present": bool(uniq), "evidence": uniq}


def _enabled_mode(raw: Any) -> str:
    if raw is True or str(raw).lower() == "true":
        return "true"
    if raw is False or str(raw).lower() == "false":
        return "false"
    return "auto"


def _collect_repo_matches(root: Path, patterns: list[str] | tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for path in _iter_files(root):
        rel = _rel(root, path)
        if _matches_any(rel, patterns):
            hits.append(rel)
    return sorted(hits)


def _run_optional_command(root: Path, command: str | None) -> tuple[int, str]:
    if not command or not str(command).strip():
        return 0, ""
    proc = subprocess.run(
        str(command),
        cwd=root,
        shell=True,
        capture_output=True,
        text=True,
    )
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out[:4000]


def _write_report(root: Path, kind: str, payload: dict[str, Any]) -> Path:
    out_dir = root / "reports" / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{kind}-summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _evaluate_layer(
    root: Path,
    *,
    gate_name: str,
    section: dict[str, Any],
    detection: dict[str, Any],
    default_source_globs: tuple[str, ...],
    default_test_globs: tuple[str, ...],
) -> int:
    enabled = _enabled_mode(section.get("enabled", "auto"))
    mode = str(section.get("mode") or "hard").lower()
    if enabled == "false":
        payload = {
            "schemaVersion": 1,
            "gate": gate_name,
            "enabled": enabled,
            "mode": mode,
            "present": detection.get("present"),
            "skipped": True,
            "reason": "disabled",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "findings": [],
            "passed": True,
        }
        _write_report(root, gate_name, payload)
        print(f"[{gate_name}] disabled — skip")
        return 0

    present = bool(detection.get("present"))
    if enabled == "auto" and not present:
        payload = {
            "schemaVersion": 1,
            "gate": gate_name,
            "enabled": enabled,
            "mode": mode,
            "present": False,
            "evidence": detection.get("evidence") or [],
            "skipped": True,
            "reason": "layer_absent",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "findings": [],
            "passed": True,
        }
        _write_report(root, gate_name, payload)
        print(f"[{gate_name}] layer absent — skip")
        return 0

    # enabled true with absent layer still enforces "must have tests when sources change"
    # but without markers we only know via source/test globs.
    base = (
        os.environ.get("LAYER_GATES_BASE")
        or os.environ.get("MUTATION_BASE")
        or section.get("base_ref")
        or "origin/main"
    )
    source_globs = list(section.get("source_globs") or default_source_globs)
    test_globs = list(section.get("test_globs") or default_test_globs)
    require_for_changed = bool(section.get("require_tests_for_changed", True))
    changed = _changed_files(root, str(base))
    source_changed = [
        p for p in changed if _matches_any(p, source_globs) and not _matches_any(p, test_globs)
    ]
    tests_changed = [p for p in changed if _matches_any(p, test_globs)]
    existing_tests = _collect_repo_matches(root, test_globs)
    findings: list[dict[str, str]] = []

    if not source_changed:
        payload = {
            "schemaVersion": 1,
            "gate": gate_name,
            "enabled": enabled,
            "mode": mode,
            "present": present or enabled == "true",
            "evidence": detection.get("evidence") or [],
            "skipped": True,
            "reason": "no_relevant_source_changes",
            "baseRef": base,
            "changedSources": [],
            "changedTests": tests_changed,
            "existingTests": existing_tests[:50],
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "findings": [],
            "passed": True,
        }
        _write_report(root, gate_name, payload)
        print(f"[{gate_name}] no relevant source changes — skip")
        return 0

    if not existing_tests:
        findings.append(
            {
                "kind": "missing_tests",
                "detail": (
                    f"{gate_name} layer present and sources changed, but no test files "
                    f"match {test_globs}"
                ),
            }
        )
    elif require_for_changed and not tests_changed:
        findings.append(
            {
                "kind": "tests_not_updated",
                "detail": (
                    f"Changed {gate_name} sources require matching test updates "
                    f"(changed sources: {', '.join(source_changed[:8])})"
                ),
            }
        )

    cmd_rc, cmd_out = _run_optional_command(root, section.get("test_command"))
    if cmd_rc != 0:
        findings.append(
            {
                "kind": "test_command_failed",
                "detail": f"test_command exit {cmd_rc}: {cmd_out or '(no output)'}",
            }
        )

    passed = not findings if mode != "warn" else True
    payload = {
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
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
        "passed": not findings if mode == "hard" else True,
        "testCommandNote": cmd_out,
    }
    _write_report(root, gate_name, payload)

    if findings:
        print(f"[{gate_name}] {len(findings)} finding(s) (mode={mode})")
        for item in findings[:20]:
            print(f"  {item['kind']}: {item['detail'][:240]}")
    else:
        print(f"[{gate_name}] PASS (sources={len(source_changed)}, tests_updated={len(tests_changed)})")

    if mode == "warn":
        print(f"[{gate_name}] warn mode — not failing the gate")
        return 0
    return 0 if passed else 1


def run_e2e_gate(root: Path | None = None, *, context: str = DEFAULT_CONTEXT) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg.get("e2e") or {}
    detection = detect_e2e(root)
    return _evaluate_layer(
        root,
        gate_name="e2e",
        section=section,
        detection=detection,
        default_source_globs=DEFAULT_E2E_SOURCE_GLOBS,
        default_test_globs=DEFAULT_E2E_TEST_GLOBS,
    )


def run_db_tests_gate(root: Path | None = None, *, context: str = DEFAULT_CONTEXT) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg.get("db_tests") or {}
    detection = detect_db_layer(root)
    return _evaluate_layer(
        root,
        gate_name="db_tests",
        section=section,
        detection=detection,
        default_source_globs=DEFAULT_DB_SOURCE_GLOBS,
        default_test_globs=DEFAULT_DB_TEST_GLOBS,
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
