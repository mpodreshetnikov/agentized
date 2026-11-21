"""AGE-51 exact command-form ownership for harness hooks."""

from __future__ import annotations

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


def is_agentized_command(command: Any, harness: str) -> bool:
    """True only when command exactly equals a known Agentized form for harness."""
    if not isinstance(command, str) or not command.strip():
        return False
    known = KNOWN_COMMAND_FORMS.get(harness)
    if not known:
        return False
    # Normalize path separators only; do not strip or rewrite the rest.
    normalized = command.replace("\\", "/")
    return normalized in known
