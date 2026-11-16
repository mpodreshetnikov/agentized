"""Text helper tests for AGE-28 (mutation-covered)."""
from __future__ import annotations

from agentized.spec_approval_text import (
    identity_emails,
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
    assert parse_approvers(None) == []  # type: ignore[arg-type]
    assert parse_approvers("approved-by:   \n") == []
    multi = "## Spec\nfirst line after heading\n## Other\n\ntwo\n"
    assert section_body(multi, "## Spec") == "first line after heading"
    # start index must be heading+1 (not +2)
    spaced = "## Spec\n\nBody after blank\n"
    assert section_body(spaced, "## Spec") == "Body after blank"
    assert parse_tags(None) == set()  # type: ignore[arg-type]


def test_placeholder_and_email_match():
    placeholders = {
        "none": is_placeholder_spec(None),  # type: ignore[arg-type]
        "": is_placeholder_spec(""),
        "_(todo)_": is_placeholder_spec("_(todo)_"),
        "TODO": is_placeholder_spec("TODO"),
        "…": is_placeholder_spec("…"),
        "...": is_placeholder_spec("..."),
        "todo.": is_placeholder_spec("todo."),
        "tbd": is_placeholder_spec("tbd"),
        "todo!": is_placeholder_spec("todo!"),
        "todo!!!!": is_placeholder_spec("todo!!!!"),  # len 8 boundary
        "todolong!": is_placeholder_spec("todolong!"),  # len 9 — not placeholder
        "Ship the gate.": is_placeholder_spec("Ship the gate."),
        "multi\nline": is_placeholder_spec("Real plan\nmore"),
    }
    assert placeholders == {
        "none": True,
        "": True,
        "_(todo)_": True,
        "TODO": True,
        "…": True,
        "...": True,
        "todo.": True,
        "tbd": True,
        "todo!": True,
        "todo!!!!": True,
        "todolong!": False,
        "Ship the gate.": False,
        "multi\nline": False,
    }
    emails = {
        "angle": identity_emails("Alice <alice@x.test>"),
        "bare": identity_emails("bob@example.com"),
        "local": identity_emails("bob"),
        "no_at_angle": identity_emails("X <notanemail>"),
        "empty": identity_emails(""),
        "spaces": identity_emails("a b@c.com"),
        "lt_no_angle_email": identity_emails("weird<a@b.com"),
        "bare_with_space": identity_emails("bob @example.com"),
    }
    assert emails == {
        "angle": {"alice@x.test"},
        "bare": {"bob@example.com"},
        "local": set(),
        "no_at_angle": set(),
        "empty": set(),
        "spaces": set(),
        "lt_no_angle_email": set(),
        "bare_with_space": set(),
    }
    allow = ["bob@example.com", "Alice <alice@x.test>"]
    matches = {
        "bob_email": participant_email_matches("bob@example.com", allow),
        "bob_angle": participant_email_matches("Bob <bob@example.com>", allow),
        "local": participant_email_matches("bob", allow),
        "name": participant_email_matches("Alice", allow),
        "eve": participant_email_matches("eve@example.com", allow),
        "empty_allow": participant_email_matches("bob@example.com", []),
    }
    assert matches == {
        "bob_email": True,
        "bob_angle": True,
        "local": False,
        "name": False,
        "eve": False,
        "empty_allow": False,
    }
