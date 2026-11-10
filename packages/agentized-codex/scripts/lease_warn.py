#!/usr/bin/env python3
"""Warn-only path-lease overlap check. Never blocks writes."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _bootstrap() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "runtime" / "agentized").is_dir():
            sys.path.insert(0, str(parent / "runtime"))
            return parent
        if (parent / "AGENTS.md").exists() and (parent / "runtime").is_dir():
            sys.path.insert(0, str(parent / "runtime"))
            return parent
    return Path.cwd()


def main() -> int:
    root = _bootstrap()
    raw = sys.stdin.read()
    payload = {}
    if raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"_raw": raw}

    from agentized.hook_common import extract_paths, lease_warn_for_paths, resolve_root

    root = resolve_root(payload)
    runtime = root / "runtime"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))

    paths = extract_paths(payload)
    # also inspect nested tool_input-style payloads Cursor may send
    if "tool_input" not in payload and isinstance(payload.get("input"), dict):
        paths = list(dict.fromkeys(paths + extract_paths({"tool_input": payload["input"]})))

    warn = lease_warn_for_paths(root, paths)
    if not warn:
        # Always allow; empty warn → silent success for Cursor permission hooks.
        print(
            json.dumps(
                {
                    "permission": "allow",
                    "continue": True,
                    "hookSpecificOutput": {
                        "hookEventName": payload.get("hook_event_name")
                        or payload.get("hookEventName")
                        or "PreToolUse",
                        "permissionDecision": "allow",
                    },
                }
            )
        )
        return 0

    out = {
        # Cursor preToolUse / permission hooks: allow + message
        "permission": "allow",
        "agent_message": warn,
        "additional_context": warn,
        # do not block
        "continue": True,
        # Claude
        "hookSpecificOutput": {
            "hookEventName": payload.get("hook_event_name")
            or payload.get("hookEventName")
            or "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": warn,
            "additionalContext": warn,
        },
        # Codex
        "hookEventName": payload.get("hook_event_name")
        or payload.get("hookEventName")
        or "PreToolUse",
        "systemMessage": warn,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
