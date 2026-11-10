#!/usr/bin/env python3
"""Harness-agnostic session-start reminder for Agentized NAV pointer."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _bootstrap():
    here = Path(__file__).resolve()
    # Locate repo root from common install locations.
    candidates = [
        here.parents[3] if len(here.parents) > 3 else None,  # context/hooks/scripts
        here.parents[2] if len(here.parents) > 2 else None,  # .cursor/hooks or .claude/hooks
        here.parents[2] if len(here.parents) > 2 else None,
    ]
    # Walk up looking for runtime/agentized
    for parent in [here.parent, *here.parents]:
        runtime = parent / "runtime"
        if (runtime / "agentized").is_dir():
            sys.path.insert(0, str(runtime))
            return parent
        # hooks under .cursor/hooks → repo root is parents[1]
        if (parent / "AGENTS.md").exists() and (parent / "runtime" / "agentized").is_dir():
            sys.path.insert(0, str(parent / "runtime"))
            return parent
    return Path.cwd()


def main() -> int:
    root = _bootstrap()
    payload = {}
    raw = sys.stdin.read()
    if raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

    from agentized.hook_common import nav_reminder, resolve_root

    root = resolve_root(payload) if payload else root
    # ensure import path for resolved root
    runtime = root / "runtime"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
        from agentized.hook_common import nav_reminder as nav_reminder  # noqa: F811

    text = nav_reminder(root)

    # Cursor sessionStart
    cursor = {"additional_context": text}
    # Claude SessionStart: plain stdout also works; emit JSON for structured consumers
    claude = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }
    # Codex SessionStart
    codex = {
        "hookEventName": "SessionStart",
        "additionalContext": text,
    }
    # Emit a merged response that each harness can pick fields from.
    out = {**cursor, **claude, **codex}
    print(json.dumps(out, ensure_ascii=False))
    # Claude also accepts plain text; keep JSON-only for predictability.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
