"""Mutation oracles for status_gates.py (mutmut test_status_gates_*.py)."""

from __future__ import annotations

from agentized.status_gates import (
    ALL_STATUSES,
    CANONICAL_STATUSES,
    DECISION_SECTION,
    INDEX_ACTIVE_STATUSES,
    MSG_DECISION_PREFIX,
    MSG_PROGRESS_PREFIX,
    MSG_TASK_DELETED,
    MSG_UNKNOWN_STATUS,
    PROGRESS_SECTION,
    STATUS_ALIASES,
    is_known_status,
    normalize_status,
    section_body,
    section_is_prefix,
)


def test_status_gates_vocab_exact():
    assert CANONICAL_STATUSES == (
        "idea",
        "open",
        "queue",
        "in-progress",
        "self-review",
        "for-review",
        "blocked",
        "done",
        "canceled",
    )
    assert STATUS_ALIASES == {"dropped": "canceled", "queued": "queue"}
    assert ALL_STATUSES == CANONICAL_STATUSES + ("dropped", "queued")
    assert INDEX_ACTIVE_STATUSES == (
        "open",
        "queue",
        "in-progress",
        "self-review",
        "for-review",
        "blocked",
    )
    assert MSG_UNKNOWN_STATUS == "unknown status {st!r}"
    assert MSG_UNKNOWN_STATUS.format(st="wip") == "unknown status 'wip'"
    assert normalize_status("dropped") == "canceled"
    assert normalize_status("queued") == "queue"
    assert normalize_status("Open") == "open"
    assert normalize_status("  SELF-REVIEW ") == "self-review"
    assert normalize_status("") == ""
    assert normalize_status(None) == ""
    assert normalize_status("   ") == ""
    assert is_known_status("idea") is True
    assert is_known_status("dropped") is True
    assert is_known_status("queued") is True
    assert is_known_status("wip") is False
    assert is_known_status("") is False
    assert is_known_status(None) is False
    assert is_known_status("done") is True
    assert is_known_status("canceled") is True
    assert PROGRESS_SECTION == "## Progress"
    assert DECISION_SECTION == "## Decision Log"
    assert MSG_PROGRESS_PREFIX == (
        "Progress is not an exact prefix of base (append-only; corrections = append only)"
    )
    assert MSG_DECISION_PREFIX == (
        "Decision Log is not an exact prefix of base (append-only; corrections = append only)"
    )
    assert MSG_TASK_DELETED == "task deleted; set статус: canceled"
    sample = "## Progress\n\na\n\n## Decision Log\n\nb\n"
    assert section_body(sample, PROGRESS_SECTION) == "\n\na\n"
    assert section_body(sample, DECISION_SECTION) == "\n\nb\n"
    assert section_body("x", PROGRESS_SECTION) is None
    assert section_is_prefix("x", sample, PROGRESS_SECTION) is True
    assert (
        section_is_prefix(
            sample,
            "## Progress\n\na\n\n- more\n\n## Decision Log\n\nb\n",
            PROGRESS_SECTION,
        )
        is True
    )
    assert (
        section_is_prefix(sample, "## Progress\n\nZ\n\n## Decision Log\n\nb\n", PROGRESS_SECTION)
        is False
    )
    assert (
        section_is_prefix(sample, "## Progress\n\na\n\n## Decision Log\n\nZ\n", DECISION_SECTION)
        is False
    )
