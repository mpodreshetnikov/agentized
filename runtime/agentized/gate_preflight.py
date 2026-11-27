"""Consumer first-push preflight around coverage, mutation and format-disable gates (AGE-85).

Wired from the CLI so ``coverage_check.py`` / ``mutation.py`` / ``format_disable_gate.py``
stay untouched (whole-file mutation would otherwise re-open their full surface).

- No modules configured (valid empty consumer quality.json) → coverage skip, said
  out loud.
- Module source/test paths missing on disk → fail closed with a clear message.
- True first push (base is ``origin/main`` and it does not exist yet) → mutation
  skip with a summary; any other unresolvable base goes to the gate (fail closed).
- Format-disable gate on that first push → scan the whole HEAD tree vs the empty
  tree (every disable counts as new); only the ancestry check is dropped.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import coverage_check, format_disable_gate, mutation, mutation_ast
from .paths import DEFAULT_CONTEXT
from .process_size import EMPTY_TREE, ref_exists
from .quality import load_quality

_TEST_PATH_TOKEN = re.compile(r"(?:^|\s)(tests/unit|tests/quality|tests|test)(?=\s|$)")


def module_layout_error(root: Path, module: dict) -> str | None:
    mid = module.get("id") or "?"
    for src in module.get("source") or []:
        if not (root / str(src)).exists():
            return (
                f"[coverage-check] FAIL {mid}: source path {src!r} missing. "
                "Fix context/quality.json modules (re-run connect on a detected "
                "src/tests layout, or remove stale dogfood entries)."
            )
    mentioned = _TEST_PATH_TOKEN.findall(str(module.get("test_command")))
    if mentioned and not any((root / m).exists() for m in mentioned):
        return (
            f"[coverage-check] FAIL {mid}: test path(s) {sorted(set(mentioned))} "
            "missing on disk. Add tests or edit context/quality.json modules."
        )
    return None


def _first_push(root: Path, base: str) -> bool:
    return base == "origin/main" and not ref_exists(root, base)


def run_coverage_gate(root: Path, *, context: str = DEFAULT_CONTEXT) -> int:
    modules = load_quality(root, context)["modules"]
    if not modules:
        print(
            "[coverage-check] no modules configured — skip module tests and "
            "coverage thresholds (valid empty consumer quality.json)"
        )
        return 0
    for module in modules:
        err = module_layout_error(root, module)
        if err:
            print(err, file=sys.stderr)
            return 1
    return coverage_check.run_coverage_check(root, context=context)


def run_mutation_gate(root: Path, *, context: str = DEFAULT_CONTEXT) -> int:
    cfg = load_quality(root, context)
    base = os.environ.get("MUTATION_BASE") or cfg["mutation"].get("base_ref") or "origin/main"
    if not _first_push(root, base):
        return mutation_ast.run_mutation(root, context=context)
    note = f"mutation base {base!r} unavailable — skip until remote baseline exists"
    path = mutation._write_summary(
        root,
        {
            "schemaVersion": 1,
            "mode": "incremental-skip",
            "base": base,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "gate": "hard",
            "passed": True,
            "note": note,
        },
    )
    print(f"[mutation] skip — {note}; wrote {path.relative_to(root)}")
    return 0


def _no_ancestry_check(root: Path, base_ref: str) -> None:
    del root, base_ref


def run_format_disable_check(root: Path, *, base_ref: str | None = None) -> dict:
    base = base_ref or os.environ.get("PROCESS_BASE") or format_disable_gate.DEFAULT_BASE
    if not _first_push(root, base):
        return format_disable_gate.format_disable_check(root, base_ref=base_ref)
    orig = format_disable_gate.validate_process_base
    format_disable_gate.validate_process_base = _no_ancestry_check
    try:
        return format_disable_gate.format_disable_check(root, base_ref=EMPTY_TREE)
    finally:
        format_disable_gate.validate_process_base = orig
