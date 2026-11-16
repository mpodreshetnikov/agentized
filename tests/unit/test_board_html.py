"""board_html — fail-loud, status_gates vocab, RU UI (AGE-37)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentized.board_html import (
    CANONICAL_STATUSES,
    COLUMN_FOR_STATUS,
    DEFAULT_LANG,
    DEFAULT_TITLE,
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
    for_review_note,
    generate_board,
    header_block,
    human_status,
    is_queue_overdue,
    load_human_participants,
    normalize_status,
    parse_status_changed_at,
    remember_task_id,
    render_board_html,
    require_status,
    require_task_header,
    ui_for,
    write_board,
)
from agentized.status_gates import ALL_STATUSES, INDEX_ACTIVE_STATUSES

NOW = datetime(2099, 6, 1, 12, 0, tzinfo=timezone.utc)


def _write_task(
    tasks: Path,
    task_id: str,
    title: str,
    *,
    status: str = "open",
    goal: str = "цель",
    parent: str = "",
    claim: str = "",
    extra_fields: str = "",
    progress: str = "",
    body_extra: str = "",
) -> None:
    parent_line = f"родитель: {parent}" if parent else "родитель: _(пусто)_"
    claim_line = f"claim: {claim}" if claim else "claim: _(пусто)_"
    extra = (extra_fields.strip() + "\n") if extra_fields.strip() else ""
    text = (
        f"# {task_id} — {title}\n\nстатус: {status}\nтеги: _(нет)_\n"
        f"{parent_line}\n{claim_line}\n{extra}\n"
        f"## Цель\n\n{goal}\n\n{body_extra}"
        f"## Progress\n\n{progress or '_(append-only)_'}\n"
    )
    (tasks / f"{task_id}.md").write_text(text, encoding="utf-8")


def test_status_gates_surface_and_columns():
    assert CANONICAL_STATUSES[0] == "idea" and CANONICAL_STATUSES[-1] == "canceled"
    assert STATUS_ALIASES == {"dropped": "canceled", "queued": "queue"}
    assert COLUMN_FOR_STATUS["self-review"] == "queue"
    assert COLUMN_FOR_STATUS["queue"] == "queue"
    assert COLUMN_FOR_STATUS["idea"] == "open"
    assert INDEX_ACTIVE_STATUSES[0] == "open" and "done" not in INDEX_ACTIVE_STATUSES
    for raw in ALL_STATUSES:
        assert normalize_status(raw) in CANONICAL_STATUSES
    assert board_columns("ru") == (
        ("open", "Открыто"),
        ("queue", "Очередь"),
        ("in-progress", "В работе"),
        ("for-review", "На ревью"),
        ("blocked", "Заблокировано"),
        ("done", "Готово"),
        ("canceled", "Отменено"),
    )
    assert DEFAULT_LANG == "ru" and DEFAULT_TITLE.startswith("Доска")
    assert JOIN_NL == "\n" and OVERDUE_HOURS == 12
    assert for_review_note("ru", ["Maxim"]) == "только Maxim"
    assert ".card.overdue" in _CSS


def test_normalize_human_escape_header_fields():
    assert normalize_status(None) == "" and normalize_status("queued") == "queue"
    with pytest.raises(BoardError) as missing:
        require_status("", path="x.md")
    assert missing.value.path == "x.md" and missing.value.reason == "missing status"
    with pytest.raises(BoardError) as unknown:
        require_status("flying", path="x.md")
    assert unknown.value.path == "x.md"
    assert column_for_status("self-review") == "queue"
    assert human_status("self-review", "ru") == "самопроверка"
    with pytest.raises(BoardError) as bad_lang:
        ui_for("de")
    assert bad_lang.value.path == "<lang>"
    assert escape("<a>") == "&lt;a&gt;" and escape(None) == ""
    assert _plain(None) == "" and _plain("_(x)_") == "" and _plain(" a ") == "a"
    text = "статус: open\n\nЦенность: val\n\n## Цель\n\ngoal\n\nстатус: done\n"
    assert header_block(text).endswith("Ценность: val\n")
    assert header_block("## x\n") == ""
    assert extract_fields(text)["статус"] == "open"
    with pytest.raises(BoardError) as dup:
        extract_fields("статус: a\nстатус: b\n", path="d.md")
    assert dup.value.path == "d.md" and dup.value.reason == "duplicate field статус"
    with pytest.raises(BoardError) as dup_def:
        extract_fields("статус: a\nстатус: b\n")
    assert dup_def.value.path == "<text>"
    assert extract_value_line(text) == "val" and extract_value_line(None) == ""
    assert extract_goal_blurb(text) == "goal" and extract_goal_blurb(None) == ""
    assert extract_description(text) == "goal"


def test_age_no_fail_open_and_stamp_errors():
    real = (
        "## Progress\n- 2099-05-31 12:00 UTC: claim\n"
        "- 2099-05-31 17:08 UTC: task→self-review; push\n"
        "- 2099-06-01 11:50 UTC: note\n"
    )
    changed = parse_status_changed_at(real, "self-review", path="t.md", now=NOW)
    assert changed == datetime(2099, 5, 31, 17, 8, tzinfo=timezone.utc)
    assert parse_status_changed_at(real, "done", path="t.md", now=NOW) is None
    later = (
        "## Progress\n- 2099-05-31 12:00 UTC: статус → queue\n"
        "- 2099-06-01 11:00 UTC: note\n"
    )
    assert parse_status_changed_at(later, "queue", path="t.md", now=NOW) == datetime(
        2099, 5, 31, 12, 0, tzinfo=timezone.utc
    )
    assert is_queue_overdue("queue", 12.0) is False
    assert is_queue_overdue("queue", 12.1) is True
    assert is_queue_overdue("self-review", None) is True
    assert age_hours(None, now=NOW) is None
    assert age_hours(changed, now=NOW) == pytest.approx(18.866666, abs=1e-3)
    with pytest.raises(TypeError) as te:
        age_hours(changed, now=None)  # type: ignore[arg-type]
    assert str(te.value) == "age_hours now must be datetime"
    assert parse_status_changed_at(
        "## Progress\n- 2099-06-01 12:00 UTC: статус → queue\n",
        "queue",
        path="eq.md",
        now=NOW,
    ) == NOW
    with pytest.raises(BoardError) as fut:
        parse_status_changed_at(
            "## Progress\n- 2099-06-02 00:00 UTC: статус → queue\n",
            "queue",
            path="f.md",
            now=NOW,
        )
    assert fut.value.path == "f.md"
    assert fut.value.reason == "future progress stamp 2099-06-02 00:00"
    with pytest.raises(BoardError) as bad:
        parse_status_changed_at(
            "## Progress\n- 2099-99-01 00:00 UTC: статус → queue\n",
            "queue",
            path="b.md",
            now=NOW,
        )
    assert bad.value.path == "b.md"


def test_fail_loud_collect(tmp_path: Path):
    with pytest.raises(BoardError) as e1:
        collect_board_cards(tmp_path / "no", now=NOW)
    assert e1.value.reason == "missing context/tasks directory"
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    empty = tasks / "T-261116-emp.md"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(BoardError) as e2:
        collect_board_cards(tasks, now=NOW)
    assert e2.value.path == str(empty) and e2.value.reason == "empty file"
    empty.unlink()
    bad = tasks / "T-261116-bad.md"
    bad.write_text("# junk\n\nстатус: open\n", encoding="utf-8")
    with pytest.raises(BoardError) as e3:
        collect_board_cards(tasks, now=NOW)
    assert e3.value.path == str(bad)
    bad.unlink()
    mis = tasks / "T-261116-mis.md"
    mis.write_text("# T-261116-zzz — X\n\nстатус: open\n\n## Цель\n\ng\n", encoding="utf-8")
    with pytest.raises(BoardError) as e_mis:
        collect_board_cards(tasks, now=NOW)
    assert e_mis.value.path == str(mis)
    assert e_mis.value.reason == "header id 'T-261116-zzz' != file stem 'T-261116-mis'"
    mis.unlink()
    utf = tasks / "T-261116-utf.md"
    utf.write_bytes(b"# T-261116-utf - X\n\n\xff\xfe\n")
    with pytest.raises(BoardError) as e_utf:
        collect_board_cards(tasks, now=NOW)
    assert e_utf.value.path == str(utf) and "invalid utf-8" in e_utf.value.reason
    utf.unlink()
    seen: dict[str, Path] = {}
    remember_task_id(seen, "T-1", Path("/tmp/a.md"))
    assert seen == {"T-1": Path("/tmp/a.md")}
    with pytest.raises(TypeError):
        remember_task_id(seen, "T-2", None)  # type: ignore[arg-type]
    with pytest.raises(BoardError) as e_dup:
        remember_task_id({"T-1": Path("/tmp/a.md")}, "T-1", Path("/tmp/b.md"))
    assert e_dup.value.path == "/tmp/b.md"
    _write_task(tasks, "T-261116-bod", "B", status="open", body_extra="статус: canceled\n")
    assert collect_board_cards(tasks, now=NOW)[0]["status"] == "open"
    blank = tasks / "T-261116-bs.md"
    blank.write_text("# T-261116-bs — B\n\nстатус:   \n\n## Цель\n\ng\n", encoding="utf-8")
    with pytest.raises(BoardError) as e_bs:
        collect_board_cards(tasks, now=NOW)
    assert e_bs.value.path == str(blank) and e_bs.value.reason == "missing status"
    blank.unlink()
    dupf = tasks / "T-261116-df.md"
    dupf.write_text(
        "# T-261116-df — D\n\nстатус: open\nстатус: queue\n\n## Цель\n\ng\n",
        encoding="utf-8",
    )
    with pytest.raises(BoardError) as e_df:
        collect_board_cards(tasks, now=NOW)
    assert e_df.value.path == str(dupf) and e_df.value.reason == "duplicate field статус"
    dupf.unlink()
    bst = tasks / "T-261116-bst.md"
    bst.write_text(
        "# T-261116-bst — S\n\nстатус: queue\n\n## Progress\n\n"
        "- 2099-99-01 00:00 UTC: статус → queue\n",
        encoding="utf-8",
    )
    with pytest.raises(BoardError) as e_bst:
        collect_board_cards(tasks, now=NOW)
    assert e_bst.value.path == str(bst)
    require_task_header("# T-261116-ok — T\n", Path("x.md"))
    with pytest.raises(TypeError):
        require_task_header("# T-261116-ok — T\n", "x.md")  # type: ignore[arg-type]


def test_render_collect_write(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tmp_path / "merge_policy.json").write_text(
        '{"human_participants":["Maxim"]}\n', encoding="utf-8"
    )
    assert load_human_participants(tmp_path) == ["Maxim"]
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "merge_policy.json").write_text('{"version":1}\n', encoding="utf-8")
    assert load_human_participants(bare) == []
    bad_list = tmp_path / "bl"
    bad_list.mkdir()
    (bad_list / "merge_policy.json").write_text(
        '{"human_participants":"x"}\n', encoding="utf-8"
    )
    with pytest.raises(BoardError) as e_list:
        load_human_participants(bad_list)
    assert e_list.value.reason == "human_participants must be a list"
    assert e_list.value.path == str(bad_list / "merge_policy.json")
    bad_json = tmp_path / "bj"
    bad_json.mkdir()
    (bad_json / "merge_policy.json").write_text("{", encoding="utf-8")
    with pytest.raises(BoardError) as e_json:
        load_human_participants(bad_json)
    assert "invalid merge_policy:" in e_json.value.reason
    bad_utf = tmp_path / "bu"
    bad_utf.mkdir()
    (bad_utf / "merge_policy.json").write_bytes(b"\xff")
    with pytest.raises(BoardError):
        load_human_participants(bad_utf)

    _write_task(tasks, "T-261116-aaa", "Alpha <xss>", goal="увидеть")
    _write_task(
        tasks,
        "T-261116-srv",
        "Self",
        status="self-review",
        progress="- 2099-05-31 12:00 UTC: статус → self-review\n",
    )
    _write_task(
        tasks,
        "T-261116-fresh",
        "Fresh",
        status="queue",
        progress="- 2099-06-01 11:00 UTC: статус → queue\n",
    )
    _write_task(
        tasks,
        "T-261116-real",
        "Real",
        status="self-review",
        progress=(
            "- 2099-05-20 17:08 UTC: task→self-review; push\n"
            "- 2099-06-01 11:50 UTC: note\n"
        ),
    )
    _write_task(
        tasks,
        "T-261116-frv",
        "ForRev",
        status="for-review",
        progress="- 2099-06-01 11:00 UTC: статус → for-review\n",
    )
    _write_task(
        tasks,
        "T-261116-blk",
        "Blocked",
        status="blocked",
        claim="alice",
        extra_fields="blocked_reason: wait\nblocked_deadline: 2026-12-01\n",
    )
    _write_task(tasks, "T-261116-que", "Q", status="queued")
    _write_task(tasks, "T-261116-drp", "D", status="dropped")
    _write_task(tasks, "T-261116-par", "P")
    _write_task(
        tasks, "T-261116-ch", "C", status="in-progress", parent="T-261116-par"
    )

    cards = collect_board_cards(tasks, lang="ru", now=NOW)
    by_id = {c["id"]: c for c in cards}
    assert by_id["T-261116-srv"]["column"] == "queue"
    assert by_id["T-261116-srv"]["overdue"] == "1"
    assert by_id["T-261116-srv"]["updated"] == "2099-05-31 12:00 UTC (24.0ч)"
    assert by_id["T-261116-fresh"]["overdue"] == ""
    assert by_id["T-261116-real"]["overdue"] == "1"
    assert by_id["T-261116-que"]["column"] == "queue"
    assert by_id["T-261116-drp"]["status"] == "canceled"
    assert by_id["T-261116-blk"]["blocked_reason"] == "wait"
    assert by_id["T-261116-blk"]["status_label"] == "заблокирована"
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

    html = generate_board(tasks, lang="ru", now=NOW, title="Моя доска")
    assert "<title>Моя доска</title>" in html and "только Maxim" in html
    assert "В статусе: 2099-05-31 12:00 UTC (24.0ч)" in html
    assert "Исполнитель: alice" in html and "(&gt;12ч)" in html
    assert html.split('data-column="queue"')[1].split("data-column=")[0].count(
        "card overdue"
    ) == 2

    out = tmp_path / "o.html"
    write_board(
        tasks,
        out,
        title="Кастом",
        lang="ru",
        now=NOW,
        generated_at="Z",
        reviewers=["CustomRev"],
    )
    body = out.read_text(encoding="utf-8")
    assert "<title>Кастом</title>" in body and "только CustomRev" in body
    assert "Подзадачи: T-261116-ch" in body and "Сгенерировано: Z" in body
    assert "В статусе: 2099-06-01 11:00 UTC (1.0ч)" in body
    en_out = tmp_path / "en.html"
    write_board(tasks, en_out, title="EN", lang="en", now=NOW, reviewers=["Zed"])
    en = en_out.read_text(encoding="utf-8")
    assert 'lang="en"' in en and "only Zed" in en and "(1.0h)" in en

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
        "updated": "t (12.0ч)",
        "overdue": "",
    }
    rendered = _render_card(card, ["T-261116-c1", "T-261116-c2"], u)
    assert rendered.startswith('<article class="card">')
    assert "Подзадачи: T-261116-c1, T-261116-c2" in rendered
    assert "XX, XX" not in rendered
    od = _render_card(
        {**card, "status": "queue", "status_label": "очередь", "overdue": "1",
         "blocked_reason": "", "blocked_deadline": "", "description": "",
         "claim": "", "parent": ""},
        [],
        u,
    )
    assert od.startswith('<article class="card overdue">')
    assert "Просрочено (&gt;12ч)" in od
    empty = render_board_html([], lang="ru", reviewers=["Maxim"])
    assert empty.count("(пусто)") == 7
    assert empty.startswith(
        "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{DEFAULT_TITLE}</title>\n"
    )
    assert empty.endswith("</main>\n</body>\n</html>\n")
    assert "None" not in empty and "XXXX" not in empty
    assert "<HEAD>" not in empty and "</MAIN>" not in empty
    col = _render_column(
        "for-review", "На ревью", [], {}, u, review_note="только Maxim"
    )
    assert "только Maxim" in col
    assert "col-note" not in _render_column("for-review", "На ревью", [], {}, u)
    assert "XXXX" not in _render_column("for-review", "На ревью", [], {}, u)

    bad_card = {**card, "id": "T-261116-badcol", "column": "not-a-column",
                "blocked_reason": "", "blocked_deadline": "", "claim": "",
                "parent": "", "description": "", "updated": "", "overdue": "",
                "status": "open", "status_label": "открыта"}
    with pytest.raises(BoardError) as exc:
        render_board_html([bad_card], lang="ru")
    assert exc.value.path == "T-261116-badcol"
    no_id = {**bad_card, "id": ""}
    with pytest.raises(BoardError) as exc2:
        render_board_html([no_id], lang="ru")
    assert exc2.value.path == "?"
    assert _subtask_ids(
        [
            {"id": "T-261116-par", "parent": ""},
            {"id": "T-261116-zb", "parent": "T-261116-par"},
            {"id": "T-261116-ya", "parent": "T-261116-par"},
        ]
    ) == {"T-261116-par": ["T-261116-ya", "T-261116-zb"]}


def test_require_status_messages():
    with pytest.raises(BoardError) as e:
        require_status(None, path="/tmp/a.md")
    assert e.value.path == "/tmp/a.md" and e.value.reason == "missing status"
    with pytest.raises(BoardError) as e2:
        require_status("nope", path="/tmp/b.md")
    assert e2.value.path == "/tmp/b.md" and e2.value.reason == "unknown status 'nope'"
