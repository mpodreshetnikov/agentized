"""AGE-51 exact command-form ownership for harness hooks."""

from __future__ import annotations

import re
from typing import Any

AGENTIZED_SCRIPTS = frozenset(
    {
        "session_start.py",
        "process_guard.py",
        "lease_warn.py",
        "ensure_agent_hooks.py",
    }
)

KNOWN_COMMAND_FORMS: dict[str, frozenset[str]] = {
    "cursor": frozenset(
        {
            ".cursor/hooks/session_start.py",
            ".cursor/hooks/process_guard.py",
            ".cursor/hooks/lease_warn.py",
            ".cursor/hooks/ensure_agent_hooks.py",
        }
    ),
    "claude": frozenset(
        {
            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/session_start.py"',
            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/process_guard.py"',
            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/lease_warn.py"',
            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/ensure_agent_hooks.py"',
        }
    ),
    "codex": frozenset(
        {
            'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/session_start.py"',
            'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/process_guard.py"',
            'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/lease_warn.py"',
            'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/ensure_agent_hooks.py"',
        }
    ),
}

_SCRIPT_ALT = "|".join(sorted(re.escape(s) for s in AGENTIZED_SCRIPTS))
# Whole-command absolute aliases only (AGE-52) — never substring / compound.
_ABS_CURSOR = re.compile(rf"^/.+/\.cursor/hooks/(?:{_SCRIPT_ALT})$")
_ABS_CLAUDE = re.compile(
    rf'^python3 (?:"/[^"]+/\.claude/hooks/(?:{_SCRIPT_ALT})"|'
    rf"/[^ ]+/\.claude/hooks/(?:{_SCRIPT_ALT}))$"
)
_ABS_CODEX = re.compile(
    rf'^python3 (?:"/[^"]+/\.codex/hooks/(?:{_SCRIPT_ALT})"|'
    rf"/[^ ]+/\.codex/hooks/(?:{_SCRIPT_ALT}))$"
)
_ABS_FORMS = {
    "cursor": _ABS_CURSOR,
    "claude": _ABS_CLAUDE,
    "codex": _ABS_CODEX,
}


def is_agentized_command(command: Any, harness: str) -> bool:
    """True for exact known forms, or whole-command absolute path to our scripts."""
    if not isinstance(command, str) or not command.strip():
        return False
    known = KNOWN_COMMAND_FORMS.get(harness)
    if not known:
        return False
    # Normalize path separators only; do not strip or rewrite the rest.
    normalized = command.replace("\\", "/")
    if normalized in known:
        return True
    abs_re = _ABS_FORMS.get(harness)
    return bool(abs_re and abs_re.fullmatch(normalized))
