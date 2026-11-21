"""Defaults + constant lexemes for spec-approval ."""
from __future__ import annotations

from typing import Any

DOC = "docs/process-control.md"

MODE_DISABLED = "disabled"
MODE_SKIP = "skip"
MODE_REFUSE = "refuse"
MODE_OK = "ok"

KEY_OK = "ok"
KEY_MODE = "mode"
KEY_MESSAGE = "message"
KEY_TASK_ID = "task_id"
KEY_APPROVERS = "approvers"
KEY_FAILURES = "failures"
KEY_CHECKED = "checked"

CFG_SPEC_APPROVAL = "spec_approval"
CFG_ENABLED = "enabled"
CFG_COMPLEX_TAG = "complex_tag"
CFG_SPEC_HEADING = "spec_heading"
CFG_APPROVAL_HEADING = "approval_heading"

DEFAULT_COMPLEX_TAG = "complex"
DEFAULT_SPEC_HEADING = "## Spec"
DEFAULT_APPROVAL_HEADING = "## Approval"
PLACEHOLDER_PREFIX = "_("
EMPTY = ""
STATUS_IN_PROGRESS = "in-progress"

# Statuses from in-progress onward (board-forward compatible).
SPEC_GATE_STATUSES: frozenset[str] = frozenset(
    {
        "in-progress",
        "self-review",
        "for-review",
        "blocked",
    }
)


def default_spec_approval() -> dict[str, Any]:
    return {
        CFG_ENABLED: False,
        CFG_COMPLEX_TAG: DEFAULT_COMPLEX_TAG,
        CFG_SPEC_HEADING: DEFAULT_SPEC_HEADING,
        CFG_APPROVAL_HEADING: DEFAULT_APPROVAL_HEADING,
    }


def missing_spec_message(task_id: str, spec_heading: str) -> str:
    return (
        f"REFUSED. spec-approval: {task_id} is complex but missing non-empty "
        f"{spec_heading} section. See {DOC}."
    )


def missing_approval_message(task_id: str, approval_heading: str) -> str:
    return (
        f"REFUSED. spec-approval: {task_id} needs {approval_heading} with "
        f"approved-by: <other participant>. See {DOC}."
    )


def self_approval_message(task_id: str, claim: str) -> str:
    return (
        f"REFUSED. spec-approval: {task_id} requires approved-by someone other "
        f"than claim owner {claim!r}. See {DOC}."
    )


def approver_not_allowlisted_message(task_id: str) -> str:
    return (
        f"REFUSED. spec-approval: {task_id} approver must be on "
        f"human_participants allowlist or the approval must be committed by a "
        f"non-owner. See {DOC}."
    )


def ok_message(task_id: str, approver: str) -> str:
    return f"spec-approval: {task_id} OK (approved-by {approver})"


def checked_message(checked: int) -> str:
    return f"spec-approval: checked {checked} complex gated task(s)"
