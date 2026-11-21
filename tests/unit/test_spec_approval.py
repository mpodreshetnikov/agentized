"""Tests for AGE-28 spec_approval decisions (mutation-gated module)."""

from __future__ import annotations

from agentized.process_control import default_process_config
from agentized.spec_approval import (
    evaluate_task_spec,
    spec_approval_from_config,
    task_needs_spec,
)
from agentized.spec_approval_defaults import (
    CFG_APPROVAL_HEADING,
    CFG_COMPLEX_TAG,
    CFG_ENABLED,
    CFG_SPEC_HEADING,
    DEFAULT_APPROVAL_HEADING,
    DEFAULT_COMPLEX_TAG,
    DEFAULT_SPEC_HEADING,
    KEY_APPROVERS,
    KEY_MESSAGE,
    KEY_MODE,
    KEY_OK,
    KEY_TASK_ID,
    MODE_OK,
    MODE_REFUSE,
    MODE_SKIP,
    approval_not_committed_message,
    approver_not_allowlisted_message,
    default_spec_approval,
    missing_approval_message,
    missing_spec_message,
    ok_message,
    self_approval_message,
)

REAL_SPEC = "Ship the gate for complex tasks."


def test_config_defaults_and_overrides():
    assert default_spec_approval() == {
        CFG_ENABLED: False,
        CFG_COMPLEX_TAG: DEFAULT_COMPLEX_TAG,
        CFG_SPEC_HEADING: DEFAULT_SPEC_HEADING,
        CFG_APPROVAL_HEADING: DEFAULT_APPROVAL_HEADING,
    }
    assert spec_approval_from_config(None) == default_spec_approval()
    assert spec_approval_from_config({}) == default_spec_approval()
    assert spec_approval_from_config({"spec_approval": "x"}) == default_spec_approval()

    custom = spec_approval_from_config(
        {
            "spec_approval": {
                "enabled": True,
                "complex_tag": " hard ",
                "spec_heading": " ## Design ",
                "approval_heading": "",
                "ignored": 1,
            }
        }
    )
    assert custom == {
        CFG_ENABLED: True,
        CFG_COMPLEX_TAG: "hard",
        CFG_SPEC_HEADING: "## Design",
        CFG_APPROVAL_HEADING: DEFAULT_APPROVAL_HEADING,
    }
    empty_tag = spec_approval_from_config({"spec_approval": {"complex_tag": "   "}})
    assert empty_tag[CFG_COMPLEX_TAG] == DEFAULT_COMPLEX_TAG
    assert "spec_approval" not in default_process_config()
    assert default_spec_approval()[CFG_ENABLED] is False


def test_task_needs_spec():
    cases = (
        ("complex", "complex"),
        ("COMPLEX,foo", "complex"),
        ("foo bar", "complex"),
        ("complexish", "complex"),
        ("complex", ""),
        ("complex", "   "),
        ("a,b", "b"),
    )
    outcomes = [task_needs_spec(tags, needle) for tags, needle in cases]
    assert outcomes == [True, True, False, False, False, False, True]


def test_evaluate_task_spec_matrix():
    policy = default_spec_approval()
    policy[CFG_ENABLED] = True
    allow = ["bob@x.test", "Bob <b@x>", "reviewer@ex.com"]

    skip = evaluate_task_spec(
        task_id="T-1",
        claim="alice",
        tags="simple",
        text="# T-1\n",
        policy=policy,
    )
    assert skip == {
        KEY_OK: True,
        KEY_MODE: MODE_SKIP,
        KEY_TASK_ID: "T-1",
        KEY_MESSAGE: "",
    }

    no_spec = evaluate_task_spec(
        task_id="T-2",
        claim="alice",
        tags="complex",
        text="# T-2\n\n## Goal\n\nx\n",
        policy=policy,
    )
    assert no_spec == {
        KEY_OK: False,
        KEY_MODE: MODE_REFUSE,
        KEY_TASK_ID: "T-2",
        KEY_MESSAGE: missing_spec_message("T-2", DEFAULT_SPEC_HEADING),
    }

    trivial_bodies = (
        "_(todo)_",
        "TODO",
        "…",
        "...",
        "tbd",
        "TODO: write the spec",
        "See _(TBD)_",
        "… fill in later",
        "x",
        ".",
        "<fill>",
        "Please <fill> this in",
        "fill-me later",
        "- [ ] fill-me",
        "!!!",
        "ok",
        "n/a",
        "WIP",
        "see chat",
        "plan: tbd",
        "Ship it.",
    )
    for body in trivial_bodies:
        placeholder = evaluate_task_spec(
            task_id="T-3",
            claim="alice",
            tags="complex",
            text=f"# T-3\n\n## Spec\n\n{body}\n",
            policy=policy,
        )
        assert placeholder[KEY_OK] is False
        assert placeholder[KEY_MODE] == MODE_REFUSE

    empty_spec = evaluate_task_spec(
        task_id="T-4",
        claim="alice",
        tags="complex",
        text=f"# T-4\n\n## Spec\n\n\n## Approval\n\napproved-by: bob@x.test\n",
        policy=policy,
        human_participants=allow,
        approval_committers={"bob@x.test"},
    )
    assert empty_spec[KEY_OK] is False
    assert empty_spec[KEY_MODE] == MODE_REFUSE

    no_approval = evaluate_task_spec(
        task_id="T-5",
        claim="alice",
        tags="complex",
        text=f"# T-5\n\n## Spec\n\n{REAL_SPEC}\n",
        policy=policy,
    )
    assert no_approval == {
        KEY_OK: False,
        KEY_MODE: MODE_REFUSE,
        KEY_TASK_ID: "T-5",
        KEY_MESSAGE: missing_approval_message("T-5", DEFAULT_APPROVAL_HEADING),
    }

    self_appr = evaluate_task_spec(
        task_id="T-6",
        claim="Alice",
        tags="complex",
        text=f"# T-6\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: alice\n",
        policy=policy,
        human_participants=allow,
        approval_committers={"bob@x.test"},
    )
    assert self_appr == {
        KEY_OK: False,
        KEY_MODE: MODE_REFUSE,
        KEY_TASK_ID: "T-6",
        KEY_MESSAGE: self_approval_message("T-6", "Alice"),
    }

    # Agent approved-by counts as self-approval (owner-or-agent)
    agent_as_approver = evaluate_task_spec(
        task_id="T-6agent",
        claim="worker-a",
        tags="complex",
        text=(
            f"# T-6agent\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\n"
            "approved-by: cursoragent@cursor.com\n"
        ),
        policy=policy,
        human_participants=["bob@x.test"],
        approval_committers={"bob@x.test"},
    )
    assert agent_as_approver == {
        KEY_OK: False,
        KEY_MODE: MODE_REFUSE,
        KEY_TASK_ID: "T-6agent",
        KEY_MESSAGE: self_approval_message("T-6agent", "worker-a"),
    }

    # Italic placeholder approved-by is skipped → self-approval if nothing else
    italic_approver = evaluate_task_spec(
        task_id="T-6ital",
        claim="alice",
        tags="complex",
        text=(f"# T-6ital\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: _(pending)_\n"),
        policy=policy,
        human_participants=allow,
        approval_committers={"bob@x.test"},
    )
    assert italic_approver[KEY_OK] is False
    assert italic_approver[KEY_MESSAGE] == self_approval_message("T-6ital", "alice")

    owner_on_allow = evaluate_task_spec(
        task_id="T-6b",
        claim="Alice <alice@corp.com>",
        tags="complex",
        text=(f"# T-6b\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: alice@corp.com\n"),
        policy=policy,
        human_participants=["alice@corp.com", "bob@x.test"],
        approval_committers={"alice@corp.com"},
    )
    assert owner_on_allow == {
        KEY_OK: False,
        KEY_MODE: MODE_REFUSE,
        KEY_TASK_ID: "T-6b",
        KEY_MESSAGE: self_approval_message("T-6b", "Alice <alice@corp.com>"),
    }

    # Typed allowlisted approver without committers → refuse
    typed_only = evaluate_task_spec(
        task_id="T-7typed",
        claim="alice",
        tags="complex",
        text=(f"# T-7typed\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: bob@x.test\n"),
        policy=policy,
        human_participants=allow,
        approval_committers=None,
    )
    assert typed_only == {
        KEY_OK: False,
        KEY_MODE: MODE_REFUSE,
        KEY_TASK_ID: "T-7typed",
        KEY_MESSAGE: approval_not_committed_message("T-7typed"),
    }

    # Allowlisted but committed by someone else → refuse
    wrong_committer = evaluate_task_spec(
        task_id="T-7wrong",
        claim="alice",
        tags="complex",
        text=(f"# T-7wrong\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: bob@x.test\n"),
        policy=policy,
        human_participants=allow,
        approval_committers={"eve@x.test"},
    )
    assert wrong_committer == {
        KEY_OK: False,
        KEY_MODE: MODE_REFUSE,
        KEY_TASK_ID: "T-7wrong",
        KEY_MESSAGE: approval_not_committed_message("T-7wrong"),
    }

    # Agent committer never counts
    agent_committer = evaluate_task_spec(
        task_id="T-7agentc",
        claim="alice",
        tags="complex",
        text=(f"# T-7agentc\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: bob@x.test\n"),
        policy=policy,
        human_participants=allow,
        approval_committers={"cursoragent@cursor.com", "bob@x.test"},
    )
    # bob is also present → should pass; isolate agent-only:
    agent_only_committer = evaluate_task_spec(
        task_id="T-7agentonly",
        claim="alice",
        tags="complex",
        text=(
            f"# T-7agentonly\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: bob@x.test\n"
        ),
        policy=policy,
        human_participants=allow,
        approval_committers={"cursoragent@cursor.com"},
    )
    assert agent_only_committer[KEY_MESSAGE] == approval_not_committed_message("T-7agentonly")
    assert agent_committer[KEY_OK] is True

    no_allow = evaluate_task_spec(
        task_id="T-7",
        claim="alice",
        tags="complex",
        text=f"# T-7\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: XXXX\n",
        policy=policy,
        human_participants=[],
        approval_committers={"xxxx@x.test"},
    )
    assert no_allow[KEY_OK] is False

    ok = evaluate_task_spec(
        task_id="T-8",
        claim="alice",
        tags="complex,foo",
        text=(
            f"# T-8\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\n"
            "approved-by: alice\napproved-by: Bob <b@x>\n"
        ),
        policy=policy,
        human_participants=allow,
        approval_committers={"b@x"},
    )
    assert ok == {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_TASK_ID: "T-8",
        KEY_MESSAGE: "spec-approval: T-8 OK (approved-by Bob <b@x>)",
        KEY_APPROVERS: ["Bob <b@x>"],
    }

    none_claim = evaluate_task_spec(
        task_id="T-11",
        claim=None,  # type: ignore[arg-type]
        tags="complex",
        text=(f"# T-11\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: bob@x.test\n"),
        policy=policy,
        human_participants=["bob@x.test", "", "  "],
        approval_committers={"bob@x.test"},
    )
    assert none_claim == {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_TASK_ID: "T-11",
        KEY_MESSAGE: ok_message("T-11", "bob@x.test"),
        KEY_APPROVERS: ["bob@x.test"],
    }

    not_listed = evaluate_task_spec(
        task_id="T-12",
        claim="alice",
        tags="complex",
        text=(f"# T-12\n\n## Spec\n\n{REAL_SPEC}\n\n## Approval\n\napproved-by: eve@x.test\n"),
        policy=policy,
        human_participants=["bob@x.test"],
        approval_committers={"eve@x.test"},
    )
    assert not_listed[KEY_OK] is False
    assert not_listed[KEY_MESSAGE] == approver_not_allowlisted_message("T-12")

    custom_policy = spec_approval_from_config(
        {
            "spec_approval": {
                "enabled": True,
                "complex_tag": "hard",
                "spec_heading": "## Design",
                "approval_heading": "## Signoff",
            }
        }
    )
    custom_ok = evaluate_task_spec(
        task_id="T-9",
        claim="a",
        tags="hard",
        text=(
            "# T-9\n\n## Design\n\nDesign the approval gate fully.\n\n"
            "## Signoff\n\nApproved-By: reviewer@ex.com\n"
        ),
        policy=custom_policy,
        human_participants=["reviewer@ex.com"],
        approval_committers={"reviewer@ex.com"},
    )
    assert custom_ok[KEY_MODE] == MODE_OK
    assert custom_ok[KEY_APPROVERS] == ["reviewer@ex.com"]
