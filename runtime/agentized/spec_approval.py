"""Spec-approval decisions (AGE-28)"""

from __future__ import annotations

from typing import Any

from .spec_approval_defaults import (
    CFG_APPROVAL_HEADING,
    CFG_COMPLEX_TAG,
    CFG_ENABLED,
    CFG_SPEC_APPROVAL,
    CFG_SPEC_HEADING,
    EMPTY,
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
from .spec_approval_text import (
    human_committer_emails,
    identity_emails,
    is_owner_or_agent_identity,
    is_placeholder_spec,
    parse_approvers,
    parse_tags,
    participant_email_matches,
    section_body,
)


def spec_approval_from_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = default_spec_approval()
    raw = (cfg or {}).get(CFG_SPEC_APPROVAL)
    if not isinstance(raw, dict):
        return base
    out = dict(base)
    if CFG_ENABLED in raw:
        out[CFG_ENABLED] = bool(raw[CFG_ENABLED])
    for key in (CFG_COMPLEX_TAG, CFG_SPEC_HEADING, CFG_APPROVAL_HEADING):
        if key in raw and str(raw[key]).strip():
            out[key] = str(raw[key]).strip()
    return out


def task_needs_spec(tags: str, complex_tag: str) -> bool:
    needle = complex_tag.strip().lower()
    if len(needle) == 0:
        return False
    return needle in parse_tags(tags)


def evaluate_task_spec(
    *,
    task_id: str,
    claim: str,
    tags: str,
    text: str,
    policy: dict[str, Any],
    human_participants: list[str] | None = None,
    approval_committers: set[str] | None = None,
) -> dict[str, Any]:
    """Pure check for one task file body. `policy` must be normalized via from_config.

    Pass only when >=1 non-owner (non-agent) approver matches ``human_participants``
    by full email **and** that approver also appears in ``approval_committers``
    (full email). Typed ``approved-by`` alone never passes (``approval_committers``
    None → refuse). Agent/bot identities never count as approvers or committers.
    """
    complex_tag = str(policy[CFG_COMPLEX_TAG])
    if not task_needs_spec(tags, complex_tag):
        return {KEY_OK: True, KEY_MODE: MODE_SKIP, KEY_TASK_ID: task_id, KEY_MESSAGE: EMPTY}
    spec_h = str(policy[CFG_SPEC_HEADING])
    appr_h = str(policy[CFG_APPROVAL_HEADING])
    spec = section_body(text, spec_h)
    if spec is None or is_placeholder_spec(spec):
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_TASK_ID: task_id,
            KEY_MESSAGE: missing_spec_message(task_id, spec_h),
        }
    approval = section_body(text, appr_h)
    if approval is None:
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_TASK_ID: task_id,
            KEY_MESSAGE: missing_approval_message(task_id, appr_h),
        }
    approvers = parse_approvers(approval)
    other = [a for a in approvers if not is_owner_or_agent_identity(a, claim or EMPTY)]
    allow: list[str] = []
    for p in human_participants or []:
        s = str(p).strip()
        if s:
            allow.append(s)

    if len(other) == 0:
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_TASK_ID: task_id,
            KEY_MESSAGE: self_approval_message(task_id, claim),
        }

    matched: list[str] = []
    for a in other:
        if participant_email_matches(a, allow):
            matched.append(a)
    if not matched:
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_TASK_ID: task_id,
            KEY_MESSAGE: approver_not_allowlisted_message(task_id),
        }

    committer_emails = human_committer_emails(approval_committers)
    confirmed: list[str] = []
    for a in matched:
        if identity_emails(a) & committer_emails:
            confirmed.append(a)
    if not confirmed:
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_TASK_ID: task_id,
            KEY_MESSAGE: approval_not_committed_message(task_id),
        }

    return {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_TASK_ID: task_id,
        KEY_MESSAGE: ok_message(task_id, confirmed[0]),
        KEY_APPROVERS: confirmed,
    }
