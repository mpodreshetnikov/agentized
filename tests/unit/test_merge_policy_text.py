"""Text helper tests for merge_policy_text (mutation-covered)."""

from __future__ import annotations

from agentized.merge_policy_defaults import DEFAULT_AGENT_TRAILER_PREFIXES
from agentized.merge_policy_text import (
    count_stripped_lines,
    identity_emails,
    is_agent_trailer_line,
    parse_coauthors,
    participant_matches,
    strip_agent_trailers,
    trailer_prefixes,
)


def test_trailer_prefixes_and_identity():
    assert trailer_prefixes(None) == list(DEFAULT_AGENT_TRAILER_PREFIXES)
    assert trailer_prefixes({}) == list(DEFAULT_AGENT_TRAILER_PREFIXES)
    assert trailer_prefixes({"agent_trailer_prefixes": []}) == list(DEFAULT_AGENT_TRAILER_PREFIXES)
    assert trailer_prefixes({"agent_trailer_prefixes": "x"}) == list(DEFAULT_AGENT_TRAILER_PREFIXES)
    assert trailer_prefixes({"agent_trailer_prefixes": [" X-Agent: ", "", "  "]}) == [" X-Agent: "]

    allow = ["Alice Example <alice@example.com>", "bob@corp.test"]
    got = {
        "full": participant_matches("Alice Example <alice@example.com>", allow),
        "email": participant_matches("alice@example.com", allow),
        "local": participant_matches("alice", allow),
        "name": participant_matches("Alice Example", allow),
        "bob_email": participant_matches("Bob <bob@corp.test>", allow),
        "eve": participant_matches("Eve <eve@example.com>", allow),
        "empty_id": participant_matches("", allow),
        "empty_list": participant_matches("alice@example.com", []),
        "blank_list": participant_matches("alice@example.com", ["", "  "]),
    }
    assert got == {
        "full": True,
        "email": True,
        "local": False,
        "name": False,
        "bob_email": True,
        "eve": False,
        "empty_id": False,
        "empty_list": False,
        "blank_list": False,
    }
    assert identity_emails("Alice <alice@example.com>") == {"alice@example.com"}
    assert identity_emails("alice") == set()
    assert identity_emails("a@b c") == set()
    assert identity_emails("a@b<x") == set()
    assert identity_emails("user@host") == {"user@host"}
    assert parse_coauthors("x\nCo-authored-by: Bob <b@x>\n") == ["Bob <b@x>"]


def test_strip_and_count():
    assert (
        is_agent_trailer_line("Co-authored-by: Cursor <x>", DEFAULT_AGENT_TRAILER_PREFIXES) is True
    )
    assert (
        is_agent_trailer_line("Co-authored-by: Alice <a>", DEFAULT_AGENT_TRAILER_PREFIXES) is False
    )
    assert is_agent_trailer_line("", DEFAULT_AGENT_TRAILER_PREFIXES) is False
    assert is_agent_trailer_line("   ", DEFAULT_AGENT_TRAILER_PREFIXES) is False
    assert is_agent_trailer_line("Generated-By: bot", DEFAULT_AGENT_TRAILER_PREFIXES) is True
    assert is_agent_trailer_line("hello", ["", "  "]) is False
    msg = "feat\n\nCo-authored-by: Cursor <c@c>\nCo-authored-by: Alice <a@a>\n"
    cleaned = strip_agent_trailers(msg)
    assert cleaned == "feat\n\nCo-authored-by: Alice <a@a>\n"
    assert count_stripped_lines(msg, cleaned) == 1
    assert count_stripped_lines(msg, msg) == 0
    assert count_stripped_lines("a\n", "a\nb\nc\n") == 0
    assert count_stripped_lines("a\nb\n", "a\n") == 1
    assert strip_agent_trailers("solo\n") == "solo\n"
    assert strip_agent_trailers("x\n\nCo-authored-by: Cursor <c>\n\n") == "x\n"
    assert strip_agent_trailers("a\nX-Agent: z\n", ["X-Agent:"]) == "a\n"
    assert strip_agent_trailers("a\n", None) == "a\n"
    assert strip_agent_trailers("body") == "body"
    assert strip_agent_trailers("body\nCo-authored-by: Cursor <c>\n") == "body\n"
    assert strip_agent_trailers("Co-authored-by: Cursor <c>\n") == ""
    assert identity_emails("") == set()
    assert identity_emails("Alice <not-an-email>") == set()
    assert parse_coauthors("") == []
    assert parse_coauthors("Co-authored-by:   \n") == []
