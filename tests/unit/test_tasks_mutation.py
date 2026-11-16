"""Mutation-oriented coverage for runtime/agentized/tasks.py (AGE-22)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agentized.tasks import (
    ACTIVE_STATUSES,
    allocate_task_id,
    append_progress,
    list_tasks,
    parse_task,
    rebuild_task_index,
    render_task_file,
    set_field,
    utc_now_stamp,
)


def test_parse_missing_status_is_empty(tmp_path: Path):
    path = tmp_path / "T-261116-ms.md"
    path.write_text("# T-261116-ms — M\n\nтеги: t\n\n## Цель\n\nx\n", encoding="utf-8")
    meta = parse_task(path)
    assert meta is not None
    assert meta.status == ""
    assert meta.value == ""


def test_parse_blank_status_is_empty(tmp_path: Path):
    path = tmp_path / "T-261116-bs.md"
    path.write_text(
        "# T-261116-bs — M\n\nстатус:   \nтеги: t\n\nЦенность: v\n",
        encoding="utf-8",
    )
    assert parse_task(path).status == ""


def test_parse_aliases_and_fields(tmp_path: Path):
    path = tmp_path / "T-261116-al.md"
    path.write_text(
        render_task_file(
            "T-261116-al",
            "A",
            status="queued",
            value="people",
            blocked_reason="r",
            blocked_deadline="2026-12-01",
            review_note="rn",
            acceptance_note="an",
        ),
        encoding="utf-8",
    )
    meta = parse_task(path)
    assert meta.status == "queue"
    assert meta.value == "people"
    assert meta.blocked_reason == "r"
    assert meta.blocked_deadline == "2026-12-01"
    assert meta.review_note == "rn"
    assert meta.acceptance_note == "an"


def test_set_field_insert_before_body():
    assert set_field("# Title\nbody\n", "claim", "z") == "# Title\nclaim: z\nbody\n"
    assert set_field("# Title\n\n\nbody\n", "claim", "z") == "# Title\n\n\nclaim: z\nbody\n"
    assert set_field("", "claim", "z") == "claim: z\n"
    base = render_task_file("T-261116-sf", "S", value="v")
    assert "статус: in-progress" in set_field(base, "статус", "in-progress")


def test_index_lanes_and_skip(tmp_path: Path):
    (tmp_path / "T-261116-r01.md").write_text(
        render_task_file("T-261116-r01", "One", status="queue", value="v"),
        encoding="utf-8",
    )
    (tmp_path / "T-261116-r02.md").write_text(
        render_task_file("T-261116-r02", "Two", status="self-review", value="v"),
        encoding="utf-8",
    )
    (tmp_path / "INDEX.md").write_text("# i\n", encoding="utf-8")
    idx = rebuild_task_index(tmp_path)
    for st in ACTIVE_STATUSES:
        assert f"## {st}" in idx
    assert "T-261116-r01" in idx and "T-261116-r02" in idx
    assert parse_task(tmp_path / "INDEX.md") is None
    ids = [t.task_id for t in list_tasks(tmp_path)]
    assert ids == ["T-261116-r01", "T-261116-r02"]


def test_allocate_and_utc(monkeypatch, tmp_path: Path):
    a = allocate_task_id(tmp_path, day="261116")
    (tmp_path / f"{a}.md").write_text("x", encoding="utf-8")
    assert allocate_task_id(tmp_path, day="261116") != a

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)

    monkeypatch.setattr("agentized.tasks.datetime", Fixed)
    assert utc_now_stamp() == "260102"
    assert "did" in append_progress("# T\n\n## Progress\n\nx\n", "did")


def test_allocate_exhausts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("agentized.tasks.secrets.token_hex", lambda n: "dead")
    (tmp_path / "T-261116-dead.md").write_text("x", encoding="utf-8")
    try:
        allocate_task_id(tmp_path, day="261116")
        raised = False
    except RuntimeError as exc:
        raised = True
        assert str(exc) == "не удалось выделить уникальный id задачи"
    assert raised is True


def test_parse_stem_fallback_and_skip(tmp_path: Path):
    bad = tmp_path / "notes.md"
    bad.write_text("hello\n", encoding="utf-8")
    assert parse_task(bad) is None
    stem = tmp_path / "T-261116-stem.md"
    stem.write_text("no title line\nстатус: open\n\nЦенность: v\n", encoding="utf-8")
    meta = parse_task(stem)
    assert meta is not None
    assert meta.task_id == "T-261116-stem"
    assert meta.status == "open"
    weird = tmp_path / "T-nope.md"
    weird.write_text("x\n", encoding="utf-8")
    assert parse_task(weird) is None


def test_render_extras_and_index_parent_claim(tmp_path: Path):
    text = render_task_file(
        "T-261116-ex",
        "Ex",
        value="v",
        blocked_reason="r",
        blocked_deadline="2026-01-01",
        review_note="rn",
        acceptance_note="an",
        parent="T-261116-par",
        claim="alice",
    )
    assert "blocked_reason: r" in text
    assert "review_note: rn" in text
    assert "acceptance_note: an" in text
    (tmp_path / "T-261116-ex.md").write_text(text, encoding="utf-8")
    (tmp_path / "T-261116-par.md").write_text(
        render_task_file("T-261116-par", "Par", status="open", value="v"),
        encoding="utf-8",
    )
    idx = rebuild_task_index(tmp_path)
    assert idx.count("- [T-261116-ex](T-261116-ex.md) — Ex (родитель: T-261116-par) · claim: alice") == 1
    assert idx.count("## open\n") == 1
