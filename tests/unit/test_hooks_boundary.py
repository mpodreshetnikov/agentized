"""AGE-52: hooks_boundary mutation selection."""

from __future__ import annotations

from agentized.hooks_boundary import is_agentized_command


def test_is_agentized_exact_and_abs():
    cases = [
        (".cursor/hooks/session_start.py", "cursor", True),
        (r".cursor\hooks\process_guard.py", "cursor", True),
        ("/home/u/repo/.cursor/hooks/lease_warn.py", "cursor", True),
        (r"/home/u\repo\.cursor\hooks\ensure_agent_hooks.py", "cursor", True),
        ("", "cursor", False),
        ("   ", "cursor", False),
        (None, "cursor", False),
        (1, "cursor", False),
        ("echo /x/.cursor/hooks/session_start.py", "cursor", False),
        ("nope", "unknown", False),
    ]
    assert [(c, h, is_agentized_command(c, h)) for c, h, _ in cases] == [
        (c, h, e) for c, h, e in cases
    ]
