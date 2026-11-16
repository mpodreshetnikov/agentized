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
    approver_not_allowlisted_message,
    default_spec_approval,
    missing_approval_message,
    missing_spec_message,
    ok_message,
    self_approval_message,
)


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
    empty_tag = spec_approval_from_config(
        {"spec_approval": {"complex_tag": "   "}}
    )
    assert empty_tag[CFG_COMPLEX_TAG] == DEFAULT_COMPLEX_TAG
    assert "spec_approval" in default_process_config()
    assert default_process_config()["spec_approval"][CFG_ENABLED] is False


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

    for body in ("_(todo)_", "TODO", "…", "...", "tbd"):
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
        text="# T-4\n\n## Spec\n\n\n## Approval\n\napproved-by: bob@x.test\n",
        policy=policy,
        human_participants=allow,
    )
    assert empty_spec[KEY_OK] is False
    assert empty_spec[KEY_MODE] == MODE_REFUSE

    no_approval = evaluate_task_spec(
        task_id="T-5",
        claim="alice",
        tags="complex",
        text="# T-5\n\n## Spec\n\nDo X.\n",
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
        text="# T-6\n\n## Spec\n\nDo X.\n\n## Approval\n\napproved-by: alice\n",
        policy=policy,
        human_participants=allow,
    )
    assert self_appr == {
        KEY_OK: False,
        KEY_MODE: MODE_REFUSE,
        KEY_TASK_ID: "T-6",
        KEY_MESSAGE: self_approval_message("T-6", "Alice"),
    }

    # Other approver without allowlist match and no non-owner → refuse
    no_allow = evaluate_task_spec(
        task_id="T-7",
        claim="alice",
        tags="complex",
        text="# T-7\n\n## Spec\n\nDo X.\n\n## Approval\n\napproved-by: XXXX\n",
        policy=policy,
        human_participants=[],
    )
    assert no_allow[KEY_OK] is False

    # Allowlist path
    ok = evaluate_task_spec(
        task_id="T-8",
        claim="alice",
        tags="complex,foo",
        text=(
            "# T-8\n\n## Spec\n\nShip it.\n\n## Approval\n\n"
            "approved-by: alice\napproved-by: Bob <b@x>\n"
        ),
        policy=policy,
        human_participants=allow,
    )
    assert ok == {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_TASK_ID: "T-8",
        KEY_MESSAGE: "spec-approval: T-8 OK (approved-by Bob <b@x>)",
        KEY_APPROVERS: ["Bob <b@x>"],
    }

    # Non-owner commit path even with self-approval text
    via_git = evaluate_task_spec(
        task_id="T-10",
        claim="alice",
        tags="complex",
        text="# T-10\n\n## Spec\n\nReal plan.\n\n## Approval\n\napproved-by: alice\n",
        policy=policy,
        human_participants=[],
        approval_by_non_owner=True,
    )
    assert via_git == {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_TASK_ID: "T-10",
        KEY_MESSAGE: ok_message("T-10", "non-owner-commit"),
        KEY_APPROVERS: ["non-owner-commit"],
    }

    # claim=None: treat claim as empty; other approvers still work via allowlist
    none_claim = evaluate_task_spec(
        task_id="T-11",
        claim=None,  # type: ignore[arg-type]
        tags="complex",
        text="# T-11\n\n## Spec\n\nPlan.\n\n## Approval\n\napproved-by: bob@x.test\n",
        policy=policy,
        human_participants=["bob@x.test", "", "  "],
    )
    assert none_claim == {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_TASK_ID: "T-11",
        KEY_MESSAGE: ok_message("T-11", "bob@x.test"),
        KEY_APPROVERS: ["bob@x.test"],
    }

    # not-allowlisted message must include task_id
    not_listed = evaluate_task_spec(
        task_id="T-12",
        claim="alice",
        tags="complex",
        text="# T-12\n\n## Spec\n\nPlan.\n\n## Approval\n\napproved-by: eve@x.test\n",
        policy=policy,
        human_participants=["bob@x.test"],
    )
    assert not_listed[KEY_OK] is False
    assert not_listed[KEY_MESSAGE] == approver_not_allowlisted_message("T-12")
    assert "T-12" in not_listed[KEY_MESSAGE]

    # non-owner with a distinct approver label uses that approver
    via_other = evaluate_task_spec(
        task_id="T-13",
        claim="alice",
        tags="complex",
        text="# T-13\n\n## Spec\n\nPlan.\n\n## Approval\n\napproved-by: carol@x.test\n",
        policy=policy,
        human_participants=[],
        approval_by_non_owner=True,
    )
    assert via_other == {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_TASK_ID: "T-13",
        KEY_MESSAGE: ok_message("T-13", "carol@x.test"),
        KEY_APPROVERS: ["carol@x.test"],
    }

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
        text="# T-9\n\n## Design\n\nPlan.\n\n## Signoff\n\nApproved-By: reviewer@ex.com\n",
        policy=custom_policy,
        human_participants=["reviewer@ex.com"],
    )
    assert custom_ok[KEY_MODE] == MODE_OK
    assert custom_ok[KEY_APPROVERS] == ["reviewer@ex.com"]
