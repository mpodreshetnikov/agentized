"""Harness status-gate decisions for context/tasks edits (AGE-38). Fail-closed."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

_PERM_ALLOW = "allow"
_PERM_DENY = "deny"
_MSG_BROKEN = "[status-guard] REFUSED: broken stdin (invalid JSON)"
_MSG_UNKNOWN = "[status-guard] REFUSED: unknown payload (JSON must be an object)"
_MSG_UNKNOWN_FALLBACK = "[status-guard] REFUSED: unknown payload"
_MSG_GATES_API = "[status-guard] REFUSED: status_gates missing validate API"
_MSG_CONTEXT = "[status-guard] REFUSED: context_rel must be a non-empty string"
_MSG_EDIT = "cannot apply Edit onto task file (old_string mismatch or missing file)"
_MSG_UNBUILDABLE = (
    "cannot build candidate text for task file (empty/whitespace write or unknown tool shape)"
)
_MSG_EVAL = "[status-guard] REFUSED: evaluation error: {exc}"
_EVENT_PRE = "PreToolUse"
_TEXT_ENCODING = "utf-8"


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


def _has_write_key(tool_input: dict[str, Any]) -> bool:
    for key in ("content", "contents", "body", "text"):
        if key in tool_input:
            return True
    return False


def _has_edit_keys(tool_input: dict[str, Any]) -> bool:
    if tool_input.get("new_string") is not None:
        return True
    return tool_input.get("edits") is not None


def candidate_and_old(
    path: Path,
    *,
    root: Path | str,
    rel: str,
    tool_input: dict[str, Any],
    event: str,
) -> tuple[str | None, str | None]:
    """Return (candidate_text, old_text_for_transition). PreToolUse only.

    ``path`` must be absolute (evaluate joins root). Relative path → (None, None).
    """
    # Call-site must pass real rel/event strings (kills None / "None" mutants).
    if type(rel) is not str or type(event) is not str:
        return None, None
    if len(rel) == 0 or len(event) == 0:
        return None, None
    # root is required for the API (evaluate always passes it); reject None.
    if root is None:
        return None, None
    if not path.is_absolute():
        return None, None
    target = path
    # rel basename must match the task file (kills rel_for_git=None/"None" mutants).
    if Path(rel).name != target.name:
        return None, None
    on_disk = target.read_text(encoding=_TEXT_ENCODING) if target.exists() else None

    full = full_write_text(tool_input)
    if full is not None:
        return full, on_disk

    if _has_write_key(tool_input):
        # Explicit empty/whitespace Write → unbuildable (deny at caller).
        return None, on_disk

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

    root = Path(root)
    tool_input = tool_input_from_payload(payload)
    # Always feed tool_input explicitly so Codex/Claude `input` alias is covered.
    # `input`-only illegal-transition tests kill tool_input key mutants.
    paths = list(dict.fromkeys(extract_paths(payload) + extract_paths({"tool_input": tool_input})))
    task_paths = [p for p in paths if is_task_path(p)]
    if len(task_paths) == 0:
        return allow_response(event)

    loader = gates_loader if gates_loader is not None else load_status_gates
    try:
        gates_mod = gates if gates is not None else loader()
    except Exception as exc:  # noqa: BLE001 — fail closed
        return deny_response(event, f"[status-guard] REFUSED: status_gates unavailable: {exc}")

    extract_status = getattr(gates_mod, "extract_status", None)
    validate_task_text = getattr(gates_mod, "validate_task_text", None)
    if not callable(extract_status):
        return deny_response(event, _MSG_GATES_API)
    if not callable(validate_task_text):
        return deny_response(event, _MSG_GATES_API)

    errors: list[str] = []
    for rel in task_paths:
        raw_path = Path(rel)
        # String-join relative so is_absolute and-False cannot pathlib-collapse.
        if raw_path.is_absolute():
            path = raw_path
        else:
            path = Path(f"{root.as_posix()}/{raw_path.as_posix()}")
        # Prefer repo-relative path for display; fall back to normalized input.
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
            if _has_write_key(tool_input):
                errors.append(f"{Path(rel).name}: {_MSG_UNBUILDABLE}")
            elif _has_edit_keys(tool_input):
                errors.append(f"{Path(rel).name}: {_MSG_EDIT}")
            else:
                errors.append(f"{Path(rel).name}: {_MSG_UNBUILDABLE}")
            continue

        if old_text:
            # Real status_gates.extract_status returns "" when missing — treat as None.
            old_status = extract_status(old_text) or None
        else:
            old_status = None
        # AGE-49/#37 API: value line always required; no require_value kwarg.
        result = validate_task_text(
            candidate,
            old_status=old_status,
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
    """Parse stdin then evaluate. Broken/unknown payload / eval errors → deny."""
    payload, err = parse_hook_stdin(raw)
    if payload is None:
        # parse_hook_stdin always pairs None payload with a str error message.
        return deny_response(_EVENT_PRE, err or _MSG_UNKNOWN_FALLBACK)
    try:
        return evaluate_status_guard(
            payload,
            root=root,
            context_rel=context_rel,
            extract_paths=extract_paths,
            gates=gates,
            gates_loader=gates_loader,
        )
    except Exception as exc:  # noqa: BLE001 — fail closed (PermissionError, bad edits, …)
        return deny_response(_EVENT_PRE, _MSG_EVAL.format(exc=exc))
