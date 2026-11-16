"""Lock status_gates vocabulary API to #25 tip f44e46e (AGE-22)."""
from __future__ import annotations

from agentized.status_gates import (
    ALL_STATUSES,
    CANONICAL_STATUSES,
    COLUMN_FOR_STATUS,
    INDEX_ACTIVE_STATUSES,
    STATUS_ALIASES,
    TEXT_ENCODING,
    is_known_status,
    normalize_status,
)


def test_vocab_matches_f44e46e_contract():
    assert TEXT_ENCODING == "utf-8"
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
    assert COLUMN_FOR_STATUS == {
        "idea": "open",
        "open": "open",
        "queue": "queue",
        "self-review": "queue",
        "in-progress": "in-progress",
        "for-review": "for-review",
        "blocked": "blocked",
        "done": "done",
        "canceled": "canceled",
    }
    assert normalize_status("Dropped") == "canceled"
    assert normalize_status("queued") == "queue"
    assert normalize_status("") == ""
    assert normalize_status(None) == ""
    assert is_known_status("queue") is True
    assert is_known_status("self-review") is True
    assert is_known_status("nope") is False
    assert is_known_status("") is False
