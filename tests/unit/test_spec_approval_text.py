"""Text helper tests for AGE-28 (mutation-covered)."""
from __future__ import annotations

from agentized.spec_approval_text import (
    _email_local_matches_claim,
    _email_local_part,
    identity_emails,
    is_claim_owner_identity,
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
        "todo_colon": is_placeholder_spec("TODO: write the spec"),
        "see_italic": is_placeholder_spec("See _(TBD)_"),
        "ellipsis_fill": is_placeholder_spec("… fill in later"),
        "dots_fill": is_placeholder_spec("... fill in later"),
        "blank_then_todo": is_placeholder_spec("Real plan\n\nTODO: later"),
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
        "todo_colon": True,
        "see_italic": True,
        "ellipsis_fill": True,
        "dots_fill": True,
        "blank_then_todo": True,
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
    owners = {
        "exact": is_claim_owner_identity("alice", "Alice"),
        "email_vs_angle": is_claim_owner_identity(
            "alice@corp.com", "Alice <alice@corp.com>"
        ),
        "bare_claim_local": is_claim_owner_identity("alice@corp.com", "alice"),
        "noreply": is_claim_owner_identity(
            "12345678+alice@users.noreply.github.com", "alice"
        ),
        "noreply_angle": is_claim_owner_identity(
            "12345678+alice@users.noreply.github.com",
            "Alice <alice@corp.com>",
        ),
        "other": is_claim_owner_identity("bob@corp.com", "alice"),
        "other_vs_angle": is_claim_owner_identity(
            "bob@corp.com", "Alice <alice@corp.com>"
        ),
        "bare_no_email": is_claim_owner_identity("bob", "alice"),
        "empty": is_claim_owner_identity("alice@corp.com", ""),
        "none_claim": is_claim_owner_identity("alice@corp.com", None),  # type: ignore[arg-type]
        "none_ident": is_claim_owner_identity(None, "alice"),  # type: ignore[arg-type]
        "empty_ident": is_claim_owner_identity("", "alice"),
        "xxxx_trap": is_claim_owner_identity("xxxx", None),  # type: ignore[arg-type]
    }
    assert owners == {
        "exact": True,
        "email_vs_angle": True,
        "bare_claim_local": True,
        "noreply": True,
        "noreply_angle": True,
        "other": False,
        "other_vs_angle": False,
        "bare_no_email": False,
        "empty": False,
        "none_claim": False,
        "none_ident": False,
        "empty_ident": False,
        "xxxx_trap": False,
    }
    assert _email_local_part("alice@corp.com") == "alice"
    assert _email_local_part("a@b@c.com") == "a"
    match_got = {
        "empty_locals": _email_local_matches_claim("alice@corp.com", set()),
        "no_at": _email_local_matches_claim("alice", {"alice"}),
        "hit": _email_local_matches_claim("alice@corp.com", {"alice"}),
        "noreply": _email_local_matches_claim(
            "9+alice@users.noreply.github.com", {"alice"}
        ),
        "miss": _email_local_matches_claim("bob@corp.com", {"alice"}),
    }
    assert match_got == {
        "empty_locals": False,
        "no_at": False,
        "hit": True,
        "noreply": True,
        "miss": False,
    }
