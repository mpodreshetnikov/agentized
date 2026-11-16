"""Unit tests for agentized.tasks — selected by mutmut for tasks.py."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentized import tasks as tasks_mod
from agentized.tasks import (
    allocate_task_id,
    append_progress,
    list_tasks,
    parse_task,
    rebuild_task_index,
    render_task_file,
    set_field,
    utc_now_stamp,
)


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_utc_now_stamp_format_and_tz(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(tasks_mod, "datetime", Fixed)
    assert utc_now_stamp() == "261116"


def test_allocate_task_id_unique_day_and_hex_width(tmp_path: Path, monkeypatch):
    a = allocate_task_id(tmp_path, day="261116")
    (tmp_path / f"{a}.md").write_text("x", encoding="utf-8")
    b = allocate_task_id(tmp_path, day="261116")
    assert a != b
    assert a.startswith("T-261116-") and b.startswith("T-261116-")
    # token_hex width must stay 2 (4 hex chars).
    seen: list[int] = []

    def capture(n):
        seen.append(n)
        return "abcd"

    monkeypatch.setattr(tasks_mod.secrets, "token_hex", capture)
    got = allocate_task_id(tmp_path, day="261116")
    assert got == "T-261116-abcd"
    assert seen == [2]
    # day=None uses utc_now_stamp (or, not and).
    monkeypatch.setattr(tasks_mod, "utc_now_stamp", lambda: "990101")
    monkeypatch.setattr(tasks_mod.secrets, "token_hex", lambda _n: "eeee")
    assert allocate_task_id(tmp_path) == "T-990101-eeee"
    # Exhaustion — exactly 64 attempts (range(64), not 65).
    (tmp_path / "T-261116-dead.md").write_text("x", encoding="utf-8")
    calls = {"n": 0}

    def always_dead(_n):
        calls["n"] += 1
        return "dead"

    monkeypatch.setattr(tasks_mod.secrets, "token_hex", always_dead)
    with pytest.raises(RuntimeError, match="^не удалось выделить уникальный id задачи$"):
        allocate_task_id(tmp_path, day="261116")
    assert calls["n"] == 64


def test_parse_task_empty_parent_keeps_claim(tmp_path: Path):
    path = _write(
        tmp_path / "T-261116-emp.md",
        "# T-261116-emp — empty parent\n\n"
        "статус: in-progress\n"
        "теги: tasks,AGE-43\n"
        "родитель:\n"
        "claim: worker-x\n",
    )
    meta = parse_task(path)
    assert meta is not None
    assert (meta.parent, meta.claim, meta.tags, meta.status) == (
        "",
        "worker-x",
        "tasks,AGE-43",
        "in-progress",
    )
    index = rebuild_task_index(tmp_path)
    assert "claim: worker-x" in index
    assert "(родитель: claim: worker-x)" not in index


def test_parse_task_empty_tags_keeps_parent_and_claim(tmp_path: Path):
    path = _write(
        tmp_path / "T-261116-tag.md",
        "# T-261116-tag — empty tags\n\n"
        "статус: open\n"
        "теги:\n"
        "родитель: T-261116-root\n"
        "claim: alice\n",
    )
    meta = parse_task(path)
    assert meta is not None
    assert (meta.tags, meta.parent, meta.claim) == ("", "T-261116-root", "alice")


def test_parse_task_same_line_spaces_only_are_stripped(tmp_path: Path):
    path = _write(
        tmp_path / "T-261116-sp.md",
        "# T-261116-sp — spaces\n\n"
        "статус: blocked\n"
        "теги:   \n"
        "родитель:   \n"
        "claim: bob\n",
    )
    meta = parse_task(path)
    assert meta is not None
    assert (meta.tags, meta.parent, meta.claim, meta.status) == ("", "", "bob", "blocked")


def test_parse_task_skips_index_template_even_if_content_looks_valid(tmp_path: Path):
    # Content would parse if skip-list broke — stem fallback is not the kill.
    validish = "# T-261116-abcd — should skip\n\nстатус: open\nclaim: z\n"
    assert parse_task(_write(tmp_path / "INDEX.md", validish)) is None
    assert parse_task(_write(tmp_path / "TEMPLATE.md", validish)) is None
    assert parse_task(_write(tmp_path / "notes.txt", validish)) is None


def test_parse_task_read_text_encoding(tmp_path: Path, monkeypatch):
    path = _write(
        tmp_path / "T-261116-enc1.md",
        "# T-261116-enc1 — Enc\n\nстатус: open\n",
    )
    seen: dict[str, object] = {}
    real = Path.read_text

    def wrapped(self, *args, **kwargs):
        seen["kwargs"] = kwargs
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", wrapped)
    assert parse_task(path) is not None
    assert seen["kwargs"].get("encoding") == "utf-8"


def test_parse_task_stem_fallback_defaults_and_empty(tmp_path: Path, monkeypatch):
    path = _write(tmp_path / "T-261116-abcd.md", "no title line\nстатус: blocked\n")
    meta = parse_task(path)
    assert meta is not None
    assert (meta.task_id, meta.title, meta.status) == ("T-261116-abcd", "T-261116-abcd", "blocked")
    path2 = _write(tmp_path / "T-261116-ef01.md", "# T-261116-ef01 — titled\n\nтеги: x\n")
    meta2 = parse_task(path2)
    assert meta2 is not None
    assert (meta2.status, meta2.title, meta2.tags, meta2.claim) == ("idea", "titled", "x", "")
    empty = parse_task(_write(tmp_path / "T-261116-zz99.md", ""))
    assert empty is not None and empty.status == "idea" and empty.claim == ""
    # empty/whitespace body → first line must be "" (not "XXXX")
    captured: list[str] = []
    real_match = tasks_mod.re.match

    def capture_match(pattern, string, *a, **k):
        captured.append(string)
        return real_match(pattern, string, *a, **k)

    monkeypatch.setattr(tasks_mod.re, "match", capture_match)
    parse_task(_write(tmp_path / "T-261116-ws01.md", "   \n\n"))
    assert captured and captured[0] == ""


def test_render_task_file_exact_defaults_and_overrides():
    blank = render_task_file("T-261116-blnk", "Blank")
    assert blank == (
        "# T-261116-blnk — Blank\n\n"
        "статус: open\n"
        "теги: _(нет)_\n"
        "родитель: _(пусто для корневой задачи; для подзадачи — путь или id родителя)_\n"
        "claim: _(пусто или кто ведёт)_\n\n"
        "## Цель\n\n"
        "Что должно быть сделано.\n\n"
        "## Progress\n\n"
        "_(append-only)_\n\n"
        "## Decision Log\n\n"
        "_(append-only)_\n"
    )
    full = render_task_file(
        "T-261116-rend",
        "Demo",
        status="open",
        tags="q",
        parent="T-root",
        claim="carol",
        goal="Ship it.",
    )
    assert full == (
        "# T-261116-rend — Demo\n\n"
        "статус: open\n"
        "теги: q\n"
        "родитель: T-root\n"
        "claim: carol\n\n"
        "## Цель\n\n"
        "Ship it.\n\n"
        "## Progress\n\n"
        "_(append-only)_\n\n"
        "## Decision Log\n\n"
        "_(append-only)_\n"
    )


def test_list_tasks_sorted(tmp_path: Path):
    _write(
        tmp_path / "T-261116-b.md",
        render_task_file("T-261116-b", "B", status="open"),
    )
    _write(
        tmp_path / "T-261116-a.md",
        render_task_file("T-261116-a", "A", status="open"),
    )
    ids = [t.task_id for t in list_tasks(tmp_path)]
    assert ids == ["T-261116-a", "T-261116-b"]


def test_set_field_replace_insert_newline_and_blank_skip():
    base = "статус: open\nстатус: open\n"
    # count=1 replaces only first
    one = set_field(base, "статус", "done")
    assert one == "статус: done\nстатус: open\n"
    assert set_field("", "claim", "x") == "claim: x\n"
    # one blank after title: +=1 lands before body; +=2 would skip past body
    src = "# Title\n\nbody\n"
    out = set_field(src, "claim", "dave")
    assert out == "# Title\n\nclaim: dave\nbody\n"
    # single-line title only: insert_at < len (not <=) must not IndexError
    assert set_field("# Title\n", "claim", "solo") == "# Title\nclaim: solo\n"
    # no trailing newline on source → none on result
    assert set_field("# Title\nbody", "claim", "e") == "# Title\nclaim: e\nbody"


def test_append_progress_exact_with_frozen_time(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return datetime(2026, 11, 16, 9, 41, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(tasks_mod, "datetime", Fixed)
    stamp = "2026-11-16 09:41 UTC"
    with_section = append_progress(
        "# T — x\n\n## Progress\n\n_(append-only)_\n\n## Decision Log\n\nz\n",
        "did",
    )
    assert with_section == (
        "# T — x\n\n## Progress\n\n_(append-only)_\n"
        f"- {stamp}: did\n"
        "\n## Decision Log\n\nz\n"
    )
    no_section = append_progress("# T — x\n", "start")
    assert no_section == f"# T — x\n\n## Progress\n\n- {stamp}: start\n"
    # Progress only (no following ##) → rest must be "" not "XXXX"; len(parts)==1
    only_prog = append_progress("# T — x\n\n## Progress\n\nold\n", "new")
    assert only_prog == (
        "# T — x\n\n## Progress\n\nold\n"
        f"- {stamp}: new\n"
    )
    assert "XXXX" not in only_prog
    # Two real "## Progress" headers: split(marker, 1) required (bare split / split(,2) unpack-fail
    # or rsplit attaches the entry to the wrong section).
    multi = (
        "# T — x\n\n## Progress\n\nfirst\n\n## Decision Log\n\nmid\n\n"
        "## Progress\n\nsecond\n"
    )
    multi_out = append_progress(multi, "e2")
    assert multi_out == (
        "# T — x\n\n## Progress\n\nfirst\n"
        f"- {stamp}: e2\n"
        "\n## Decision Log\n\nmid\n\n## Progress\n\nsecond\n"
    )
    # rstrip (not lstrip) on body without section
    padded = append_progress("# T — x\n   \n", "p")
    assert padded.startswith("# T — x\n\n## Progress\n\n- ")
    assert padded.endswith(f"- {stamp}: p\n")


def test_rebuild_task_index_exact(tmp_path: Path):
    _write(
        tmp_path / "T-261116-o1.md",
        "# T-261116-o1 — Open one\n\nстатус: open\nтеги:\nродитель: T-parent\nclaim: eve\n",
    )
    _write(
        tmp_path / "T-261116-i1.md",
        "# T-261116-i1 — IP\n\nстатус: in-progress\nтеги:\nродитель: _(placeholder)_\nclaim: _(пусто)_\n",
    )
    _write(
        tmp_path / "T-261116-b1.md",
        "# T-261116-b1 — Blocked\n\nстатус: blocked\nтеги:\nродитель:\nclaim: frank\n",
    )
    _write(
        tmp_path / "T-261116-d1.md",
        "# T-261116-d1 — Done skip\n\nстатус: done\nтеги:\nродитель:\nclaim: x\n",
    )
    index = rebuild_task_index(tmp_path)
    assert index == (
        "# Задачи — живой индекс\n\n"
        "Генерируемый список **активной** работы. Не полный архив истории.\n\n"
        "Статусы в индексе: `open` · `in-progress` · `blocked`.\n\n"
        "Поиск: этот индекс + grep по id / title / tags. Не обходи весь каталог `tasks/`.\n\n"
        "## open\n\n"
        "- [T-261116-o1](T-261116-o1.md) — Open one (родитель: T-parent) · claim: eve\n\n"
        "## in-progress\n\n"
        "- [T-261116-i1](T-261116-i1.md) — IP\n\n"
        "## blocked\n\n"
        "- [T-261116-b1](T-261116-b1.md) — Blocked · claim: frank\n\n"
        "Новые задачи — по [`TEMPLATE.md`](TEMPLATE.md). Файлы задач лежат рядом с этим индексом; "
        "при смене статуса файл **не перемещается**.\n"
    )
    (tmp_path / "empty").mkdir()
    empty = rebuild_task_index(tmp_path / "empty")
    assert empty == (
        "# Задачи — живой индекс\n\n"
        "Генерируемый список **активной** работы. Не полный архив истории.\n\n"
        "Статусы в индексе: `open` · `in-progress` · `blocked`.\n\n"
        "Поиск: этот индекс + grep по id / title / tags. Не обходи весь каталог `tasks/`.\n\n"
        "## open\n\n_(пусто)_\n\n"
        "## in-progress\n\n_(пусто)_\n\n"
        "## blocked\n\n_(пусто)_\n\n"
        "Новые задачи — по [`TEMPLATE.md`](TEMPLATE.md). Файлы задач лежат рядом с этим индексом; "
        "при смене статуса файл **не перемещается**.\n"
    )
    # two rows in one bucket → join with "\n" not "XX\nXX"
    _write(
        tmp_path / "T-261116-o2.md",
        "# T-261116-o2 — Open two\n\nстатус: open\nтеги:\nродитель:\nclaim:\n",
    )
    two_open = rebuild_task_index(tmp_path)
    open_section = two_open.split("## open\n\n", 1)[1].split("\n\n## in-progress", 1)[0]
    assert open_section == (
        "- [T-261116-o1](T-261116-o1.md) — Open one (родитель: T-parent) · claim: eve\n"
        "- [T-261116-o2](T-261116-o2.md) — Open two"
    )
    assert "XX\nXX" not in two_open
