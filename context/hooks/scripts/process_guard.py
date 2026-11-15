#!/usr/bin/env python3
"""Claim-before-edits process guard. May deny Write/Edit in agent sessions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
try:
    from _bootstrap import ensure_runtime_on_path
except ImportError:  # copied next to hooks without package layout
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
        from agentized.hook_common import context_rel, extract_paths, resolve_root
        from agentized.process_control import claim_check
    except Exception as exc:  # noqa: BLE001 — never crash the harness
        allow["agent_message"] = f"[process-guard] unavailable: {exc}"
        print(json.dumps(allow, ensure_ascii=False))
        return 0

    root = resolve_root(payload) if payload else workspace
    runtime = root / "runtime"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))

    paths = extract_paths(payload)
    if "tool_input" not in payload and isinstance(payload.get("input"), dict):
        paths = list(dict.fromkeys(paths + extract_paths({"tool_input": payload["input"]})))
    if not paths:
        print(json.dumps(allow))
        return 0

    ctx = context_rel(root)
    result = claim_check(root, paths, context_rel=ctx)
    msg = result.get("message") or ""
    if result.get("ok", True):
        if msg and result.get("mode") == "warn":
            allow["agent_message"] = msg
            allow["additional_context"] = msg
            allow["hookSpecificOutput"]["permissionDecisionReason"] = msg
            allow["systemMessage"] = msg
        print(json.dumps(allow, ensure_ascii=False))
        return 0

    deny = {
        "permission": "deny",
        "continue": False,
        "agent_message": msg,
        "additional_context": msg,
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
        },
        "hookEventName": event,
        "systemMessage": msg,
    }
    print(json.dumps(deny, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
