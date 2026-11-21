"""Pure merge of Agentized harness hooks (AGE-23). No filesystem I/O."""
from __future__ import annotations

from typing import Any

from .hooks_boundary import is_agentized_command

__all__ = ("is_agentized_command",)

CURSOR_VERSION_KEY = "version"


class HooksShapeError(ValueError):
    """Valid JSON with wrong hooks shape — caller must refuse writes."""


def cursor_entry_is_ours(
    entry: Any, *, previously_owned: frozenset[str] | None = None
) -> bool:
    if not isinstance(entry, dict):
        return False
    cmd = entry.get("command")
    if previously_owned and isinstance(cmd, str) and cmd in previously_owned:
        return True
    return is_agentized_command(cmd, "cursor")


def nested_hook_is_ours(
    hook: Any,
    harness: str,
    *,
    previously_owned: frozenset[str] | None = None,
) -> bool:
    if not isinstance(hook, dict):
        return False
    cmd = hook.get("command")
    if previously_owned and isinstance(cmd, str) and cmd in previously_owned:
        return True
    return is_agentized_command(cmd, harness)


def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _require_hooks_map(hooks: Any, *, ctx: str) -> dict:
    if hooks is None:
        return {}
    if not isinstance(hooks, dict):
        raise HooksShapeError(
            f"{ctx}: hooks must be an object, got {type(hooks).__name__}"
        )
    return hooks


def _require_event_list(value: Any, *, ctx: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HooksShapeError(
            f"{ctx}: event value must be a list, got {type(value).__name__}"
        )
    return value


def _require_block_hooks(block: dict, *, ctx: str) -> list:
    if "hooks" not in block:
        return []
    nested = block.get("hooks")
    if not isinstance(nested, list):
        raise HooksShapeError(
            f"{ctx}: block hooks must be a list, got {type(nested).__name__}"
        )
    return nested


def merge_cursor_hooks(
    existing: dict | None,
    desired_hooks: dict,
    *,
    previously_owned: frozenset[str] | None = None,
) -> dict:
    doc = dict(existing) if isinstance(existing, dict) else {}
    existing_hooks = _require_hooks_map(doc.get("hooks"), ctx="cursor")
    hooks_out: dict[str, list] = {}
    for event in dict.fromkeys([*existing_hooks.keys(), *desired_hooks.keys()]):
        foreign = [
            e
            for e in _require_event_list(
                existing_hooks.get(event), ctx=f"cursor.{event}"
            )
            if not cursor_entry_is_ours(e, previously_owned=previously_owned)
        ]
        ours = list(_as_list(desired_hooks.get(event)))
        if foreign or ours:
            hooks_out[event] = foreign + ours
    doc["hooks"] = hooks_out
    if CURSOR_VERSION_KEY not in doc:
        doc[CURSOR_VERSION_KEY] = 1
    return doc


def merge_nested_hooks(
    existing_hooks: dict | None,
    desired_hooks: dict,
    *,
    harness: str,
    previously_owned: frozenset[str] | None = None,
) -> dict:
    existing = _require_hooks_map(existing_hooks, ctx=harness)
    out: dict[str, list] = {}
    for event in dict.fromkeys([*existing.keys(), *desired_hooks.keys()]):
        foreign_blocks: list = []
        for block in _require_event_list(
            existing.get(event), ctx=f"{harness}.{event}"
        ):
            if not isinstance(block, dict):
                foreign_blocks.append(block)
                continue
            nested = _require_block_hooks(block, ctx=f"{harness}.{event}")
            kept = [
                h
                for h in nested
                if not nested_hook_is_ours(
                    h, harness, previously_owned=previously_owned
                )
            ]
            if not nested:
                foreign_blocks.append(block)
                continue
            if not kept:
                continue
            if len(kept) == len(nested):
                foreign_blocks.append(block)
            else:
                rebuilt = dict(block)
                rebuilt["hooks"] = kept
                foreign_blocks.append(rebuilt)
        ours = list(_as_list(desired_hooks.get(event)))
        if foreign_blocks or ours:
            out[event] = foreign_blocks + ours
    return out


def merge_claude_settings(
    existing: dict | None,
    desired_hooks: dict,
    *,
    previously_owned: frozenset[str] | None = None,
) -> dict:
    doc = dict(existing) if isinstance(existing, dict) else {}
    doc["hooks"] = merge_nested_hooks(
        doc.get("hooks"),
        desired_hooks,
        harness="claude",
        previously_owned=previously_owned,
    )
    return doc


def merge_codex_hooks(
    existing: dict | None,
    desired: dict,
    *,
    previously_owned: frozenset[str] | None = None,
) -> dict:
    doc = dict(existing) if isinstance(existing, dict) else {}
    desired_hooks = _as_dict(
        desired.get("hooks") if isinstance(desired, dict) else None
    )
    doc["hooks"] = merge_nested_hooks(
        doc.get("hooks"),
        desired_hooks,
        harness="codex",
        previously_owned=previously_owned,
    )
    if (
        isinstance(desired, dict)
        and "description" not in doc
        and "description" in desired
    ):
        doc["description"] = desired["description"]
    return doc


def plan_json_change(path: str, before: dict, after: dict) -> dict[str, Any]:
    if before == after:
        action = "skip"
    elif not before:
        action = "create"
    else:
        action = "merge"
    return {
        "path": path,
        "action": action,
        "changed": before != after,
        "before_hooks_events": sorted(_as_dict(before.get("hooks")).keys()),
        "after_hooks_events": sorted(_as_dict(after.get("hooks")).keys()),
    }


def _collect_owned_commands(hooks_doc: dict, *, harness: str) -> list[str]:
    hooks = hooks_doc.get("hooks") if isinstance(hooks_doc.get("hooks"), dict) else {}
    owned: list[str] = []
    if harness == "cursor":
        for entries in hooks.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if cursor_entry_is_ours(entry) and isinstance(entry, dict):
                    cmd = entry.get("command")
                    if isinstance(cmd, str):
                        owned.append(cmd)
        return owned
    for blocks in hooks.values():
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            for hook in block.get("hooks") or []:
                if nested_hook_is_ours(hook, harness) and isinstance(hook, dict):
                    cmd = hook.get("command")
                    if isinstance(cmd, str):
                        owned.append(cmd)
    return owned


def merge_marketplace_plugins(existing: dict | None, ours: dict) -> dict:
    """Merge Codex marketplace by plugin name; keep foreign plugins."""
    doc = dict(existing) if isinstance(existing, dict) else {}
    if "name" not in doc and isinstance(ours.get("name"), str):
        doc["name"] = ours["name"]
    existing_plugins = doc.get("plugins")
    if existing_plugins is None:
        existing_plugins = []
    if not isinstance(existing_plugins, list):
        raise HooksShapeError(
            f"marketplace: plugins must be a list, got {type(existing_plugins).__name__}"
        )
    ours_plugins = ours.get("plugins") or []
    if not isinstance(ours_plugins, list):
        raise HooksShapeError("marketplace: desired plugins must be a list")
    ours_names = {
        p.get("name")
        for p in ours_plugins
        if isinstance(p, dict) and isinstance(p.get("name"), str)
    }
    foreign = [
        p
        for p in existing_plugins
        if not (isinstance(p, dict) and p.get("name") in ours_names)
    ]
    doc["plugins"] = foreign + [p for p in ours_plugins if isinstance(p, dict)]
    return doc
