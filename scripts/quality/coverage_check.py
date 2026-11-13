#!/usr/bin/env python3
"""Parallel-style per-module + combined coverage threshold gate (Orbit mechanism)."""
from __future__ import annotations

import concurrent.futures
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT / "runtime") not in sys.path:
    sys.path.insert(0, str(ROOT / "runtime"))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agentized.paths import DEFAULT_CONTEXT, find_repo_root  # noqa: E402
from agentized.quality import load_quality, module_thresholds  # noqa: E402

from coverage_report import build_report, write_report  # noqa: E402


def _check_module(root: Path, cfg: dict, module: dict, summary_mod: dict) -> int:
    mid = module.get("id") or "?"
    totals = summary_mod["totals"]
    line_min, branch_min = module_thresholds(cfg, module)
    ok = True
    if totals["lines_pct"] + 1e-9 < line_min:
        print(
            f"[coverage-check] FAIL {mid} lines {totals['lines_pct']}% < {line_min}%",
            file=sys.stderr,
        )
        ok = False
    if totals["branches_pct"] + 1e-9 < branch_min:
        print(
            f"[coverage-check] FAIL {mid} branches {totals['branches_pct']}% < {branch_min}%",
            file=sys.stderr,
        )
        ok = False
    if ok:
        print(
            f"[coverage-check] PASS {mid} lines={totals['lines_pct']}% "
            f"branches={totals['branches_pct']}%"
        )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    root = find_repo_root()
    context = DEFAULT_CONTEXT
    args = list(argv or sys.argv[1:])
    if "--context" in args:
        i = args.index("--context")
        context = args[i + 1]
    skip_tests = "--skip-tests" in args

    cfg = load_quality(root, context)
    if not skip_tests:
        # Run module test commands (coverage producers) sequentially for stable artifacts,
        # then threshold checks in parallel like Orbit's run-coverage-check-parallel.
        for module in cfg.get("modules") or []:
            cmd = module.get("test_command")
            if not cmd:
                continue
            print(f"[coverage-check] running tests for {module.get('id')}: {cmd}")
            proc = subprocess.run(cmd, shell=True, cwd=root)
            if proc.returncode != 0:
                print(f"[coverage-check] module tests failed: {module.get('id')}", file=sys.stderr)
                return proc.returncode

    summary = build_report(root, context)
    write_report(root, summary)

    codes: list[int] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(summary["modules"]))) as pool:
        futs = [
            pool.submit(
                _check_module,
                root,
                cfg,
                next(m for m in cfg["modules"] if m.get("id") == mid),
                mod,
            )
            for mid, mod in summary["modules"].items()
        ]
        for fut in concurrent.futures.as_completed(futs):
            codes.append(fut.result())

    g_lines = summary["coverage_thresholds"]["lines"]
    g_branches = summary["coverage_thresholds"]["branches"]
    combined = summary["combined"]
    if combined["lines_pct"] + 1e-9 < g_lines or combined["branches_pct"] + 1e-9 < g_branches:
        print(
            f"[coverage-check] FAIL combined lines={combined['lines_pct']}% "
            f"branches={combined['branches_pct']}% "
            f"(need ≥{g_lines}% / ≥{g_branches}%)",
            file=sys.stderr,
        )
        codes.append(1)
    else:
        print(
            f"[coverage-check] PASS combined lines={combined['lines_pct']}% "
            f"branches={combined['branches_pct']}%"
        )
        codes.append(0)

    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
