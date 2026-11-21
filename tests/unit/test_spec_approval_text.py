"""Text helper tests for AGE-28 (mutation-covered)."""

from __future__ import annotations

from agentized.spec_approval_text import (
    MIN_REAL_SPEC_WORDS,
    _approval_body_without_fences,
    _email_local_matches_claim,
    _email_local_part,
    human_committer_emails,
    identity_emails,
    is_agent_commit_identity,
    is_claim_owner_identity,
    is_owner_or_agent_identity,
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


def test_parse_approvers_skips_italic_and_fenced():
    italic = "approved-by: _(pending)_\napproved-by: bob@x.test\n"
    assert parse_approvers(italic) == ["bob@x.test"]
    # Empty approved-by must not stop parsing later lines (continue, not break).
    blank_then = "approved-by:   \napproved-by: bob@x.test\n"
    assert parse_approvers(blank_then) == ["bob@x.test"]
    fenced = "Example:\n```\napproved-by: fake@example.com\n```\napproved-by: real@example.com\n"
    assert parse_approvers(fenced) == ["real@example.com"]
    nested = "```text\napproved-by: inside@x.test\n```\napproved-by: _(skip)_\n"
    assert parse_approvers(nested) == []
    both = "approved-by: a@x.test\n```\napproved-by: b@x.test\n```\napproved-by: c@x.test\n"
    assert parse_approvers(both) == ["a@x.test", "c@x.test"]
    stripped = _approval_body_without_fences(both)
    assert "XXXX" not in stripped
    assert "b@x.test" not in stripped
    assert "a@x.test" in stripped and "c@x.test" in stripped


def test_placeholder_trivial_and_fill():
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
        "x": is_placeholder_spec("x"),
        "dot": is_placeholder_spec("."),
        "fill_tag": is_placeholder_spec("<fill>"),
        "fill_upper": is_placeholder_spec("PLEASE <FILL> THIS NOW"),
        "fill_me": is_placeholder_spec("fill-me"),
        "unchecked": is_placeholder_spec("- [ ] do the thing"),
        "punct_only": is_placeholder_spec("!!!"),
        "single_a": is_placeholder_spec("a"),
        "two_ok": is_placeholder_spec("ok"),
        "ok_case": is_placeholder_spec("OK"),
        "na": is_placeholder_spec("n/a"),
        "wip": is_placeholder_spec("wip"),
        "see_chat": is_placeholder_spec("see chat"),
        "plan_tbd": is_placeholder_spec("plan: tbd"),
        "long_tbd": is_placeholder_spec("Finish the plan: TBD"),
        "two_words": is_placeholder_spec("Ship it."),
        "Ship the gate.": is_placeholder_spec("Ship the gate."),
        "multi\nline": is_placeholder_spec("Real plan for more"),
        "later_none": is_placeholder_spec("Real plan for more\n\nnone"),
        "later_italic": is_placeholder_spec("Ship the gate.\nSee _(note)_"),
    }
    assert MIN_REAL_SPEC_WORDS == 3
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
        "x": True,
        "dot": True,
        "fill_tag": True,
        "fill_upper": True,
        "fill_me": True,
        "unchecked": True,
        "punct_only": True,
        "single_a": True,
        "two_ok": True,
        "ok_case": True,
        "na": True,
        "wip": True,
        "see_chat": True,
        "plan_tbd": True,
        "long_tbd": True,
        "two_words": True,
        "Ship the gate.": False,
        "multi\nline": False,
        "later_none": True,
        "later_italic": True,
    }


def test_emails_owners_agents_committers():
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
        "email_vs_angle": is_claim_owner_identity("alice@corp.com", "Alice <alice@corp.com>"),
        "bare_claim_local": is_claim_owner_identity("alice@corp.com", "alice"),
        "noreply": is_claim_owner_identity("12345678+alice@users.noreply.github.com", "alice"),
        "noreply_angle": is_claim_owner_identity(
            "12345678+alice@users.noreply.github.com",
            "Alice <alice@corp.com>",
        ),
        "other": is_claim_owner_identity("bob@corp.com", "alice"),
        "other_vs_angle": is_claim_owner_identity("bob@corp.com", "Alice <alice@corp.com>"),
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

    assert is_agent_commit_identity("cursoragent") is True
    assert is_agent_commit_identity("cursoragent@cursor.com") is True
    assert is_agent_commit_identity("Cursor Agent <cursoragent@cursor.com>") is True
    assert is_agent_commit_identity("github-actions@github.com") is True
    assert is_agent_commit_identity("bob@example.com") is False
    assert is_agent_commit_identity("") is False
    assert is_agent_commit_identity(None) is False  # type: ignore[arg-type]

    assert is_owner_or_agent_identity("cursoragent@cursor.com", "worker-a") is True
    assert is_owner_or_agent_identity("worker-a", "worker-a") is True
    assert is_owner_or_agent_identity("bob@x.test", "worker-a") is False

    assert human_committer_emails(None) == set()
    assert human_committer_emails(set()) == set()
    assert human_committer_emails({"cursoragent@cursor.com", "bob@x.test"}) == {"bob@x.test"}
    assert human_committer_emails({"Bob <bob@x.test>"}) == {"bob@x.test"}
    # List with agent first — continue (not break) must still reach the human.
    assert human_committer_emails(["cursoragent@cursor.com", "bob@x.test"]) == {"bob@x.test"}
    # Multiple humans — |= must accumulate (not replace).
    assert human_committer_emails({"alice@x.test", "bob@x.test"}) == {
        "alice@x.test",
        "bob@x.test",
    }

    assert _email_local_part("alice@corp.com") == "alice"
    assert _email_local_part("a@b@c.com") == "a"
    match_got = {
        "empty_locals": _email_local_matches_claim("alice@corp.com", set()),
        "no_at": _email_local_matches_claim("alice", {"alice"}),
        "hit": _email_local_matches_claim("alice@corp.com", {"alice"}),
        "noreply": _email_local_matches_claim("9+alice@users.noreply.github.com", {"alice"}),
        "miss": _email_local_matches_claim("bob@corp.com", {"alice"}),
    }
    assert match_got == {
        "empty_locals": False,
        "no_at": False,
        "hit": True,
        "noreply": True,
        "miss": False,
    }
