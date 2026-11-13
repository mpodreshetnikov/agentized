#!/usr/bin/env python3
"""Harness-agnostic session-start reminder for Agentized NAV pointer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
try:
    from _bootstrap import ensure_runtime_on_path
except ImportError:
    sys.path.insert(0, str(_HERE.parent))
    try:
        from _bootstrap import ensure_runtime_on_path
    except ImportError:

        def ensure_runtime_on_path(here=None):  # type: ignore[misc]
            return Path.cwd()


def main() -> int:
    workspace = ensure_runtime_on_path(_HERE)
    payload: dict = {}
    raw = sys.stdin.read()
    if raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

    text = f"Agentized session check: workspace={workspace}"
    try:
        from agentized.hook_common import nav_reminder, resolve_root

        root = resolve_root(payload) if payload else workspace
        runtime = root / "runtime"
        if runtime.is_dir() and str(runtime) not in sys.path:
            sys.path.insert(0, str(runtime))
            from agentized.hook_common import nav_reminder as nav_reminder  # noqa: F811

        text = nav_reminder(root)
        try:
            from agentized.env_check import check as env_check

            env_result = env_check(repo_root=root)
            text = text + "\n\n" + env_result["message"]
        except Exception as exc:  # noqa: BLE001
            text = text + f"\n\n[agent-env-check] unavailable: {exc}"
    except Exception as exc:  # noqa: BLE001 — foreign repo without runtime
        text = (
            "Agentized session check: runtime unavailable "
            f"({exc}). Install Agentized on PATH or keep runtime/ in-repo."
        )

    out = {
        "additional_context": text,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        },
        "hookEventName": "SessionStart",
        "additionalContext": text,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
