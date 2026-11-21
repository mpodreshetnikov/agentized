"""Tests for spec_approval_defaults (mutation-covered)."""
from __future__ import annotations

from agentized.spec_approval_defaults import (
    CFG_APPROVAL_HEADING,
    CFG_COMPLEX_TAG,
    CFG_ENABLED,
    CFG_SPEC_APPROVAL,
    CFG_SPEC_HEADING,
    DEFAULT_APPROVAL_HEADING,
    DEFAULT_COMPLEX_TAG,
    DEFAULT_SPEC_HEADING,
    DOC,
    EMPTY,
    KEY_APPROVERS,
    KEY_CHECKED,
    KEY_FAILURES,
    KEY_MESSAGE,
    KEY_MODE,
    KEY_OK,
    KEY_TASK_ID,
    MODE_DISABLED,
    MODE_OK,
    MODE_REFUSE,
    MODE_SKIP,
    PLACEHOLDER_PREFIX,
    SPEC_GATE_STATUSES,
    STATUS_IN_PROGRESS,
    approver_not_allowlisted_message,
    checked_message,
    default_spec_approval,
    missing_approval_message,
    missing_spec_message,
    ok_message,
    self_approval_message,
)


def test_constants_and_default():
    assert (MODE_DISABLED, MODE_SKIP, MODE_REFUSE, MODE_OK) == (
        "disabled",
        "skip",
        "refuse",
        "ok",
    )
    assert (
        KEY_OK,
        KEY_MODE,
        KEY_MESSAGE,
        KEY_TASK_ID,
        KEY_APPROVERS,
        KEY_FAILURES,
        KEY_CHECKED,
    ) == ("ok", "mode", "message", "task_id", "approvers", "failures", "checked")
    assert (
        CFG_SPEC_APPROVAL,
        CFG_ENABLED,
        CFG_COMPLEX_TAG,
        CFG_SPEC_HEADING,
        CFG_APPROVAL_HEADING,
    ) == ("spec_approval", "enabled", "complex_tag", "spec_heading", "approval_heading")
    assert (
        DOC,
        DEFAULT_COMPLEX_TAG,
        DEFAULT_SPEC_HEADING,
        DEFAULT_APPROVAL_HEADING,
        PLACEHOLDER_PREFIX,
        EMPTY,
        STATUS_IN_PROGRESS,
    ) == (
        "docs/process-control.md",
        "complex",
        "## Spec",
        "## Approval",
        "_(",
        "",
        "in-progress",
    )
    assert STATUS_IN_PROGRESS in SPEC_GATE_STATUSES
    assert SPEC_GATE_STATUSES == frozenset(
        {"in-progress", "self-review", "for-review", "blocked"}
    )
    assert "done" not in SPEC_GATE_STATUSES
    assert "dropped" not in SPEC_GATE_STATUSES
    assert "canceled" not in SPEC_GATE_STATUSES
    assert "open" not in SPEC_GATE_STATUSES
    assert default_spec_approval() == {
        "enabled": False,
        "complex_tag": "complex",
        "spec_heading": "## Spec",
        "approval_heading": "## Approval",
    }


def test_message_builders():
    assert missing_spec_message("T-1", "## Spec") == (
        "REFUSED. spec-approval: T-1 is complex but missing non-empty "
        "## Spec section. See docs/process-control.md."
    )
    assert missing_approval_message("T-2", "## Approval") == (
        "REFUSED. spec-approval: T-2 needs ## Approval with "
        "approved-by: <other participant>. See docs/process-control.md."
    )
    assert self_approval_message("T-3", "Alice") == (
        "REFUSED. spec-approval: T-3 requires approved-by someone other "
        "than claim owner 'Alice'. See docs/process-control.md."
    )
    assert ok_message("T-4", "bob") == "spec-approval: T-4 OK (approved-by bob)"
    assert checked_message(3) == "spec-approval: checked 3 complex gated task(s)"
    assert "human_participants" in approver_not_allowlisted_message("T-5")
