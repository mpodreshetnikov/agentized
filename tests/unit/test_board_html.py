"""board_html renderer — fail-loud, RU UI, queue/overdue (AGE-37)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentized.board_html import (
    CANONICAL_STATUSES,
    COLUMN_FOR_STATUS,
    DEFAULT_LANG,
    DEFAULT_TITLE,
    FOR_REVIEW_NOTE,
    JOIN_NL,
    OVERDUE_HOURS,
    STATUS_ALIASES,
    BoardError,
    _CSS,
    _plain,
    _render_card,
    _render_column,
    _subtask_ids,
    age_hours,
    board_columns,
    collect_board_cards,
    column_for_status,
    escape,
    extract_description,
    extract_fields,
    extract_goal_blurb,
    extract_value_line,
    generate_board,
    human_status,
    is_queue_overdue,
    normalize_status,
    parse_status_changed_at,
    render_board_html,
    require_status,
    require_task_header,
    ui_for,
    write_board,
)
from agentized.board_html_io import ENCODING, read_task_text, write_html

# Far from wall-clock so age_hours(..., now=None) mutants cannot match exact labels.
NOW = datetime(2099, 6, 1, 12, 0, tzinfo=timezone.utc)


def _write_task(
    tasks: Path,
    task_id: str,
    title: str,
    *,
    status: str = "open",
    goal: str = "короткая цель",
    value: str = "",
    parent: str = "",
    claim: str = "",
    extra_fields: str = "",
    progress: str = "",
) -> None:
    parent_line = f"родитель: {parent}" if parent else "родитель: _(пусто)_"
    claim_line = f"claim: {claim}" if claim else "claim: _(пусто)_"
    extra = (extra_fields.strip() + "\n") if extra_fields.strip() else ""
    value_block = f"\nЦенность: {value}\n" if value else "\n"
    progress_block = progress or "_(append-only)_"
    text = (
        f"# {task_id} — {title}\n\n"
        f"статус: {status}\n"
        f"теги: _(нет)_\n"
        f"{parent_line}\n"
        f"{claim_line}\n"
        f"{extra}"
        f"{value_block}"
        f"## Цель\n\n{goal}\n\n"
        f"## Progress\n\n{progress_block}\n"
    )
    (tasks / f"{task_id}.md").write_text(text, encoding="utf-8")


def test_canonical_and_columns_ru():
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
    assert COLUMN_FOR_STATUS["self-review"] == "queue"
    assert COLUMN_FOR_STATUS["queue"] == "queue"
    assert COLUMN_FOR_STATUS["idea"] == "open"
    cols = board_columns("ru")
    assert cols == (
        ("open", "Открыто"),
        ("queue", "Очередь"),
        ("in-progress", "В работе"),
        ("for-review", "На ревью"),
        ("blocked", "Заблокировано"),
        ("done", "Готово"),
        ("canceled", "Отменено"),
    )
    assert board_columns("en")[0] == ("open", "Open")
    assert DEFAULT_LANG == "ru"
    assert DEFAULT_TITLE == "Доска задач Agentized"
    assert JOIN_NL == "\n"
    assert OVERDUE_HOURS == 12
    assert FOR_REVIEW_NOTE == "только Maxim"
    assert ".card.overdue" in _CSS


def test_normalize_require_status_and_human():
    assert normalize_status(None) == ""
    assert normalize_status("") == ""
    assert normalize_status("queued") == "queue"
    assert normalize_status("OPEN") == "open"
    with pytest.raises(BoardError) as missing:
        require_status("", path="x.md")
    assert missing.value.reason == "missing status"
    with pytest.raises(BoardError) as unknown:
        require_status("flying", path="x.md")
    assert "unknown status" in unknown.value.reason
    assert require_status("self-review", path="x.md") == "self-review"
    assert column_for_status("self-review") == "queue"
    assert human_status("self-review", "ru") == "самопроверка"
    assert human_status("for-review", "en") == "for review"
    assert human_status("not-a-status", "ru") == "not-a-status"
    with pytest.raises(BoardError) as bad_lang:
        ui_for("de")
    assert bad_lang.value.path == "<lang>"
    assert bad_lang.value.reason == "unknown lang 'de'; expected ru|en"


def test_escape_plain_extractors():
    assert escape("<a>") == "&lt;a&gt;"
    assert escape(None) == ""
    assert escape("'x'") == "&#x27;x&#x27;"
    assert _plain("_(пусто)_") == ""
    assert _plain(" alice ") == "alice"
    assert _plain(None) == ""
    text = "статус: open\n\nЦенность: val\n\n## Цель\n\nсделать хорошо\n\n## Progress\n"
    assert extract_value_line(text) == "val"
    assert extract_value_line(None) == ""
    assert extract_value_line("no value here\n") == ""
    assert extract_goal_blurb(text) == "сделать хорошо"
    assert extract_goal_blurb(None) == ""
    assert extract_goal_blurb("## Цель\n\n_(пусто)_\n\n## Progress\n") == ""
    # blank then real line — continue (not break) must reach the goal
    assert (
        extract_goal_blurb("## Цель\n\n\n_(skip)_\n\nреальная цель\n\n## X\n")
        == "реальная цель"
    )
    assert extract_description(text) == "сделать хорошо"
    assert extract_description("Ценность: only\n") == "only"
    assert extract_description("nothing useful\n") == ""
    assert extract_fields(text)["статус"] == "open"
    assert extract_fields(None) == {}


def test_age_and_overdue():
    text = (
        "## Progress\n"
        "- 2099-06-01 00:00 UTC: статус → queue\n"
        "- 2099-06-01 01:00 UTC: note\n"
    )
    changed = parse_status_changed_at(text)
    assert changed == datetime(2099, 6, 1, 0, 0, tzinfo=timezone.utc)
    hours = age_hours(changed, now=NOW)
    assert hours == 12.0
    assert is_queue_overdue("queue", 12.0) is False
    assert is_queue_overdue("queue", 12.1) is True
    assert is_queue_overdue("self-review", None) is True
    assert is_queue_overdue("open", 100.0) is False
    assert age_hours(None, now=NOW) is None
    # clock resolved upstream — age_hours itself requires an explicit now
    assert age_hours(changed, now=NOW) == 12.0
    assert parse_status_changed_at("## Progress\n_(none)_\n") is None
    fallback = parse_status_changed_at(
        "## Progress\n- 2099-05-31 10:00 UTC: claim by x\n"
    )
    assert fallback == datetime(2099, 5, 31, 10, 0, tzinfo=timezone.utc)


def test_fail_loud_missing_dir_empty_bad_header_status(tmp_path: Path):
    missing = tmp_path / "no-tasks"
    with pytest.raises(BoardError) as e1:
        collect_board_cards(missing, now=NOW)
    assert e1.value.path == str(missing)
    assert e1.value.reason == "missing context/tasks directory"
    assert str(e1.value) == f"{missing}: missing context/tasks directory"

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    empty = tasks / "T-261116-emp.md"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(BoardError) as e2:
        collect_board_cards(tasks, now=NOW)
    assert e2.value.path == str(empty)
    assert e2.value.reason == "empty file"
    empty.unlink()

    bad = tasks / "T-261116-bad.md"
    bad.write_text("# junk\n\nстатус: open\n", encoding="utf-8")
    with pytest.raises(BoardError) as e3:
        collect_board_cards(tasks, now=NOW)
    assert e3.value.path == str(bad)
    assert e3.value.reason == "unparseable or missing # T-… — title header"
    bad.unlink()

    no_status = tasks / "T-261116-ns.md"
    no_status.write_text(
        "# T-261116-ns — NoStatus\n\nтеги: x\n\n## Цель\n\ng\n",
        encoding="utf-8",
    )
    with pytest.raises(BoardError) as e4:
        collect_board_cards(tasks, now=NOW)
    assert e4.value.path == str(no_status)
    assert e4.value.reason == "missing status"
    no_status.unlink()

    blank_status = tasks / "T-261116-bs.md"
    blank_status.write_text(
        "# T-261116-bs — Blank\n\nстатус:   \n\n## Цель\n\ng\n",
        encoding="utf-8",
    )
    with pytest.raises(BoardError) as e4b:
        collect_board_cards(tasks, now=NOW)
    assert e4b.value.path == str(blank_status)
    assert e4b.value.reason == "missing status"
    blank_status.unlink()

    unk = tasks / "T-261116-unk.md"
    unk.write_text(
        "# T-261116-unk — Unk\n\nстатус: flying\n\n## Цель\n\ng\n",
        encoding="utf-8",
    )
    with pytest.raises(BoardError) as e5:
        collect_board_cards(tasks, now=NOW)
    assert e5.value.path == str(unk)
    assert e5.value.reason == "unknown status 'flying'"


def test_collect_and_render_ru_queue_overdue(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _write_task(
        tasks,
        "T-261116-aaa",
        "Alpha <xss>",
        status="open",
        goal="увидеть доску",
    )
    _write_task(
        tasks,
        "T-261116-srv",
        "Self",
        status="self-review",
        goal="проверить себя",
        progress="- 2099-05-31 12:00 UTC: статус → self-review\n",
    )
    # Fresh queue item — NOT overdue at NOW (1h old). Kills hours=None survivors.
    _write_task(
        tasks,
        "T-261116-fresh",
        "Fresh",
        status="queue",
        goal="свежая",
        progress="- 2099-06-01 11:00 UTC: статус → queue\n",
    )
    _write_task(
        tasks,
        "T-261116-frv",
        "ForRev",
        status="for-review",
        goal="отдать Maxim",
        progress="- 2099-06-01 11:00 UTC: статус → for-review\n",
    )
    _write_task(
        tasks,
        "T-261116-blk",
        "Blocked",
        status="blocked",
        goal="ждём API",
        claim="alice",
        extra_fields="blocked_reason: wait\nblocked_deadline: 2026-12-01\n",
    )
    cards = collect_board_cards(tasks, lang="ru", now=NOW)
    by_id = {c["id"]: c for c in cards}
    assert by_id["T-261116-srv"]["column"] == "queue"
    assert by_id["T-261116-srv"]["overdue"] == "1"
    assert by_id["T-261116-srv"]["updated"] == "2099-05-31 12:00 UTC (24.0h)"
    assert by_id["T-261116-srv"]["status_label"] == "самопроверка"
    assert by_id["T-261116-fresh"]["overdue"] == ""
    assert by_id["T-261116-fresh"]["updated"] == "2099-06-01 11:00 UTC (1.0h)"
    assert by_id["T-261116-aaa"]["description"] == "увидеть доску"
    assert by_id["T-261116-aaa"]["overdue"] == ""
    assert by_id["T-261116-blk"]["claim"] == "alice"
    assert by_id["T-261116-blk"]["blocked_reason"] == "wait"
    assert by_id["T-261116-blk"]["blocked_deadline"] == "2026-12-01"
    assert by_id["T-261116-aaa"]["blocked_reason"] == ""
    assert by_id["T-261116-aaa"]["blocked_deadline"] == ""
    assert by_id["T-261116-aaa"]["updated"] == ""
    assert by_id["T-261116-aaa"]["claim"] == ""
    assert set(by_id["T-261116-blk"]) == {
        "id",
        "title",
        "status",
        "status_label",
        "description",
        "claim",
        "parent",
        "blocked_reason",
        "blocked_deadline",
        "column",
        "updated",
        "overdue",
    }
    en_cards = collect_board_cards(tasks, lang="en", now=NOW)
    assert {c["id"]: c["status_label"] for c in en_cards}["T-261116-srv"] == (
        "self-review"
    )

    html = generate_board(tasks, lang="ru", now=NOW, title="Моя доска")
    assert "<title>Моя доска</title>" in html
    assert "<h1>Моя доска</h1>" in html
    assert 'lang="ru"' in html
    assert "Открыто" in html
    assert "Очередь" in html
    assert "На ревью" in html
    assert FOR_REVIEW_NOTE in html
    assert "только Maxim" in html
    assert "Alpha &lt;xss&gt;" in html
    assert "увидеть доску" in html
    assert "Просрочено" in html
    assert "Обновлено: 2099-05-31 12:00 UTC (24.0h)" in html
    assert "Обновлено: 2099-06-01 11:00 UTC (1.0h)" in html
    assert "Статус: самопроверка" in html
    assert "Claim: alice" in html
    assert "Блок: wait" in html
    assert "Дедлайн: 2026-12-01" in html
    assert "XX" not in html
    assert "None" not in html
    assert "<HEAD>" not in html
    assert html.startswith("<!DOCTYPE html>\n")
    assert '<meta charset="utf-8">' in html
    queue_sec = html.split('data-column="queue"')[1].split("data-column=")[0]
    assert ">Self</h3>" in queue_sec
    assert ">Fresh</h3>" in queue_sec
    # overdue class only on Self, not Fresh
    assert queue_sec.count("card overdue") == 1
    fr = html.split('data-column="for-review"')[1].split("data-column=")[0]
    assert FOR_REVIEW_NOTE in fr
    assert ">ForRev</h3>" in fr
    en_html = generate_board(tasks, lang="en", now=NOW, title="Board")
    assert 'lang="en"' in en_html
    assert "Status: self-review" in en_html
    assert "Overdue" in en_html


def test_aliases_and_determinism(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _write_task(tasks, "T-261116-que", "Q", status="queued", goal="g")
    _write_task(tasks, "T-261116-drp", "D", status="dropped", goal="g")
    cards = collect_board_cards(tasks, now=NOW)
    by_id = {c["id"]: c for c in cards}
    assert by_id["T-261116-que"]["status"] == "queue"
    assert by_id["T-261116-que"]["column"] == "queue"
    assert by_id["T-261116-drp"]["status"] == "canceled"
    a = generate_board(tasks, now=NOW)
    b = generate_board(tasks, now=NOW)
    assert a == b
    stamped = generate_board(tasks, generated_at="2026-11-16T00:00:00Z", now=NOW)
    assert "Сгенерировано: 2026-11-16T00:00:00Z" in stamped
    en = generate_board(tasks, lang="en", title="Board", now=NOW)
    assert 'lang="en"' in en
    assert "Queue" in en
    assert "only Maxim" in en


def test_write_board_and_subtasks(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _write_task(tasks, "T-261116-par", "P", status="open", goal="parent")
    _write_task(
        tasks,
        "T-261116-ch",
        "C",
        status="in-progress",
        parent="T-261116-par",
        goal="child",
    )
    out = tmp_path / "a" / "b" / "board.html"
    written = write_board(
        tasks,
        out,
        title="Кастом",
        lang="ru",
        now=NOW,
        generated_at="2026-11-16T12:00:00Z",
    )
    assert written == out
    body = out.read_text(encoding="utf-8")
    assert "<title>Кастом</title>" in body
    assert 'lang="ru"' in body
    assert "Сгенерировано: 2026-11-16T12:00:00Z" in body
    assert "Подзадачи: T-261116-ch" in body
    assert "Родитель: T-261116-par" in body
    # now= must be forwarded — stamp age uses NOW=2099, not wall clock
    _write_task(
        tasks,
        "T-261116-aged",
        "Aged",
        status="queue",
        goal="g",
        progress="- 2099-06-01 11:00 UTC: статус → queue\n",
    )
    aged_out = tmp_path / "aged.html"
    write_board(tasks, aged_out, title="Aged", lang="ru", now=NOW)
    aged_body = aged_out.read_text(encoding="utf-8")
    assert "Обновлено: 2099-06-01 11:00 UTC (1.0h)" in aged_body
    en_out = tmp_path / "en.html"
    write_board(tasks, en_out, title="EN Board", lang="en", now=NOW)
    en_body = en_out.read_text(encoding="utf-8")
    assert 'lang="en"' in en_body
    assert "<title>EN Board</title>" in en_body
    assert "only Maxim" in en_body
    assert "Updated: 2099-06-01 11:00 UTC (1.0h)" in en_body
    kids = _subtask_ids(
        [
            {
                "id": "T-261116-par",
                "parent": "",
                "title": "",
                "status": "open",
                "status_label": "",
                "description": "",
                "claim": "",
                "blocked_reason": "",
                "blocked_deadline": "",
                "column": "open",
                "updated": "",
                "overdue": "",
            },
            {
                "id": "T-261116-zb",
                "parent": "T-261116-par",
                "title": "",
                "status": "open",
                "status_label": "",
                "description": "",
                "claim": "",
                "blocked_reason": "",
                "blocked_deadline": "",
                "column": "open",
                "updated": "",
                "overdue": "",
            },
            {
                "id": "T-261116-ya",
                "parent": "T-261116-par",
                "title": "",
                "status": "open",
                "status_label": "",
                "description": "",
                "claim": "",
                "blocked_reason": "",
                "blocked_deadline": "",
                "column": "open",
                "updated": "",
                "overdue": "",
            },
        ]
    )
    assert kids == {"T-261116-par": ["T-261116-ya", "T-261116-zb"]}
    orphan = _subtask_ids(
        [
            {
                "id": "T-261116-or",
                "parent": "T-missing",
                "title": "",
                "status": "open",
                "status_label": "",
                "description": "",
                "claim": "",
                "blocked_reason": "",
                "blocked_deadline": "",
                "column": "open",
                "updated": "",
                "overdue": "",
            }
        ]
    )
    assert orphan == {}


def test_render_helpers_and_empty():
    u = ui_for("ru")
    card = {
        "id": "T-261116-x1",
        "title": "X",
        "status": "blocked",
        "status_label": "заблокирована",
        "description": "desc",
        "claim": "c",
        "parent": "T-261116-p",
        "blocked_reason": "why",
        "blocked_deadline": "2026-01-01",
        "column": "blocked",
        "updated": "2026-11-16 00:00 UTC (12.0h)",
        "overdue": "",
    }
    rendered = _render_card(card, ["T-261116-c1", "T-261116-c2"], u)
    assert '<p class="card-id">T-261116-x1</p>' in rendered
    assert "Статус: заблокирована" in rendered
    assert "Блок: why" in rendered
    assert "Дедлайн: 2026-01-01" in rendered
    assert "Подзадачи: T-261116-c1, T-261116-c2" in rendered
    assert "XX, XX" not in rendered
    assert rendered.endswith("</article>")
    assert "</ARTICLE>" not in rendered
    assert "XX" not in rendered
    assert "None" not in rendered
    overdue = dict(card)
    overdue["status"] = "queue"
    overdue["status_label"] = "очередь"
    overdue["overdue"] = "1"
    overdue["blocked_reason"] = ""
    overdue["blocked_deadline"] = ""
    od = _render_card(overdue, [], u)
    assert 'class="card overdue"' in od
    assert "Просрочено" in od
    empty = render_board_html([], lang="ru")
    assert empty.count("(пусто)") == len(board_columns("ru"))
    assert 'lang="ru"' in empty
    col = _render_column("for-review", "На ревью", [], {}, u)
    assert FOR_REVIEW_NOTE in col
    assert "(0)" in col


def test_board_html_io_roundtrip(tmp_path: Path):
    assert ENCODING == "utf-8"
    deep = tmp_path / "a" / "b" / "c" / "out.html"
    payload = "<!DOCTYPE html>\n<html>Ценность: café</html>\n"
    write_html(deep, payload)
    assert deep.read_bytes() == payload.encode("utf-8")
    assert read_task_text(deep) == payload
    write_html(deep, payload + "<!--2-->\n")
    assert read_task_text(deep).endswith("<!--2-->\n")
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe")
    with pytest.raises(UnicodeDecodeError):
        read_task_text(bad)


def test_require_task_header_ok():
    m = require_task_header("# T-261116-ok — Title\n\nстатус: open\n", Path("x.md"))
    assert m.group(1) == "T-261116-ok"
    assert m.group(2).strip() == "Title"
    with pytest.raises(
        TypeError, match=r"^require_task_header path must be pathlib\.Path$"
    ):
        require_task_header("# T-261116-ok — Title\n", "x.md")  # type: ignore[arg-type]


def test_unknown_column_and_render_shape():
    bad_card = {
        "id": "T-261116-badcol",
        "title": "X",
        "status": "open",
        "status_label": "открыта",
        "description": "",
        "claim": "",
        "parent": "",
        "blocked_reason": "",
        "blocked_deadline": "",
        "column": "not-a-column",
        "updated": "",
        "overdue": "",
    }
    with pytest.raises(BoardError) as exc:
        render_board_html([bad_card], lang="ru")
    assert exc.value.path == "T-261116-badcol"
    assert exc.value.reason == "unknown column 'not-a-column'"
    no_id = dict(bad_card)
    no_id["id"] = ""
    with pytest.raises(BoardError) as exc2:
        render_board_html([no_id], lang="ru")
    assert exc2.value.path == "?"
    empty = render_board_html([], lang="ru", title="T")
    assert empty.startswith("<!DOCTYPE html>\n")
    assert '<meta charset="utf-8">' in empty
    assert "</head>\n" in empty
    assert "<body>\n" in empty
    assert "<header>\n" in empty
    assert "</header>\n" in empty
    assert '<main class="board">\n' in empty
    assert "\n</main>\n" in empty
    assert "</body>\n" in empty
    assert empty.endswith("</html>\n")
    assert "None" not in empty
    assert "<HEAD>" not in empty
    assert "</BODY>" not in empty
    assert "</MAIN>" not in empty
    assert "</HTML>" not in empty
    # intro must come from UI (kills escape(None) on intro)
    assert "Канбан из context/tasks" in empty


def test_require_status_messages():
    with pytest.raises(BoardError) as e:
        require_status(None, path="/tmp/a.md")
    assert e.value.path == "/tmp/a.md"
    assert e.value.reason == "missing status"
    with pytest.raises(BoardError) as e2:
        require_status("nope", path="/tmp/b.md")
    assert e2.value.path == "/tmp/b.md"
    assert e2.value.reason == "unknown status 'nope'"
