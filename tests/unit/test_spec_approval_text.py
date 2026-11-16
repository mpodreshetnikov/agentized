"""Text helper tests for AGE-28 (mutation-covered)."""
from __future__ import annotations

from agentized.spec_approval_text import (
    is_placeholder_spec,
    parse_approvers,
    parse_tags,
    participant_email_matches,
    section_body,
)


def test_section_tags_approvers():
    text = "# t\n\n## Spec\n\nBody\nline2\n\n## Approval\n\napproved-by: A\n"
    assert section_body(text, "## Spec") == "Body\nline2"
    assert section_body(text, "## Approval") == "approved-by: A"
    assert section_body(text, "## Missing") is None
    assert section_body("", "## Spec") is None
    assert section_body("## Spec\n\n  \n", "## Spec") == ""
    assert parse_tags("A, b  C") == {"a", "b", "c"}
    assert parse_tags("") == set()
    assert parse_tags("  ,  ") == set()
    assert parse_approvers("approved-by: X\nApproved-By: Y\napproved-by:\n") == ["X", "Y"]
    assert parse_approvers("") == []
    assert parse_approvers("approved-by:   \n") == []
    multi = "## Spec\n\none\n## Other\n\ntwo\n"
    assert section_body(multi, "## Spec") == "one"


def test_placeholder_and_email_match():
    placeholders = {
        "": is_placeholder_spec(""),
        "_(todo)_": is_placeholder_spec("_(todo)_"),
        "TODO": is_placeholder_spec("TODO"),
        "…": is_placeholder_spec("…"),
        "...": is_placeholder_spec("..."),
        "Ship the gate.": is_placeholder_spec("Ship the gate."),
    }
    assert placeholders == {
        "": True,
        "_(todo)_": True,
        "TODO": True,
        "…": True,
        "...": True,
        "Ship the gate.": False,
    }
    allow = ["bob@example.com", "Alice <alice@x.test>"]
    matches = {
        "bob_email": participant_email_matches("bob@example.com", allow),
        "bob_angle": participant_email_matches("Bob <bob@example.com>", allow),
        "local": participant_email_matches("bob", allow),
        "name": participant_email_matches("Alice", allow),
        "eve": participant_email_matches("eve@example.com", allow),
    }
    assert matches == {
        "bob_email": True,
        "bob_angle": True,
        "local": False,
        "name": False,
        "eve": False,
    }
