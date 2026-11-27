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

        def ensure_runtime_on_path(here=None):
            return Path.cwd()


def _nav_fn():
    try:
        from agentized.context_layout import session_nav_reminder

        return session_nav_reminder
    except ImportError:
        from agentized.hook_common import nav_reminder

        return nav_reminder


def _apply_env(env_result: dict, root: Path) -> dict:
    try:
        from agentized.context_layout import apply_external_env_check

        return apply_external_env_check(env_result, root)
    except ImportError:
        return env_result


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
        from agentized.hook_common import resolve_root

        root = resolve_root(payload) if payload else workspace
        runtime = root / "runtime"
        if runtime.is_dir() and str(runtime) not in sys.path:
            sys.path.insert(0, str(runtime))

        text = _nav_fn()(root)
        try:
            from agentized.env_check import check as env_check

            env_result = _apply_env(env_check(repo_root=root), root)
            text = text + "\n\n" + env_result["message"]
        except Exception as exc:
            text = text + f"\n\n[agent-env-check] unavailable: {exc}"
    except Exception as exc:  # foreign repo without runtime
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
