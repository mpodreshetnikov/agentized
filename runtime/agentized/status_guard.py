"""Harness status-gate decisions for context/tasks edits (AGE-38).

Fail-closed: broken stdin, unknown payload shape, or status_gates import
failure while touching a task file → deny. Non-task paths allow without
loading status_gates (AGE-22 may land separately).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

_PERM_ALLOW = "allow"
_PERM_DENY = "deny"
_MSG_BROKEN = "[status-guard] REFUSED: broken stdin (invalid JSON)"
_MSG_UNKNOWN = "[status-guard] REFUSED: unknown payload (JSON must be an object)"
_MSG_UNKNOWN_FALLBACK = "[status-guard] REFUSED: unknown payload"
_MSG_GATES_API = "[status-guard] REFUSED: status_gates missing validate API"
_MSG_CONTEXT = "[status-guard] REFUSED: context_rel must be a non-empty string"
_MSG_EDIT = "cannot apply Edit onto task file (old_string mismatch or missing file)"
_EVENT_PRE = "PreToolUse"


def allow_response(event: str) -> dict[str, Any]:
    return {
        "permission": _PERM_ALLOW,
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": _PERM_ALLOW,
        },
    }


def deny_response(event: str, msg: str) -> dict[str, Any]:
    return {
        "permission": _PERM_DENY,
        "continue": False,
        "agent_message": msg,
        "additional_context": msg,
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": _PERM_DENY,
            "permissionDecisionReason": msg,
        },
        "hookEventName": event,
        "systemMessage": msg,
    }


def parse_hook_stdin(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse hook stdin. Returns (payload, error). error set → deny."""
    if not raw.strip():
        return {}, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, _MSG_BROKEN
    if type(data) is not dict:
        return None, _MSG_UNKNOWN
    return data, None


def hook_event_name(payload: dict[str, Any]) -> str:
    named = payload.get("hook_event_name")
    if named:
        return str(named)
    named = payload.get("hookEventName")
    if named:
        return str(named)
    return _EVENT_PRE


def is_task_path(path: str) -> bool:
    """True for task markdown under a tasks/ directory (T-*.md)."""
    parts = str(path).replace("\\", "/").split("/")
    if len(parts) < 2:
        return False
    name = parts[-1]
    # Minimum T-x.md (6 chars): T- + ≥1 char + .md
    if len(name) < 6:
        return False
    if name[:2] != "T-":
        return False
    if name[-3:] != ".md":
        return False
    return "tasks" in parts[:-1]


def is_after_edit(event: str) -> bool:
    if not event:
        return False
    e = str(event).lower().replace("_", "")
    if e == "afterfileedit":
        return True
    if e == "posttooluse":
        return True
    return False


def git_blob(root: Path, rel: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "show", f"HEAD:{rel}"],
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def apply_edits(base: str, tool_input: dict[str, Any]) -> str | None:
    """Apply Cursor-style Edit payload onto ``base``. None if not an edit payload."""
    old_s = tool_input.get("old_string")
    new_s = tool_input.get("new_string")
    if type(old_s) is str and type(new_s) is str:
        if old_s not in base:
            return None
        return base.replace(old_s, new_s, 1)

    edits = tool_input.get("edits")
    if type(edits) is not list:
        return None
    if len(edits) == 0:
        return None

    pairs: list[tuple[str, str]] = []
    for ed in edits:
        if type(ed) is not dict:
            continue
        o = ed.get("old_string")
        n = ed.get("new_string")
        if type(o) is not str:
            continue
        if type(n) is not str:
            continue
        pairs.append((o, n))
    if len(pairs) == 0:
        return None

    merged = base
    for o, n in pairs:
        if o not in merged:
            return None
        merged = merged.replace(o, n, 1)
    return merged


def full_write_text(tool_input: dict[str, Any]) -> str | None:
    for key in ("content", "contents", "body", "text"):
        val = tool_input.get(key)
        if type(val) is str and val.strip() != "":
            return val
    return None


def tool_input_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("tool_input")
    if type(raw) is dict:
        return raw
    raw = payload.get("toolInput")
    if type(raw) is dict:
        return raw
    raw = payload.get("input")
    if type(raw) is dict:
        return raw
    return {}


def candidate_and_old(
    path: Path,
    *,
    root: Path,
    rel: str,
    tool_input: dict[str, Any],
    event: str,
) -> tuple[str | None, str | None]:
    """Return (candidate_text, old_text_for_transition)."""
    on_disk = path.read_text(encoding="utf-8") if path.exists() else None
    if is_after_edit(event):
        blob = git_blob(root, rel)
        if on_disk is None:
            return "", blob
        return on_disk, blob

    full = full_write_text(tool_input)
    if full is not None:
        return full, on_disk

    if on_disk is not None:
        merged = apply_edits(on_disk, tool_input)
        if merged is not None:
            return merged, on_disk

    return None, on_disk


def load_status_gates() -> ModuleType:
    from agentized import status_gates as gates

    return gates


def evaluate_status_guard(
    payload: dict[str, Any],
    *,
    root: Path,
    context_rel: str,
    extract_paths: Callable[[dict[str, Any]], list[str]],
    gates: ModuleType | None = None,
    gates_loader: Callable[[], ModuleType] | None = None,
) -> dict[str, Any]:
    """Decide allow/deny for one hook payload."""
    event = hook_event_name(payload)
    if type(context_rel) is not str or len(context_rel) == 0:
        return deny_response(event, _MSG_CONTEXT)

    tool_input = tool_input_from_payload(payload)
    # Always feed tool_input explicitly so Codex/Claude `input` alias is covered.
    paths = list(
        dict.fromkeys(extract_paths(payload) + extract_paths({"tool_input": tool_input}))
    )
    task_paths = [p for p in paths if is_task_path(p)]
    if len(task_paths) == 0:
        return allow_response(event)

    loader = gates_loader if gates_loader is not None else load_status_gates
    try:
        gates_mod = gates if gates is not None else loader()
    except Exception as exc:  # noqa: BLE001 — fail closed
        return deny_response(
            event, f"[status-guard] REFUSED: status_gates unavailable: {exc}"
        )

    extract_status = getattr(gates_mod, "extract_status", None)
    validate_task_text = getattr(gates_mod, "validate_task_text", None)
    if not callable(extract_status):
        return deny_response(event, _MSG_GATES_API)
    if not callable(validate_task_text):
        return deny_response(event, _MSG_GATES_API)

    errors: list[str] = []
    for rel in task_paths:
        path = Path(rel)
        if not path.is_absolute():
            path = root / rel
        # Prefer repo-relative path for git; fall back to normalized input path.
        try:
            rel_for_git = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel_for_git = Path(str(rel)).as_posix()

        candidate, old_text = candidate_and_old(
            path,
            root=root,
            rel=rel_for_git,
            tool_input=tool_input,
            event=event,
        )
        blank = candidate is None or str(candidate).strip() == ""
        if blank:
            if tool_input.get("new_string") is not None or tool_input.get("edits") is not None:
                errors.append(f"{Path(rel).name}: {_MSG_EDIT}")
            continue

        if old_text:
            old_status = extract_status(old_text)
        else:
            old_status = None
        result = validate_task_text(
            candidate,
            old_status=old_status,
            require_value=True,
            check_transition=old_status is not None,
        )
        if not hasattr(result, "ok") or result.ok is not True:
            message = getattr(result, "message", None)
            if not message:
                message = "invalid task"
            errors.append(f"{Path(rel).name}: {message}")

    if len(errors) == 0:
        return allow_response(event)
    return deny_response(event, "[status-guard] REFUSED: " + "; ".join(errors))


def decide_from_stdin(
    raw: str,
    *,
    root: Path,
    context_rel: str,
    extract_paths: Callable[[dict[str, Any]], list[str]],
    gates: ModuleType | None = None,
    gates_loader: Callable[[], ModuleType] | None = None,
) -> dict[str, Any]:
    """Parse stdin then evaluate. Broken/unknown payload → deny."""
    payload, err = parse_hook_stdin(raw)
    if payload is None:
        # parse_hook_stdin always pairs None payload with a str error message.
        return deny_response(_EVENT_PRE, err or _MSG_UNKNOWN_FALLBACK)
    return evaluate_status_guard(
        payload,
        root=root,
        context_rel=context_rel,
        extract_paths=extract_paths,
        gates=gates,
        gates_loader=gates_loader,
    )
