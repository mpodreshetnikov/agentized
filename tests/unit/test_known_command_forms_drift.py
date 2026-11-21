"""AGE-52: KNOWN_COMMAND_FORMS must match committed harness hook JSON commands."""

from __future__ import annotations

import json
from pathlib import Path

from agentized.hooks_boundary import KNOWN_COMMAND_FORMS

REPO = Path(__file__).resolve().parents[2]


def _cursor_commands(doc: dict) -> set[str]:
    out: set[str] = set()
    for entries in (doc.get("hooks") or {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("command"), str):
                out.add(entry["command"])
    return out


def _nested_commands(doc: dict) -> set[str]:
    out: set[str] = set()
    for blocks in (doc.get("hooks") or {}).values():
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            for hook in block.get("hooks") or []:
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    out.add(hook["command"])
    return out


def test_known_command_forms_match_repo_harness_json():
    cursor = json.loads((REPO / ".cursor/hooks.json").read_text(encoding="utf-8"))
    claude = json.loads((REPO / ".claude/settings.json").read_text(encoding="utf-8"))
    codex = json.loads((REPO / ".codex/hooks.json").read_text(encoding="utf-8"))
    assert _cursor_commands(cursor) == set(KNOWN_COMMAND_FORMS["cursor"])
    assert _nested_commands(claude) == set(KNOWN_COMMAND_FORMS["claude"])
    assert _nested_commands(codex) == set(KNOWN_COMMAND_FORMS["codex"])
