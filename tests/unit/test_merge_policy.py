"""Tests for AGE-27 merge_policy decisions (mutation-gated module)."""

from __future__ import annotations

import pytest

from agentized.merge_policy import (
    agent_merge_decision,
    authorship_check,
    merge_policy_from_config,
    normalize_agent_merge,
)
from agentized.merge_policy_defaults import (
    AGENT_MERGE_ALLOWED,
    AGENT_MERGE_FORBIDDEN,
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
    default_merge_policy,
)


def test_normalize_and_config():
    assert normalize_agent_merge("forbidden") == AGENT_MERGE_FORBIDDEN
    assert normalize_agent_merge("FORBIDDEN") == AGENT_MERGE_FORBIDDEN
    assert normalize_agent_merge("allowed") == AGENT_MERGE_ALLOWED
    with pytest.raises(ValueError, match="allowed"):
        normalize_agent_merge("")
    with pytest.raises(ValueError, match=r"got 'maybe'") as exc_maybe:
        normalize_agent_merge("maybe")
    assert "forbidden" in str(exc_maybe.value)
    assert "None" not in str(exc_maybe.value)

    assert merge_policy_from_config(None)["agent_merge"] == AGENT_MERGE_ALLOWED
    assert merge_policy_from_config({})["agent_merge"] == AGENT_MERGE_ALLOWED
    assert merge_policy_from_config({"merge_policy": "x"})["agent_merge"] == AGENT_MERGE_ALLOWED
    assert merge_policy_from_config(None)["human_authorship"]["enabled"] is True

    partial = merge_policy_from_config({"merge_policy": {"human_participants": ["A"]}})
    assert partial["agent_merge"] == AGENT_MERGE_ALLOWED
    assert partial["human_participants"] == ["A"]

    with pytest.raises(ValueError):
        merge_policy_from_config({"merge_policy": {"agent_merge": "maybe"}})

    forbidden = merge_policy_from_config(
        {
            "merge_policy": {
                "agent_merge": "forbidden",
                "human_participants": ["Bob <b@x>", ""],
                "human_authorship": {
                    "enabled": True,
                    "strip_agent_trailers": True,
                    "agent_trailer_prefixes": ["X-Agent:", ""],
                },
            }
        }
    )
    assert forbidden["agent_merge"] == AGENT_MERGE_FORBIDDEN
    assert forbidden["human_participants"] == ["Bob <b@x>"]
    assert forbidden["human_authorship"]["enabled"] is True
    assert forbidden["human_authorship"]["strip_agent_trailers"] is True
    assert forbidden["human_authorship"]["agent_trailer_prefixes"] == ["X-Agent:"]
    no_strip = merge_policy_from_config(
        {"merge_policy": {"human_authorship": {"strip_agent_trailers": False}}}
    )
    assert no_strip["human_authorship"]["strip_agent_trailers"] is False
    assert set(no_strip["human_authorship"]) == {
        "enabled",
        "strip_agent_trailers",
        "agent_trailer_prefixes",
    }
    empty_pref = merge_policy_from_config(
        {"merge_policy": {"human_authorship": {"agent_trailer_prefixes": []}}}
    )
    assert (
        empty_pref["human_authorship"]["agent_trailer_prefixes"]
        == default_merge_policy()["human_authorship"]["agent_trailer_prefixes"]
    )
    assert merge_policy_from_config({})["agent_merge"] == AGENT_MERGE_ALLOWED


def test_authorship_check_modes():
    msg = "x\n\nCo-authored-by: Cursor <c@c>\n"
    disabled_policy = default_merge_policy()
    disabled_policy["human_authorship"]["enabled"] = False
    disabled = authorship_check(author="A", message=msg, policy=disabled_policy)
    assert disabled == {
        KEY_OK: True,
        KEY_MODE: MODE_DISABLED,
        KEY_CLEANED: msg,
        KEY_STRIPPED: 0,
        KEY_MESSAGE: "",
    }

    policy = default_merge_policy()
    empty = authorship_check(author="A", message=msg, policy=policy)
    assert empty[KEY_OK] is False
    assert empty[KEY_MODE] == MODE_REFUSE
    assert empty[KEY_CLEANED] == "x\n"
    assert empty[KEY_STRIPPED] == 1
    assert "human_participants is empty" in empty[KEY_MESSAGE]

    policy["human_participants"] = ["Alice <alice@example.com>"]
    bad = authorship_check(author="Eve <e@e>", message=msg, policy=policy)
    assert bad[KEY_MODE] == MODE_REFUSE
    assert bad[KEY_OK] is False
    assert "Eve <e@e>" in bad[KEY_MESSAGE]

    good = authorship_check(author="Alice <alice@example.com>", message=msg, policy=policy)
    assert good == {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_CLEANED: "x\n",
        KEY_STRIPPED: 1,
        KEY_MESSAGE: "merge-policy: authorship OK for 'Alice <alice@example.com>' (stripped 1 agent trailer line(s))",
    }

    co_msg = "feat\n\nCo-authored-by: Cursor <c@c>\nCo-authored-by: Alice <alice@example.com>\n"
    # Coauthor allowlist hit must not launder stranger / agent author.
    via_trailer = authorship_check(
        author="Cursor Agent <cursoragent@cursor.com>", message=co_msg, policy=policy
    )
    assert via_trailer[KEY_OK] is False
    assert via_trailer[KEY_MODE] == MODE_REFUSE
    assert "Cursor Agent" in via_trailer[KEY_MESSAGE]

    via_empty_author = authorship_check(author="", message=co_msg, policy=policy)
    assert via_empty_author[KEY_OK] is False
    empty_fail = authorship_check(author="", message="feat\n", policy=policy)
    assert empty_fail[KEY_OK] is False
    # Allowlisted author still OK when human coauthors also present.
    human_author = authorship_check(
        author="Alice <alice@example.com>", message=co_msg, policy=policy
    )
    assert human_author[KEY_OK] is True
    assert "Alice <alice@example.com>" in human_author[KEY_MESSAGE]

    policy["human_authorship"]["strip_agent_trailers"] = False
    nos = authorship_check(author="Alice <alice@example.com>", message=msg, policy=policy)
    assert nos[KEY_CLEANED] == msg
    assert nos[KEY_STRIPPED] == 0
    assert nos[KEY_MESSAGE] == "merge-policy: authorship OK for 'Alice <alice@example.com>'"

    policy2 = default_merge_policy()
    policy2["human_authorship"] = {"enabled": True}
    policy2["human_participants"] = ["Alice <alice@example.com>"]
    stripped_default = authorship_check(
        author="Alice <alice@example.com>", message=msg, policy=policy2
    )
    assert stripped_default[KEY_CLEANED] == "x\n"
    assert stripped_default[KEY_STRIPPED] == 1

    policy3 = default_merge_policy()
    policy3["human_authorship"]["enabled"] = True
    policy3["human_authorship"]["agent_trailer_prefixes"] = ["X-Agent:"]
    policy3["human_participants"] = ["Alice <alice@example.com>"]
    custom_msg = "body\n\nX-Agent: bot\nCo-authored-by: Cursor <c@c>\n"
    custom = authorship_check(
        author="Alice <alice@example.com>", message=custom_msg, policy=policy3
    )
    assert custom[KEY_CLEANED] == "body\n\nCo-authored-by: Cursor <c@c>\n"
    assert custom[KEY_STRIPPED] == 1


def test_agent_merge_decision_matrix():
    assert agent_merge_decision(agent_merge="allowed", is_agent=True, merge_shas=["a"]) == {
        KEY_OK: True,
        KEY_MODE: MODE_ALLOWED,
        KEY_MESSAGE: "",
        KEY_MERGES: [],
    }
    assert agent_merge_decision(agent_merge="FORBIDDEN", is_agent=False, merge_shas=["a"]) == {
        KEY_OK: True,
        KEY_MODE: MODE_HUMAN,
        KEY_MESSAGE: "",
        KEY_MERGES: [],
    }
    assert agent_merge_decision(agent_merge="forbidden", is_agent=True, merge_shas=[]) == {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_MESSAGE: "",
        KEY_MERGES: [],
    }
    shas = ["abcdef1234567890", "fedcba0987654321"]
    refused = agent_merge_decision(agent_merge="forbidden", is_agent=True, merge_shas=shas)
    assert refused[KEY_OK] is False
    assert refused[KEY_MODE] == MODE_REFUSE
    assert refused[KEY_MERGES] == shas
    assert refused[KEY_MERGES] is not shas
    assert (
        refused[KEY_MESSAGE]
        == "REFUSED. merge-policy: agent_merge=forbidden — agent sessions must not "
        "push merge commits (abcdef123456, fedcba098765). See docs/process-control.md."
    )
    bad = agent_merge_decision(agent_merge="", is_agent=True, merge_shas=["x"])
    assert bad[KEY_OK] is False
    assert bad[KEY_MODE] == MODE_REFUSE
    assert "allowed" in bad[KEY_MESSAGE]
