#!/usr/bin/env python3
"""Incremental mutation hard gate on covered changed lines (mutmut).

Orbit Lead + Maxim intent: required gate on covered changed lines (not advisory).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

from agentized.paths import DEFAULT_CONTEXT, find_repo_root  # noqa: E402
from agentized.quality import load_quality  # noqa: E402

DURABLE_SETUP = """[mutmut]
source_paths = runtime/agentized
pytest_add_cli_args_test_selection = tests/unit
mutate_only_covered_lines = true
use_git_change_detection = false
also_copy =
  tests/
  runtime/
  context/quality.json
  pyproject.toml
  setup.cfg
"""


def _changed_py_files(root: Path, base_ref: str, prefixes: list[str]) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"],
        cwd=root, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref],
            cwd=root, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print(proc.stderr or "git diff failed", file=sys.stderr)
            raise SystemExit(proc.returncode or 1)
    out = []
    for name in proc.stdout.splitlines():
        name = name.strip().replace("\\", "/")
        if not name.endswith(".py"):
            continue
        if name.startswith("tests/") or "/test" in name or name.endswith("_test.py"):
            continue
        if any(name == p or name.startswith(p.rstrip("/") + "/") for p in prefixes):
            out.append(name)
    return sorted(set(out))


def _write_summary(root: Path, payload: dict) -> Path:
    out = root / "reports" / "mutation"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "mutation-summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_setup(root: Path, only_mutate: list[str]) -> None:
    lines = [DURABLE_SETUP.rstrip(), ""]
    if only_mutate:
        lines.append("only_mutate =")
        for item in only_mutate:
            lines.append(f"  {item}")
        lines.append("")
    (root / "setup.cfg").write_text("\n".join(lines), encoding="utf-8")


def _collect_stats(root: Path) -> dict:
    killed = survived = no_tests = timeout = other = 0
    files: list[str] = []
    mutants_dir = root / "mutants"
    for meta in mutants_dir.rglob("*.meta") if mutants_dir.exists() else []:
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        exit_map = data.get("exit_code_by_key") or {}
        if not exit_map:
            continue
        files.append(str(meta.relative_to(mutants_dir)))
        for code in exit_map.values():
            if code in (1, 3):
                killed += 1
            elif code == 0:
                survived += 1
            elif code in (5, 33):
                no_tests += 1
            elif code in (36, 24, 152, 255, -24):
                timeout += 1
            else:
                other += 1
    if killed + survived + no_tests == 0:
        proc = subprocess.run(
            [sys.executable, "-m", "mutmut", "results", "--all"],
            cwd=root, capture_output=True, text=True,
        )
        for line in (proc.stdout or "").splitlines():
            low = line.lower()
            if ": survived" in low:
                survived += 1
            elif ": killed" in low:
                killed += 1
            elif ": no tests" in low:
                no_tests += 1
            elif ": timeout" in low:
                timeout += 1
    total = killed + survived + no_tests + timeout
    covered = killed + survived + timeout
    return {
        "killed": killed, "survived": survived, "no_tests": no_tests,
        "timeout": timeout, "other": other, "totalMutants": total, "files": files,
        "mutationScore": round(10000 * (killed + timeout) / total) / 100 if total else None,
        "mutationScoreCovered": (
            round(10000 * (killed + timeout) / covered) / 100 if covered else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    root = find_repo_root()
    os.chdir(root)
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    cfg = load_quality(root, context)
    mut = cfg.get("mutation") or {}
    if not mut.get("enabled", True):
        print("[mutation] disabled — skip")
        return 0

    base = os.environ.get("MUTATION_BASE") or mut.get("base_ref") or "origin/main"
    prefixes = [
        str(src).replace("\\", "/")
        for module in cfg.get("modules") or []
        for src in module.get("source") or []
    ] or ["runtime/agentized"]
    changed = _changed_py_files(root, base, prefixes)
    if not changed:
        path = _write_summary(root, {
            "schemaVersion": 1, "mode": "incremental-skip", "base": base,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "mutationScore": None, "survived": 0, "killed": 0, "no_tests": 0,
            "files": [], "gate": "hard", "passed": True,
            "note": f"No mutable source files changed vs {base}",
        })
        print(f"[mutation] skip vs {base}; wrote {path.relative_to(root)}")
        return 0

    print(f"[mutation] hard gate vs {base} ({len(changed)} files)")
    for f in changed:
        print(f"  {f}")

    pre = subprocess.run([sys.executable, "-m", "pytest", "tests/unit", "-q", "--tb=no"], cwd=root)
    if pre.returncode != 0:
        print("[mutation] unit tests failed before mutation", file=sys.stderr)
        return pre.returncode

    setup = root / "setup.cfg"
    backup = setup.read_text(encoding="utf-8") if setup.exists() else DURABLE_SETUP
    _write_setup(root, changed)
    try:
        run = subprocess.run([sys.executable, "-m", "mutmut", "run"], cwd=root)
        if run.returncode not in (0, None) and run.returncode != 0:
            print(f"[mutation] mutmut exited {run.returncode}", file=sys.stderr)
    finally:
        setup.write_text(backup if backup.strip() else DURABLE_SETUP, encoding="utf-8")

    stats = _collect_stats(root)
    reasons = []
    if mut.get("break_on_survived", True) and stats["survived"] > 0:
        reasons.append(f"survived={stats['survived']}")
    if mut.get("break_on_no_tests", True) and stats["no_tests"] > 0:
        reasons.append(f"no_tests={stats['no_tests']}")
    passed = not reasons
    path = _write_summary(root, {
        "schemaVersion": 1, "mode": "incremental", "base": base,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "gate": "hard", "scope": "covered_changed_lines", "tool": "mutmut",
        "changedFiles": changed, "passed": passed, "reasons": reasons, **stats,
    })
    print(
        f"[mutation] score={stats['mutationScore']} covered={stats['mutationScoreCovered']} "
        f"killed={stats['killed']} survived={stats['survived']} no_tests={stats['no_tests']}"
    )
    print(f"[mutation] wrote {path.relative_to(root)}")
    if not passed:
        print(f"[mutation] FAIL: {', '.join(reasons)}", file=sys.stderr)
        return 1
    print("[mutation] PASS hard gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
