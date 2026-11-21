"""AGE-52: hooks_boundary mutation selection."""

from __future__ import annotations
from agentized.hooks_boundary import is_agentized_command


def test_is_agentized_exact_and_abs():
    assert is_agentized_command(".cursor/hooks/session_start.py", "cursor") is True
    assert is_agentized_command(r".cursor\hooks\process_guard.py", "cursor") is True
    assert is_agentized_command("/home/u/repo/.cursor/hooks/lease_warn.py", "cursor") is True
    assert (
        is_agentized_command(r"/home/u\repo\.cursor\hooks\ensure_agent_hooks.py", "cursor") is True
    )
    assert is_agentized_command("", "cursor") is False
    assert is_agentized_command("   ", "cursor") is False
    assert is_agentized_command(None, "cursor") is False
    assert is_agentized_command(1, "cursor") is False
    assert is_agentized_command("echo /x/.cursor/hooks/session_start.py", "cursor") is False
    assert is_agentized_command("nope", "unknown") is False
