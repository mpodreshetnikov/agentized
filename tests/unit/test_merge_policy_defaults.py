"""Tests for merge_policy_defaults (mutation-covered)."""

from __future__ import annotations

from agentized.merge_policy_defaults import (
    AGENT_MERGE_ALLOWED,
    AGENT_MERGE_FORBIDDEN,
    CFG_AGENT_MERGE,
    CFG_AGENT_TRAILER_PREFIXES,
    CFG_ENABLED,
    CFG_HUMAN_AUTHORSHIP,
    CFG_HUMAN_PARTICIPANTS,
    CFG_MERGE_POLICY,
    CFG_STRIP_AGENT_TRAILERS,
    DEFAULT_AGENT_TRAILER_PREFIXES,
    DOC,
    KEY_CLEANED,
    KEY_MERGES,
    KEY_MESSAGE,
    KEY_MODE,
    KEY_OK,
    KEY_STRIPPED,
    MODE_ALLOWED,
    MODE_DISABLED,
    MODE_HUMAN,
    MODE_OK,
    MODE_REFUSE,
    agent_merge_refuse_message,
    author_not_allowlisted_message,
    authorship_ok_message,
    default_merge_policy,
    empty_allowlist_message,
    invalid_agent_merge_message,
)


def test_constants_and_default_policy():
    assert (
        AGENT_MERGE_ALLOWED,
        AGENT_MERGE_FORBIDDEN,
        MODE_DISABLED,
        MODE_REFUSE,
        MODE_OK,
        MODE_HUMAN,
        MODE_ALLOWED,
    ) == ("allowed", "forbidden", "disabled", "refuse", "ok", "human", "allowed")
    assert (KEY_OK, KEY_MODE, KEY_MESSAGE, KEY_MERGES, KEY_CLEANED, KEY_STRIPPED) == (
        "ok",
        "mode",
        "message",
        "merges",
        "cleaned_message",
        "stripped",
    )
    assert (
        CFG_MERGE_POLICY,
        CFG_AGENT_MERGE,
        CFG_HUMAN_PARTICIPANTS,
        CFG_HUMAN_AUTHORSHIP,
        CFG_ENABLED,
        CFG_STRIP_AGENT_TRAILERS,
        CFG_AGENT_TRAILER_PREFIXES,
    ) == (
        "merge_policy",
        "agent_merge",
        "human_participants",
        "human_authorship",
        "enabled",
        "strip_agent_trailers",
        "agent_trailer_prefixes",
    )
    assert DOC == "docs/process-control.md"
    assert DEFAULT_AGENT_TRAILER_PREFIXES == (
        "Co-authored-by: Cursor",
        "Co-authored-by: cursor",
        "Co-authored-by: Claude",
        "Co-authored-by: claude",
        "Co-authored-by: Codex",
        "Co-authored-by: codex",
        "Co-authored-by: Copilot",
        "Co-authored-by: GitHub Copilot",
        "Generated-by:",
        "Generated-By:",
        "Signed-off-by: Cursor",
        "Signed-off-by: Claude",
    )
    policy = default_merge_policy()
    assert policy == {
        "agent_merge": "allowed",
        "human_participants": [],
        "human_authorship": {
            "enabled": True,
            "strip_agent_trailers": True,
            "agent_trailer_prefixes": list(DEFAULT_AGENT_TRAILER_PREFIXES),
        },
    }
    assert (
        default_merge_policy()["human_authorship"]["agent_trailer_prefixes"]
        is not policy["human_authorship"]["agent_trailer_prefixes"]
    )


def test_message_builders():
    assert empty_allowlist_message() == (
        "REFUSED. merge-policy: human_authorship.enabled but "
        "human_participants is empty. See docs/process-control.md."
    )
    assert author_not_allowlisted_message("Eve <e@e>") == (
        "REFUSED. merge-policy: author 'Eve <e@e>' is not on "
        "human_participants allowlist. See docs/process-control.md."
    )
    assert authorship_ok_message("Alice", 0) == "merge-policy: authorship OK for 'Alice'"
    assert authorship_ok_message("Alice", 2) == (
        "merge-policy: authorship OK for 'Alice' (stripped 2 agent trailer line(s))"
    )
    assert agent_merge_refuse_message("abc, def") == (
        "REFUSED. merge-policy: agent_merge=forbidden — agent sessions must not "
        "push merge commits (abc, def). See docs/process-control.md."
    )
    assert invalid_agent_merge_message("maybe") == (
        "REFUSED. merge-policy: agent_merge must be "
        "'allowed' or 'forbidden', got 'maybe'. See docs/process-control.md."
    )
