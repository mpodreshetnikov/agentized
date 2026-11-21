"""Vocab surface + facade smoke for tasks.py (AGE-45). Schema oracles in test_task_schema_oracles."""

from agentized import tasks
from agentized.task_schema import ACTIVE_STATUSES, render_task_file, set_field
from agentized.tasks import ALL_STATUSES, CANONICAL_STATUSES, FIELD_RE, STATUS_ALIASES


def test_status_vocab_and_field_re():
    assert ALL_STATUSES == CANONICAL_STATUSES + ("dropped", "queued")
    assert STATUS_ALIASES == {"dropped": "canceled", "queued": "queue"}
    assert set(STATUS_ALIASES).issubset(ALL_STATUSES)
    assert FIELD_RE.match("acceptance_note: shipped").group(2) == "shipped"
    assert FIELD_RE.match("blocked_reason: dep").group(1) == "blocked_reason"
    assert FIELD_RE.match("blocked_deadline: 2026-12-01").group(2) == "2026-12-01"
    body = "pr:\nreview_note: tip\n"
    assert dict(FIELD_RE.findall(body)) == {"pr": "", "review_note": "tip"}


def test_tasks_reexports_match_schema():
    assert tasks.ACTIVE_STATUSES == ACTIVE_STATUSES
    assert tasks.render_task_file is render_task_file
    assert tasks.set_field is set_field
    assert tasks.render_task_file("T-1", "Hi") == render_task_file("T-1", "Hi")
    # AGE-43 invariant still reachable via facade
    text = "# T-1 — x\n\nродитель:\nclaim: alice\n"
    assert set_field(text, "родитель", "P") == "# T-1 — x\n\nродитель: P\nclaim: alice\n"
    assert tasks.set_field(text, "родитель", "P") == set_field(text, "родитель", "P")
