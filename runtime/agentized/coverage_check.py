"""Per-module + combined coverage threshold gate (Orbit parallel-check mechanism)."""

from __future__ import annotations

import concurrent.futures
import re
import subprocess
import sys
from pathlib import Path

from .coverage_report import build_report, write_report
from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality, module_thresholds

_TEST_PATH_TOKEN = re.compile(r"(?:^|[\s])(tests(?:/unit|/quality)?|test)(?:[\s]|$)")


def _module_layout_error(root: Path, module: dict) -> str | None:
    """Fail-closed message when module source/tests paths are missing (AGE-85)."""
    mid = module.get("id") or "?"
    for src in module.get("source") or []:
        if not (root / str(src)).exists():
            return (
                f"[coverage-check] FAIL {mid}: source path {src!r} missing. "
                "Fix context/quality.json modules (re-run connect on a detected "
                "src/tests layout, or remove stale dogfood entries)."
            )
    cmd = str(module.get("test_command") or "")
    mentioned = _TEST_PATH_TOKEN.findall(cmd)
    if mentioned and not any((root / m).exists() for m in mentioned):
        return (
            f"[coverage-check] FAIL {mid}: test path(s) {sorted(set(mentioned))} "
            "missing on disk. Add tests or edit context/quality.json modules."
        )
    return None


def _check_module(cfg: dict, module: dict, summary_mod: dict) -> int:
    mid = module.get("id") or "?"
    totals = summary_mod["totals"]
    line_min, branch_min = module_thresholds(cfg, module)
    ok = True
    if not summary_mod.get("artifact_ok", True):
        print(
            f"[coverage-check] FAIL {mid} missing/unusable coverage artifacts: "
            f"{summary_mod.get('missing_artifacts') or ['(none)']}",
            file=sys.stderr,
        )
        return 1
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


def run_coverage_check(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
    skip_tests: bool = False,
) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    modules = list(cfg.get("modules") or [])
    if not modules:
        print(
            "[coverage-check] no modules configured — skip module tests and "
            "coverage thresholds (valid empty consumer quality.json)"
        )
        summary = build_report(root, context)
        write_report(root, summary)
        return 0

    if not skip_tests:
        for module in modules:
            layout_err = _module_layout_error(root, module)
            if layout_err:
                print(layout_err, file=sys.stderr)
                return 1
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
    if not summary["combined_pass"]:
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


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    skip_tests = "--skip-tests" in args
    return run_coverage_check(find_repo_root(), context=context, skip_tests=skip_tests)


if __name__ == "__main__":
    raise SystemExit(main())
