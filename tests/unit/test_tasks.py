"""Unit tests for agentized.tasks — selected by mutmut for tasks.py."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from agentized import tasks as tasks_mod
from agentized.tasks import (
    ALL_STATUSES,
    CANONICAL_STATUSES,
    FIELD_RE,
    STATUS_ALIASES,
    allocate_task_id,
    append_progress,
    append_status_progress,
    last_progress_entry,
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


def test_shared_status_list_and_field_re_keys():
    assert ALL_STATUSES == CANONICAL_STATUSES + ("dropped", "queued")
    assert STATUS_ALIASES == {"dropped": "canceled", "queued": "queue"}
    assert set(STATUS_ALIASES).issubset(ALL_STATUSES)
    assert {"queue", "self-review", "for-review", "canceled"}.issubset(ALL_STATUSES)
    assert FIELD_RE.match("acceptance_note: shipped").group(2) == "shipped"
    assert FIELD_RE.match("blocked_reason: dep").group(1) == "blocked_reason"
    assert FIELD_RE.match("blocked_deadline: 2026-12-01").group(2) == "2026-12-01"
    # empty value must not swallow next line ([ \t]* not \s*)
    body = "pr:\nreview_note: tip\n"
    assert dict(FIELD_RE.findall(body)) == {"pr": "", "review_note": "tip"}


def test_utc_now_stamp_format_and_tz(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)

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
        "# T-261116-sp — spaces\n\nстатус: blocked\nтеги:   \nродитель:   \nclaim: bob\n",
    )
    meta = parse_task(path)
    assert meta is not None
    assert (meta.tags, meta.parent, meta.claim, meta.status) == ("", "", "bob", "blocked")


def test_parse_task_skips_index_template_even_if_content_looks_valid(tmp_path: Path):
    # Same body parses as a real task file; INDEX/TEMPLATE/non-.md must still be skipped.
    validish = "# T-261116-abcd — should skip\n\nстатус: open\nclaim: z\n"
    control = parse_task(_write(tmp_path / "T-261116-abcd.md", validish))
    assert control is not None
    assert (control.task_id, control.title, control.status, control.claim) == (
        "T-261116-abcd",
        "should skip",
        "open",
        "z",
    )
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


def test_set_field_empty_claim_does_not_swallow_next_field():
    # Empty claim: then a following header — \\s* would eat the next line.
    text = (
        "# T-261116-sf — set_field\n\nстатус: open\nтеги: x\nродитель:\nclaim:\n## Цель\n\nbody\n"
    )
    claimed = set_field(text, "claim", "worker-a")
    assert claimed == (
        "# T-261116-sf — set_field\n\n"
        "статус: open\n"
        "теги: x\n"
        "родитель:\n"
        "claim: worker-a\n"
        "## Цель\n\nbody\n"
    )
    # Claim before статус (CLI-shaped: claim then status rewrite).
    flipped = "# T-261116-sf — set_field\n\nclaim:\nстатус: open\n"
    after_claim = set_field(flipped, "claim", "worker-b")
    assert after_claim == "# T-261116-sf — set_field\n\nclaim: worker-b\nстатус: open\n"
    after_status = set_field(after_claim, "статус", "in-progress")
    assert after_status == ("# T-261116-sf — set_field\n\nclaim: worker-b\nстатус: in-progress\n")


def test_set_field_cli_claim_sequence_preserves_neighbors(tmp_path: Path):
    """Mirror cmd_claim order: set_field(claim) then set_field(статус) on empty claim."""
    path = _write(
        tmp_path / "T-261116-cli.md",
        "# T-261116-cli — cli claim\n\n"
        "статус: open\n"
        "теги: AGE-43\n"
        "родитель:\n"
        "claim:\n\n"
        "## Цель\n\ngoal\n\n"
        "## Progress\n\n_(append-only)_\n",
    )
    body = path.read_text(encoding="utf-8")
    body = set_field(body, "claim", "cli-owner")
    body = set_field(body, "статус", "in-progress")
    body = append_progress(body, "claim by cli-owner")
    path.write_text(body, encoding="utf-8")
    meta = parse_task(path)
    assert meta is not None
    assert (meta.claim, meta.status, meta.parent, meta.tags) == (
        "cli-owner",
        "in-progress",
        "",
        "AGE-43",
    )
    assert "## Цель" in body
    assert "claim: cli-owner" in body
    assert "статус: in-progress" in body
    assert "родитель:\n" in body


def test_parse_task_crlf_and_trailing_whitespace(tmp_path: Path):
    crlf = (
        "# T-261116-cr — crlf\r\n\r\n"
        "статус: in-progress\r\n"
        "теги: a,b  \r\n"
        "родитель:  \r\n"
        "claim: worker-cr\r\n"
    )
    meta = parse_task(_write(tmp_path / "T-261116-cr.md", crlf))
    assert meta is not None
    assert (meta.parent, meta.claim, meta.tags, meta.status) == (
        "",
        "worker-cr",
        "a,b",
        "in-progress",
    )
    # Trailing spaces on same line must strip; empty parent still keeps claim.
    spaced = (
        "# T-261116-sp2 — spaces\n\nстатус: blocked   \nтеги:   \nродитель:   \nclaim:  bob  \n"
    )
    meta2 = parse_task(_write(tmp_path / "T-261116-sp2.md", spaced))
    assert meta2 is not None
    assert (meta2.parent, meta2.claim, meta2.tags, meta2.status) == (
        "",
        "bob",
        "",
        "blocked",
    )
    # set_field on CRLF empty claim must not swallow the next header.
    crlf_empty = "# T\r\n\r\nclaim:\r\nстатус: open\r\n"
    fixed = set_field(crlf_empty, "claim", "cr-owner")
    assert "статус: open" in fixed
    assert "claim: cr-owner" in fixed


def test_append_progress_exact_with_frozen_time(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return datetime(2026, 11, 16, 9, 41, 0, tzinfo=UTC)

    monkeypatch.setattr(tasks_mod, "datetime", Fixed)
    stamp = "2026-11-16 09:41 UTC"
    with_section = append_progress(
        "# T — x\n\n## Progress\n\n_(append-only)_\n\n## Decision Log\n\nz\n",
        "did",
    )
    assert with_section == (
        f"# T — x\n\n## Progress\n\n_(append-only)_\n- {stamp}: did\n\n## Decision Log\n\nz\n"
    )
    no_section = append_progress("# T — x\n", "start")
    assert no_section == f"# T — x\n\n## Progress\n\n- {stamp}: start\n"
    # Progress only (no following ##) → rest must be "" not "XXXX"; len(parts)==1
    only_prog = append_progress("# T — x\n\n## Progress\n\nold\n", "new")
    assert only_prog == (f"# T — x\n\n## Progress\n\nold\n- {stamp}: new\n")
    assert "XXXX" not in only_prog
    # Two real "## Progress" headers: split(marker, 1) required (bare split / split(,2) unpack-fail
    # or rsplit attaches the entry to the wrong section).
    multi = "# T — x\n\n## Progress\n\nfirst\n\n## Decision Log\n\nmid\n\n## Progress\n\nsecond\n"
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


def test_append_progress_never_prepends_existing_history(monkeypatch):
    """AGE-73: new bullets go after existing history, not under _(append-only)_ ahead of it."""

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return datetime(2026, 11, 21, 10, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(tasks_mod, "datetime", Fixed)
    stamp = "2026-11-21 10:00 UTC"
    base = (
        "# T — x\n\n## Progress\n\n_(append-only)_\n"
        "- 2026-11-21 09:00 UTC: claim by a\n"
        "- 2026-11-21 09:30 UTC: work done\n"
        "\n## Decision Log\n\nz\n"
    )
    out = append_progress(base, "newer tip")
    # Newest line is last (append), not first after the marker (prepend).
    assert out.index("claim by a") < out.index("work done") < out.index("newer tip")
    assert out == (
        "# T — x\n\n## Progress\n\n_(append-only)_\n"
        "- 2026-11-21 09:00 UTC: claim by a\n"
        "- 2026-11-21 09:30 UTC: work done\n"
        f"- {stamp}: newer tip\n"
        "\n## Decision Log\n\nz\n"
    )
    # Prepend would put the new stamp immediately after _(append-only)_.
    prog = out.split("## Progress", 1)[1].split("\n## ", 1)[0]
    assert not prog.lstrip().startswith(
        f"_(append-only)_\n- {stamp}: newer tip\n- 2026-11-21 09:00"
    )


def test_last_progress_entry_uses_first_progress_section():
    """Kill find/slice/len mutants on last_progress_entry Progress extraction."""
    assert last_progress_entry("# no progress") is None
    assert last_progress_entry("## Progress\n\n_(append-only)_\n") is None
    two = (
        "# T\n\n## Progress\n\n"
        "- 2026-11-21 09:00 UTC: first-section\n"
        "\n## Decision Log\n\n"
        "- 2026-11-21 10:00 UTC: not-progress\n"
        "\n## Progress\n\n"
        "- 2026-11-21 11:00 UTC: second-section\n"
    )
    # First ## Progress only (find, not rfind); Decision Log bullets ignored.
    assert last_progress_entry(two) == "first-section"
    only = "# T\n\n## Progress\n\n- 2026-11-21 09:00 UTC: older\n- 2026-11-21 09:30 UTC: newer\n"
    assert last_progress_entry(only) == "newer"
    # Marker length: truncated marker must not match.
    assert last_progress_entry("# T\n\n## Progres\n\n- 2026-11-21 09:00 UTC: x\n") is None
    # start == 0: kill start < 0 → <=0 / <1 (must still find Progress at file start).
    assert last_progress_entry("## Progress\n\n- 2026-11-21 09:00 UTC: at-start\n") == "at-start"
    # No following ## section: kill end-branch `and False` (after[:-1] truncates entry).
    assert (
        last_progress_entry("# T\n\n## Progress\n\n- 2026-11-21 09:00 UTC: only-section")
        == "only-section"
    )
    # end == 0 (Progress immediately followed by next ##): must not leak Decision bullets.
    assert (
        last_progress_entry(
            "## Progress\n## Decision Log\n\n- 2026-11-21 09:00 UTC: from-decision\n"
        )
        is None
    )


def test_append_status_progress_appends_and_dedupes(monkeypatch):
    """AGE-73: status→done Progress writer appends once; second identical call is no-op."""

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return datetime(2026, 11, 21, 11, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(tasks_mod, "datetime", Fixed)
    stamp = "2026-11-21 11:00 UTC"
    base = (
        "# T — x\n\nстатус: in-progress\n\n## Progress\n\n_(append-only)_\n"
        "- 2026-11-21 09:00 UTC: claim by a\n"
        "\n## Decision Log\n\n_(append-only)_\n"
    )
    once = append_status_progress(base, "done")
    assert last_progress_entry(once) == "статус → done"
    assert once.count("статус → done") == 1
    assert f"- 2026-11-21 09:00 UTC: claim by a\n- {stamp}: статус → done\n" in once
    assert once.index("claim by a") < once.index("статус → done")
    twice = append_status_progress(once, "done")
    assert twice == once
    # English alias on last line also dedupes.
    eng = append_progress(base, "status → self-review")
    assert append_status_progress(eng, "self-review") == eng
    # Different status still appends.
    other = append_status_progress(once, "self-review")
    assert other != once
    assert last_progress_entry(other) == "статус → self-review"
    assert other.count("статус → done") == 1
    assert other.count("статус → self-review") == 1


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


def test_active_statuses_lazy_identity_with_status_gates():
    from agentized import status_gates as sg
    from agentized import task_schema as ts
    from agentized import tasks as tasks_mod

    assert tasks_mod.ACTIVE_STATUSES is sg.INDEX_ACTIVE_STATUSES
    assert ts.ACTIVE_STATUSES is sg.INDEX_ACTIVE_STATUSES
    assert tasks_mod.CLAIM_STATUSES == ("open", "in-progress", "blocked")
    assert "queue" not in tasks_mod.CLAIM_STATUSES
    assert "self-review" not in tasks_mod.CLAIM_STATUSES


def test_rebuild_task_index_includes_orbit_id(tmp_path: Path):
    _write(
        tmp_path / "T-261116-orb.md",
        "# T-261116-orb — Orbit\n\nстатус: open\nтеги:\nродитель:\nclaim: eve\norbit_id: T-0023\n",
    )
    assert rebuild_task_index(tmp_path) == (
        "# Задачи — живой индекс\n\n"
        "Генерируемый список **активной** работы. Не полный архив истории.\n\n"
        "Статусы в индексе: `open` · `in-progress` · `blocked`.\n\n"
        "Поиск: этот индекс + grep по id / title / tags. Не обходи весь каталог `tasks/`.\n\n"
        "## open\n\n"
        "- [T-261116-orb](T-261116-orb.md) — Orbit · claim: eve · orbit: T-0023\n\n"
        "## in-progress\n\n_(пусто)_\n\n"
        "## blocked\n\n_(пусто)_\n\n"
        "Новые задачи — по [`TEMPLATE.md`](TEMPLATE.md). Файлы задач лежат рядом с этим индексом; "
        "при смене статуса файл **не перемещается**.\n"
    )


def test_rebuild_skips_underscore_orbit_id(tmp_path: Path):
    _write(
        tmp_path / "T-261116-orbx.md",
        "# T-261116-orbx — O\n\nстатус: open\nтеги:\nродитель:\nclaim:\norbit_id: _hidden\n",
    )
    index = rebuild_task_index(tmp_path)
    assert index == (
        "# Задачи — живой индекс\n\n"
        "Генерируемый список **активной** работы. Не полный архив истории.\n\n"
        "Статусы в индексе: `open` · `in-progress` · `blocked`.\n\n"
        "Поиск: этот индекс + grep по id / title / tags. Не обходи весь каталог `tasks/`.\n\n"
        "## open\n\n"
        "- [T-261116-orbx](T-261116-orbx.md) — O\n\n"
        "## in-progress\n\n_(пусто)_\n\n"
        "## blocked\n\n_(пусто)_\n\n"
        "Новые задачи — по [`TEMPLATE.md`](TEMPLATE.md). Файлы задач лежат рядом с этим индексом; "
        "при смене статуса файл **не перемещается**.\n"
    )
    assert "orbit:" not in index
    assert "_hidden" not in index


@pytest.mark.parametrize("status", ["self-review", "queue", "for-review"])
def test_claim_refuse_non_claim_status_not_active(tmp_path: Path, status: str):
    """Non-CLAIM_STATUSES claims must not satisfy refuse claim_check."""
    from agentized.process_control import active_claims, claim_check

    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tmp_path / "context" / "process-control.json").write_text(
        '{"claim_required": true, "claim_mode_agent": "refuse", "claim_mode_local": "warn"}\n',
        encoding="utf-8",
    )
    _write(
        tasks / "T-261116-srcl.md",
        f"# T-261116-srcl — SR\n\nстатус: {status}\nтеги:\nродитель:\nclaim: alice\n",
    )
    assert active_claims(tmp_path) == []
    refused = claim_check(tmp_path, ["runtime/x.py"], env={"CURSOR_AGENT": "1"})
    assert refused["ok"] is False
    assert refused["mode"] == "refuse"


def test_tasks_reexports_match_schema():
    from agentized import tasks
    from agentized.task_schema import render_task_file as schema_render
    from agentized.task_schema import set_field as schema_set

    assert tasks.render_task_file is schema_render
    assert tasks.set_field is schema_set
    text = "# T-1 — x\n\nродитель:\nclaim: alice\n"
    assert set_field(text, "родитель", "P") == "# T-1 — x\n\nродитель: P\nclaim: alice\n"


def test_tasks_getattr_unknown_message():
    import pytest
    from agentized import tasks as tasks_mod

    with pytest.raises(AttributeError, match="has no attribute 'not_a_real_export'") as ei:
        _ = tasks_mod.not_a_real_export
    assert "not_a_real_export" in str(ei.value)
    assert "agentized.tasks" in str(ei.value) or "tasks" in str(ei.value)
