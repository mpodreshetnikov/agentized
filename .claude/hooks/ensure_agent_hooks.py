#!/usr/bin/env python3
"""Self-heal `.githooks` bind before git commit/push (all harnesses).

Cursor Cloud: wire agent-hooks dispatcher → repo `.githooks` when ready.
Local / Claude / Codex: set `core.hooksPath=.githooks` when unset (never
clobber user or Cursor agent-hooks paths).

Wired as:
  - Cursor `beforeShellExecution`
  - Claude / Codex `PreToolUse` (Bash)

Always allows the tool call (never blocks the shell).
"""
from __future__ import annotations

import json
import os
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


def _is_git_mutating(command: str) -> bool:
    c = command.lower()
    return "git " in f" {c}" and any(
        tok in c for tok in (" commit", " push", "commit ", "push ")
    )


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
        or "beforeShellExecution"
    )
    allow = {
        "permission": "allow",
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "allow",
        },
    }

    command = ""
    tool_input = payload.get("tool_input") or payload.get("input") or {}
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    if not command:
        command = str(payload.get("command") or "")

    # Only attempt wiring around git write paths (cheap no-op otherwise).
    if command and not _is_git_mutating(command):
        print(json.dumps(allow))
        return 0

    notes: list[str] = []
    try:
        from agentized.connect import ensure_githooks_path
        from agentized.cursor_agent_git_hooks import (
            agent_hooks_dir,
            git_hooks_problem,
            install,
        )
        from agentized.env_check import is_cursor_cloud
        from agentized.hook_common import resolve_root
    except Exception as exc:  # noqa: BLE001
        allow["agent_message"] = f"[ensure-agent-hooks] unavailable: {exc}"
        print(json.dumps(allow, ensure_ascii=False))
        return 0

    root = resolve_root(payload) if payload else workspace
    env = dict(os.environ)

    # Local / Claude / Codex: idempotent core.hooksPath=.githooks when unset.
    try:
        path_status = ensure_githooks_path(root)
        if path_status == "set":
            notes.append("core.hooksPath=.githooks")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"hooksPath-skip:{exc}")

    # Cursor Cloud: chain agent-hooks → tracked .githooks when dispatcher exists.
    if is_cursor_cloud(env):
        hooks = agent_hooks_dir(root)
        dispatcher = hooks / ".dispatcher"
        if hooks.is_dir() and dispatcher.exists():
            problem = git_hooks_problem(root)
            if problem is not None:
                result = install(root)
                if result.get("changed"):
                    notes.append(result.get("message") or "agent-hooks wired")

    if notes:
        allow["agent_message"] = "[ensure-agent-hooks] " + "; ".join(notes)
    print(json.dumps(allow, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
