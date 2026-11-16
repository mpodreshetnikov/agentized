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
    default_spec_approval,
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
    # empty complex_tag must not replace default
    empty_tag = spec_approval_from_config(
        {"spec_approval": {"complex_tag": "   "}}
    )
    assert empty_tag[CFG_COMPLEX_TAG] == DEFAULT_COMPLEX_TAG
    assert "spec_approval" in default_process_config()
    assert default_process_config()["spec_approval"][CFG_ENABLED] is False


def test_task_needs_spec():
    assert task_needs_spec("complex", "complex") is True
    assert task_needs_spec("COMPLEX,foo", "complex") is True
    assert task_needs_spec("foo bar", "complex") is False
    assert task_needs_spec("complexish", "complex") is False
    assert task_needs_spec("complex", "") is False
    assert task_needs_spec("complex", "   ") is False
    assert task_needs_spec("a,b", "b") is True


def test_evaluate_task_spec_matrix():
    policy = default_spec_approval()
    policy[CFG_ENABLED] = True

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
    assert no_spec[KEY_OK] is False
    assert no_spec[KEY_MODE] == MODE_REFUSE
    assert no_spec[KEY_TASK_ID] == "T-2"
    assert "missing non-empty ## Spec" in no_spec[KEY_MESSAGE]
    assert set(no_spec) == {KEY_OK, KEY_MODE, KEY_TASK_ID, KEY_MESSAGE}

    placeholder = evaluate_task_spec(
        task_id="T-3",
        claim="alice",
        tags="complex",
        text="# T-3\n\n## Spec\n\n_(todo)_\n",
        policy=policy,
    )
    assert placeholder[KEY_MODE] == MODE_REFUSE
    assert "missing non-empty ## Spec" in placeholder[KEY_MESSAGE]

    empty_spec = evaluate_task_spec(
        task_id="T-4",
        claim="alice",
        tags="complex",
        text="# T-4\n\n## Spec\n\n\n## Approval\n\napproved-by: bob\n",
        policy=policy,
    )
    assert empty_spec[KEY_MODE] == MODE_REFUSE

    no_approval = evaluate_task_spec(
        task_id="T-5",
        claim="alice",
        tags="complex",
        text="# T-5\n\n## Spec\n\nDo X.\n",
        policy=policy,
    )
    assert no_approval[KEY_MODE] == MODE_REFUSE
    assert "needs ## Approval" in no_approval[KEY_MESSAGE]

    self_appr = evaluate_task_spec(
        task_id="T-6",
        claim="Alice",
        tags="complex",
        text="# T-6\n\n## Spec\n\nDo X.\n\n## Approval\n\napproved-by: alice\n",
        policy=policy,
    )
    assert self_appr[KEY_MODE] == MODE_REFUSE
    assert "someone other than claim owner 'Alice'" in self_appr[KEY_MESSAGE]

    empty_approved = evaluate_task_spec(
        task_id="T-7",
        claim="alice",
        tags="complex",
        text="# T-7\n\n## Spec\n\nDo X.\n\n## Approval\n\napproved-by:   \n",
        policy=policy,
    )
    assert empty_approved[KEY_MODE] == MODE_REFUSE

    ok = evaluate_task_spec(
        task_id="T-8",
        claim="alice",
        tags="complex,foo",
        text=(
            "# T-8\n\n## Spec\n\nShip it.\n\n## Approval\n\n"
            "approved-by: alice\napproved-by: Bob <b@x>\n"
        ),
        policy=policy,
    )
    assert ok == {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_TASK_ID: "T-8",
        KEY_MESSAGE: "spec-approval: T-8 OK (approved-by Bob <b@x>)",
        KEY_APPROVERS: ["Bob <b@x>"],
    }

    # custom headings
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
        text="# T-9\n\n## Design\n\nPlan.\n\n## Signoff\n\nApproved-By: reviewer\n",
        policy=custom_policy,
    )
    assert custom_ok[KEY_MODE] == MODE_OK
    assert custom_ok[KEY_APPROVERS] == ["reviewer"]
