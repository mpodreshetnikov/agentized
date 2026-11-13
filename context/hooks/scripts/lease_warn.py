#!/usr/bin/env python3
"""Warn-only path-lease overlap check. Never blocks writes."""
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
    raw = sys.stdin.read()
    payload: dict = {}
    if raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"_raw": raw}

    event = (
        payload.get("hook_event_name")
        or payload.get("hookEventName")
        or "PreToolUse"
    )
    allow = {
        "permission": "allow",
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "allow",
        },
    }

    try:
        from agentized.hook_common import extract_paths, lease_warn_for_paths, resolve_root
    except Exception as exc:  # noqa: BLE001
        allow["agent_message"] = f"[lease-warn] unavailable: {exc}"
        print(json.dumps(allow, ensure_ascii=False))
        return 0

    root = resolve_root(payload) if payload else workspace
    runtime = root / "runtime"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))

    paths = extract_paths(payload)
    if "tool_input" not in payload and isinstance(payload.get("input"), dict):
        paths = list(dict.fromkeys(paths + extract_paths({"tool_input": payload["input"]})))

    warn = lease_warn_for_paths(root, paths)
    if not warn:
        print(json.dumps(allow))
        return 0

    out = {
        "permission": "allow",
        "agent_message": warn,
        "additional_context": warn,
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "allow",
            "permissionDecisionReason": warn,
            "additionalContext": warn,
        },
        "hookEventName": event,
        "systemMessage": warn,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
