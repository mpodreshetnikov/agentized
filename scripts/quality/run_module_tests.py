#!/usr/bin/env python3
"""Run each configured module test command from context/quality.json."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "runtime") not in sys.path:
    sys.path.insert(0, str(ROOT / "runtime"))

from agentized.paths import DEFAULT_CONTEXT, find_repo_root  # noqa: E402
from agentized.quality import load_quality  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    root = find_repo_root()
    context = DEFAULT_CONTEXT
    args = list(argv or sys.argv[1:])
    if "--context" in args:
        context = args[args.index("--context") + 1]
    cfg = load_quality(root, context)
    codes = []
    for module in cfg.get("modules") or []:
        cmd = module.get("test_command")
        mid = module.get("id") or "?"
        if not cmd:
            print(f"[module-tests] skip {mid}: no test_command")
            continue
        print(f"[module-tests] {mid}: {cmd}")
        proc = subprocess.run(cmd, shell=True, cwd=root)
        codes.append(proc.returncode)
        if proc.returncode != 0:
            print(f"[module-tests] FAIL {mid}", file=sys.stderr)
    return 0 if codes and all(c == 0 for c in codes) else (1 if codes else 0)


if __name__ == "__main__":
    raise SystemExit(main())
