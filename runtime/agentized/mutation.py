"""Incremental mutation hard gate on covered changed lines (mutmut).

Required gate (Orbit Lead + Maxim intent): fail the build when the covered
mutation score on changed sources is below context/quality.json threshold.
Self-contained under runtime/agentized for connected foreign repos.
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

DURABLE_SETUP = """[mutmut]
# Top-level `agentized` symlink → runtime/agentized so trampoline keys match imports.
source_paths = agentized
pytest_add_cli_args_test_selection = tests/unit
mutate_only_covered_lines = false
use_git_change_detection = false
also_copy =
  tests/
  context/
  pyproject.toml
  setup.cfg
"""


def _ensure_agentized_link(root: Path) -> bool:
    link = root / "agentized"
    if link.exists() or link.is_symlink():
        return False
    link.symlink_to(Path("runtime") / "agentized", target_is_directory=True)
    return True


def _changed_py_files(root: Path, base_ref: str, prefixes: list[str]) -> list[str]:
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
        lines.extend(f"  {item}" for item in only_mutate)
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
    total = killed + survived + no_tests + timeout
    covered = killed + survived + timeout
    return {
        "killed": killed,
        "survived": survived,
        "no_tests": no_tests,
        "timeout": timeout,
        "other": other,
        "totalMutants": total,
        "files": files,
        "mutationScore": round(10000 * (killed + timeout) / total) / 100 if total else None,
        "mutationScoreCovered": (
            round(10000 * (killed + timeout) / covered) / 100 if covered else None
        ),
    }


def run_mutation(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
) -> int:
    root = root or find_repo_root()
    os.chdir(root)
    cfg = load_quality(root, context)
    mut = cfg.get("mutation") or {}
    if not mut.get("enabled", True):
        print("[mutation] disabled — skip")
        return 0

    base = os.environ.get("MUTATION_BASE") or mut.get("base_ref") or "origin/main"
    min_score = float(mut.get("min_score_covered", 50))
    prefixes = [
        str(src).replace("\\", "/")
        for module in cfg.get("modules") or []
        for src in module.get("source") or []
    ] or ["runtime/agentized"]
    changed = _changed_py_files(root, base, prefixes)
    include_globs = list(mut.get("include_globs") or [])
    if include_globs:
        changed = [
            path
            for path in changed
            if any(fnmatch.fnmatch(path, pat) for pat in include_globs)
        ]
    if not changed:
        path = _write_summary(
            root,
            {
                "schemaVersion": 1,
                "mode": "incremental-skip",
                "base": base,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "mutationScore": None,
                "mutationScoreCovered": None,
                "survived": 0,
                "killed": 0,
                "no_tests": 0,
                "files": [],
                "gate": "hard",
                "passed": True,
                "note": f"No mutable source files changed vs {base}",
            },
        )
        print(f"[mutation] skip vs {base}; wrote {path.relative_to(root)}")
        return 0

    print(f"[mutation] hard gate vs {base} ({len(changed)} files, min_score_covered={min_score})")
    for f in changed:
        print(f"  {f}")

    unit_tests = root / "tests" / "unit"
    if unit_tests.is_dir():
        pre = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit", "-q", "--tb=no"],
            cwd=root,
        )
        if pre.returncode != 0:
            print("[mutation] unit tests failed before mutation", file=sys.stderr)
            return pre.returncode

    only = [
        ("agentized/" + p[len("runtime/agentized/") :])
        if p.startswith("runtime/agentized/")
        else p
        for p in changed
    ]
    setup = root / "setup.cfg"
    backup = setup.read_text(encoding="utf-8") if setup.exists() else DURABLE_SETUP
    created_link = _ensure_agentized_link(root)
    _write_setup(root, only)
    # Wipe prior mutants so a failed current run cannot PASS on cached results.
    mutants_dir = root / "mutants"
    if mutants_dir.exists():
        shutil.rmtree(mutants_dir, ignore_errors=True)
    env = {**os.environ, "PYTHONPATH": str(root)}
    mutmut_rc = 0
    try:
        run = subprocess.run([sys.executable, "-m", "mutmut", "run"], cwd=root, env=env)
        mutmut_rc = run.returncode or 0
        if mutmut_rc != 0:
            print(f"[mutation] mutmut exited {mutmut_rc}", file=sys.stderr)
    finally:
        setup.write_text(backup if backup.strip() else DURABLE_SETUP, encoding="utf-8")
        link = root / "agentized"
        if created_link and link.is_symlink():
            link.unlink(missing_ok=True)

    stats = _collect_stats(root)
    reasons: list[str] = []
    # Always fail closed on runner failure (Codex P1) — never trust cached/partial stats.
    if mutmut_rc != 0:
        reasons.append(f"mutmut_exit={mutmut_rc}")
    if mut.get("break_on_no_tests", True) and stats["no_tests"] > 0:
        reasons.append(f"no_tests={stats['no_tests']}")
    score = stats["mutationScoreCovered"]
    if score is None and changed and stats["totalMutants"] == 0 and mutmut_rc == 0:
        reasons.append("no_mutants_evaluated")
    if score is not None and score + 1e-9 < min_score:
        reasons.append(f"score_covered={score}<{min_score}")
    if mut.get("break_on_survived") and stats["survived"] > 0:
        reasons.append(f"survived={stats['survived']}")

    passed = not reasons
    path = _write_summary(
        root,
        {
            "schemaVersion": 1,
            "mode": "incremental",
            "base": base,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "gate": "hard",
            "scope": "covered_changed_lines",
            "tool": "mutmut",
            "minScoreCovered": min_score,
            "changedFiles": changed,
            "passed": passed,
            "reasons": reasons,
            "mutmutExit": mutmut_rc,
            **stats,
        },
    )
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


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    return run_mutation(find_repo_root(), context=context)


if __name__ == "__main__":
    raise SystemExit(main())
