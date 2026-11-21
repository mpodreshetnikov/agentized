"""Mutation oracles for status_gates.py (mutmut test_status_gates_*.py)."""

from __future__ import annotations

from agentized.status_gates import (
    ALL_STATUSES,
    CANONICAL_STATUSES,
    INDEX_ACTIVE_STATUSES,
    MSG_UNKNOWN_STATUS,
    STATUS_ALIASES,
    is_known_status,
    normalize_status,
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
