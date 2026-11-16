"""Static board.html generator — columns, escaping, determinism (AGE-37)."""
from __future__ import annotations

from pathlib import Path

from agentized.board_html import (
    BOARD_COLUMNS,
    BOARD_INTRO,
    CANONICAL_STATUSES,
    COLUMN_FOR_STATUS,
    DEFAULT_TITLE,
    EMPTY_COLUMN_HTML,
    FALLBACK_COLUMN,
    JOIN_NL,
    STATUS_ALIASES,
    _CSS,
    _card_data,
    _plain,
    _render_card,
    _render_column,
    _subtask_ids,
    collect_board_cards,
    column_for_status,
    escape,
    extract_fields,
    extract_value_line,
    generate_board,
    normalize_status,
    render_board_html,
    write_board,
)
from agentized.board_html_io import ENCODING, read_task_text, write_html
from agentized.tasks import TaskMeta

# Exact skeleton fragments — kills HTML case / XX-wrap / join mutants.
_REQUIRED_FRAGMENTS = (
    "<!DOCTYPE html>\n",
    '<html lang="en">\n',
    "<head>\n",
    '<meta charset="utf-8">\n',
    "</head>\n",
    "<body>\n",
    "<header>\n",
    "</header>\n",
    '<main class="board">\n',
    "\n</main>\n",
    "</body>\n",
    "</html>\n",
)


def _write_task(
    tasks: Path,
    task_id: str,
    title: str,
    *,
    status: str = "open",
    value: str = "plain value",
    parent: str = "",
    claim: str = "",
    extra_fields: str = "",
) -> None:
    parent_line = f"родитель: {parent}" if parent else "родитель: _(пусто)_"
    claim_line = f"claim: {claim}" if claim else "claim: _(пусто)_"
    extra = (extra_fields.strip() + "\n") if extra_fields.strip() else ""
    text = (
        f"# {task_id} — {title}\n\n"
        f"статус: {status}\n"
        f"теги: _(нет)_\n"
        f"{parent_line}\n"
        f"{claim_line}\n"
        f"{extra}\n"
        f"Ценность: {value}\n\n"
        f"## Цель\n\ngoal\n"
    )
    (tasks / f"{task_id}.md").write_text(text, encoding="utf-8")


def test_canonical_status_set_and_columns():
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
    assert COLUMN_FOR_STATUS["idea"] == "open"
    assert COLUMN_FOR_STATUS["queue"] == "open"
    assert COLUMN_FOR_STATUS["canceled"] == "canceled"
    assert BOARD_COLUMNS == (
        ("open", "Open / Queue"),
        ("in-progress", "In Progress"),
        ("self-review", "Self-Review"),
        ("for-review", "For Review"),
        ("blocked", "Blocked"),
        ("done", "Done"),
        ("canceled", "Canceled"),
    )
    assert FALLBACK_COLUMN == "open"
    assert DEFAULT_TITLE == "Agentized task board"
    assert EMPTY_COLUMN_HTML == '<p class="empty">(empty)</p>'
    assert JOIN_NL == "\n"
    assert "static, no network" in BOARD_INTRO
    assert _CSS.startswith(":root{--bg:#0f1419;")
    assert ".card-blocked{color:#e8a0a0}" in _CSS


def test_normalize_and_column_helpers():
    assert normalize_status(None) == "idea"
    assert normalize_status("") == "idea"
    assert normalize_status("  ") == "idea"
    assert normalize_status("OPEN") == "open"
    assert normalize_status("queued") == "queue"
    assert normalize_status("dropped") == "canceled"
    assert normalize_status("self-review") == "self-review"
    assert column_for_status("queue") == "open"
    assert column_for_status("flying") == FALLBACK_COLUMN
    assert column_for_status("in-progress") == "in-progress"


def test_escape_and_plain():
    assert escape("<script>") == "&lt;script&gt;"
    assert escape('say "hi"') == "say &quot;hi&quot;"
    assert escape("'x'") == "&#x27;x&#x27;"
    assert escape("") == ""
    assert escape(None) == ""
    assert _plain("") == ""
    assert _plain("_(пусто)_") == ""
    assert _plain("  alice  ") == "alice"
    assert _plain(None) == ""
    assert _plain("_hidden") == ""


def test_extract_value_and_fields():
    text = "статус: open\nclaim: bob\n\nЦенность: see people\n"
    assert extract_value_line(text) == "see people"
    assert extract_value_line("") == ""
    assert extract_value_line(None) == ""
    assert extract_value_line("no value here") == ""
    assert extract_fields(text) == {"статус": "open", "claim": "bob"}
    assert extract_fields("") == {}
    assert extract_fields(None) == {}
    assert extract_fields("blocked_reason: wait\nblocked_deadline: 2026-12-01\n") == {
        "blocked_reason": "wait",
        "blocked_deadline": "2026-12-01",
    }


def test_columns_and_cards(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _write_task(tasks, "T-261116-aaa", "Alpha <xss>", status="open", value="see board")
    _write_task(
        tasks,
        "T-261116-bbb",
        "Blocked one",
        status="blocked",
        claim="alice",
        extra_fields="blocked_reason: wait on API\nblocked_deadline: 2026-12-01\n",
    )
    _write_task(
        tasks,
        "T-261116-ccc",
        "Child",
        status="in-progress",
        parent="T-261116-aaa",
        claim="bob",
    )
    cards = collect_board_cards(tasks)
    by_id = {c["id"]: c for c in cards}
    assert len(cards) == 3
    assert by_id["T-261116-aaa"]["title"] == "Alpha <xss>"
    assert by_id["T-261116-aaa"]["value"] == "see board"
    assert by_id["T-261116-aaa"]["column"] == "open"
    assert by_id["T-261116-aaa"]["blocked_reason"] == ""
    assert by_id["T-261116-aaa"]["blocked_deadline"] == ""
    assert by_id["T-261116-bbb"]["status"] == "blocked"
    assert by_id["T-261116-bbb"]["claim"] == "alice"
    assert by_id["T-261116-bbb"]["blocked_reason"] == "wait on API"
    assert by_id["T-261116-bbb"]["blocked_deadline"] == "2026-12-01"
    assert by_id["T-261116-ccc"]["parent"] == "T-261116-aaa"
    assert by_id["T-261116-ccc"]["column"] == "in-progress"

    html = generate_board(tasks)
    for frag in _REQUIRED_FRAGMENTS:
        assert frag in html
    assert "XX" not in html
    assert "None" not in html
    assert "<HEAD>" not in html
    assert "<BODY>" not in html
    assert "<HEADER>" not in html
    assert "<MAIN" not in html
    assert f"<style>{_CSS}</style>" in html
    assert f"<p>{BOARD_INTRO}</p>" in html
    col_markers = [f'data-column="{col_id}"' for col_id, _ in BOARD_COLUMNS]
    assert [html.find(m) for m in col_markers] == sorted(html.find(m) for m in col_markers)
    assert all(html.find(m) != -1 for m in col_markers)
    assert html.count("Alpha &lt;xss&gt;") == 1
    assert html.count('<p class="card-id">T-261116-aaa</p>') == 1
    assert html.count('<p class="card-value">see board</p>') == 1
    assert html.find("<script>") == -1
    assert html.count("Claim: alice") == 1
    assert html.count("Parent: T-261116-aaa") == 1
    assert html.count("Subtasks: T-261116-ccc") == 1
    assert html.count("wait on API") == 1
    assert html.count("2026-12-01") == 1
    assert html.count('data-column="open"') == 1
    assert html.count("Open / Queue") == 1
    assert html.count("(1)") >= 3


def test_subtask_ids_sorted_and_orphan_parent():
    cards = [
        {
            "id": "T-261116-par",
            "title": "P",
            "status": "open",
            "value": "v",
            "claim": "",
            "parent": "",
            "blocked_reason": "",
            "blocked_deadline": "",
            "column": "open",
        },
        {
            "id": "T-261116-zb",
            "title": "B",
            "status": "open",
            "value": "v",
            "claim": "",
            "parent": "T-261116-par",
            "blocked_reason": "",
            "blocked_deadline": "",
            "column": "open",
        },
        {
            "id": "T-261116-ya",
            "title": "A",
            "status": "open",
            "value": "v",
            "claim": "",
            "parent": "T-261116-par",
            "blocked_reason": "",
            "blocked_deadline": "",
            "column": "open",
        },
        {
            "id": "T-261116-or",
            "title": "Orphan",
            "status": "open",
            "value": "v",
            "claim": "",
            "parent": "T-missing-parent",
            "blocked_reason": "",
            "blocked_deadline": "",
            "column": "open",
        },
    ]
    kids = _subtask_ids(cards)
    assert kids == {"T-261116-par": ["T-261116-ya", "T-261116-zb"]}
    html = render_board_html(cards)
    assert html.count("Subtasks: T-261116-ya, T-261116-zb") == 1
    assert html.count("Parent: T-missing-parent") == 1


def test_determinism_without_stamp(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _write_task(tasks, "T-261116-zzz", "Z", value="v")
    a = generate_board(tasks)
    b = generate_board(tasks)
    assert a == b
    assert a.count(f"<title>{DEFAULT_TITLE}</title>") == 1
    assert a.count(f"<h1>{DEFAULT_TITLE}</h1>") == 1
    assert a.count("Generated:") == 0
    assert "XXXX" not in a
    assert "None" not in a
    stamped = generate_board(tasks, generated_at="2026-11-16T00:00:00Z")
    assert stamped.count("Generated: 2026-11-16T00:00:00Z") == 1
    assert a != stamped
    titled = generate_board(tasks, title="Custom Board")
    assert titled.count("<title>Custom Board</title>") == 1
    assert titled.count("<h1>Custom Board</h1>") == 1
    # stamp escapes HTML
    stamped_xss = generate_board(tasks, generated_at='<img src=x onerror=alert(1)>')
    assert stamped_xss.count("&lt;img src=x onerror=alert(1)&gt;") == 1
    assert stamped_xss.find("<img src=x") == -1


def test_write_board_and_collect(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _write_task(tasks, "T-261116-ddd", "D", status="queue", value="q")
    out = tmp_path / "a" / "b" / "c" / "board.html"
    written = write_board(
        tasks,
        out,
        generated_at="2026-11-16T12:00:00Z",
        title="Write Title",
    )
    assert written == out
    assert out.is_file()
    body = out.read_text(encoding="utf-8")
    assert body.startswith("<!DOCTYPE html>\n")
    assert body.count("<title>Write Title</title>") == 1
    assert body.count("Generated: 2026-11-16T12:00:00Z") == 1
    write_board(tasks, out, title="Write Title 2")
    body2 = out.read_text(encoding="utf-8")
    assert body2.count("<title>Write Title 2</title>") == 1
    cards = collect_board_cards(tasks)
    assert len(cards) == 1
    assert cards[0]["column"] == "open"
    assert cards[0]["status"] == "queue"
    empty = render_board_html([])
    assert empty.count(EMPTY_COLUMN_HTML) == len(BOARD_COLUMNS)
    assert empty.count(f"<title>{DEFAULT_TITLE}</title>") == 1
    # alias queued → queue → open column
    _write_task(tasks, "T-261116-que", "Q", status="queued", value="q2")
    cards2 = collect_board_cards(tasks)
    by_id = {c["id"]: c for c in cards2}
    assert by_id["T-261116-que"]["status"] == "queue"
    assert by_id["T-261116-que"]["column"] == "open"


def test_board_skips_unparseable_and_unknown_column(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T-0000xx-bad.md").write_text("# junk\n", encoding="utf-8")
    _write_task(tasks, "T-261116-eee", "E", status="open", value="v")
    cards = collect_board_cards(tasks)
    assert len(cards) == 1
    assert cards[0]["id"] == "T-261116-eee"
    weird = dict(cards[0])
    weird["column"] = "not-a-column"
    html = render_board_html([weird])
    open_section = html.split('data-column="open"')[1].split("data-column=")[0]
    assert open_section.count(">E</h3>") == 1
    bare = {
        "id": "T-261116-fff",
        "title": "Bare",
        "status": "open",
        "value": "",
        "claim": "",
        "parent": "",
        "blocked_reason": "",
        "blocked_deadline": "",
        "column": "open",
    }
    html2 = render_board_html([bare])
    assert html2.count(">Bare</h3>") == 1
    assert html2.find("Claim:") == -1
    assert html2.find('class="card-value"') == -1
    blocked = dict(bare)
    blocked["status"] = "blocked"
    blocked["id"] = "T-261116-blk"
    html3 = render_board_html([blocked])
    assert html3.count("Status: blocked") == 1
    assert html3.find("Blocked:") == -1
    assert html3.find("Deadline:") == -1
    no_col = dict(bare)
    no_col.pop("column")
    no_col["id"] = "T-261116-ncol"
    no_col["title"] = "NoCol"
    html4 = render_board_html([no_col])
    open_sec = html4.split('data-column="open"')[1].split("data-column=")[0]
    assert open_sec.count(">NoCol</h3>") == 1


def test_idea_self_review_for_review_done_canceled(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _write_task(tasks, "T-261116-ide", "Idea", status="idea", value="v")
    _write_task(
        tasks,
        "T-261116-srv",
        "Review",
        status="self-review",
        value="v",
        extra_fields="review_note: checklist\n",
    )
    _write_task(
        tasks,
        "T-261116-frv",
        "ForRev",
        status="for-review",
        value="v",
        extra_fields="pr: https://example.com/pr/1\n",
    )
    _write_task(tasks, "T-261116-don", "Done", status="done", value="v")
    _write_task(tasks, "T-261116-can", "Can", status="canceled", value="v")
    _write_task(tasks, "T-261116-drp", "Drop", status="dropped", value="v")
    cards = collect_board_cards(tasks)
    by_id = {c["id"]: c for c in cards}
    assert by_id["T-261116-ide"]["column"] == "open"
    assert by_id["T-261116-ide"]["status"] == "idea"
    assert by_id["T-261116-srv"]["column"] == "self-review"
    assert by_id["T-261116-frv"]["column"] == "for-review"
    assert by_id["T-261116-don"]["column"] == "done"
    assert by_id["T-261116-can"]["column"] == "canceled"
    assert by_id["T-261116-drp"]["status"] == "canceled"
    assert by_id["T-261116-drp"]["column"] == "canceled"
    html = generate_board(tasks)
    assert html.count('data-column="self-review"') == 1
    self_sec = html.split('data-column="self-review"')[1].split("data-column=")[0]
    assert self_sec.count(">Review</h3>") == 1
    for_sec = html.split('data-column="for-review"')[1].split("data-column=")[0]
    assert for_sec.count(">ForRev</h3>") == 1
    done_sec = html.split('data-column="done"')[1].split("data-column=")[0]
    assert done_sec.count(">Done</h3>") == 1
    can_sec = html.split('data-column="canceled"')[1].split("data-column=")[0]
    assert can_sec.count(">Can</h3>") == 1
    assert can_sec.count(">Drop</h3>") == 1


def test_card_data_unknown_status_column():
    meta = TaskMeta(
        path=Path("T-261116-unk.md"),
        task_id="T-261116-unk",
        title="Unk",
        status="flying",
        tags="",
        parent="",
        claim="",
    )
    card = _card_data(meta, "# T-261116-unk — Unk\n\nстатус: flying\n\nЦенность: v\n")
    assert card["status"] == "flying"
    assert card["column"] == "open"
    assert card["value"] == "v"


def test_render_card_and_column_helpers():
    card = {
        "id": "T-261116-x1",
        "title": "X",
        "status": "blocked",
        "value": "val",
        "claim": "c",
        "parent": "T-261116-p",
        "blocked_reason": "why",
        "blocked_deadline": "2026-01-01",
        "column": "blocked",
    }
    rendered = _render_card(card, ["T-261116-c1", "T-261116-c2"])
    expected_card = JOIN_NL.join(
        [
            '<article class="card">',
            '<h3 class="card-title">X</h3>',
            '<p class="card-id">T-261116-x1</p>',
            '<p class="card-value">val</p>',
            '<p class="card-status">Status: blocked</p>',
            '<p class="card-claim">Claim: c</p>',
            '<p class="card-blocked">Blocked: why</p>',
            '<p class="card-deadline">Deadline: 2026-01-01</p>',
            '<p class="card-parent">Parent: T-261116-p</p>',
            '<p class="card-subtasks">Subtasks: T-261116-c1, T-261116-c2</p>',
            "</article>",
        ]
    )
    assert rendered == expected_card
    assert "XX" not in rendered
    col = _render_column("blocked", "Blocked", [card], {"T-261116-x1": []})
    assert 'data-column="blocked"' in col
    assert "<h2>Blocked <span class=\"count\">(1)</span></h2>" in col
    assert "XX" not in col
    empty_col = _render_column("done", "Done", [], {})
    assert EMPTY_COLUMN_HTML in empty_col
    assert '<span class="count">(0)</span>' in empty_col
    # two cards → JOIN_NL between articles (not XX\\nXX)
    card_a = {
        "id": "T-261116-a1",
        "title": "A",
        "status": "open",
        "value": "",
        "claim": "",
        "parent": "",
        "blocked_reason": "",
        "blocked_deadline": "",
        "column": "open",
    }
    card_b = dict(card_a)
    card_b["id"] = "T-261116-b1"
    card_b["title"] = "B"
    two = _render_column("open", "Open / Queue", [card_a, card_b], {})
    piece_a = _render_card(card_a, [])
    piece_b = _render_card(card_b, [])
    assert two.count(piece_a) == 1
    assert two.count(piece_b) == 1
    assert JOIN_NL.join([piece_a, piece_b]) in two
    assert "XX" not in two


def test_empty_board_exact_skeleton():
    html = render_board_html([])
    for frag in _REQUIRED_FRAGMENTS:
        assert frag in html
    assert html.count(EMPTY_COLUMN_HTML) == len(BOARD_COLUMNS)
    assert "XX" not in html
    assert "None" not in html
    assert "XXXX" not in html
    assert "<HEAD>" not in html
    assert "</HEAD>" not in html
    assert "<BODY>" not in html
    assert "</BODY>" not in html
    assert "<HEADER>" not in html
    assert "</HEADER>" not in html
    assert "<MAIN CLASS=" not in html
    assert "</MAIN>" not in html
    assert "</HTML>" not in html
    assert "Open / Queue" in html
    assert "In Progress" in html
    assert "Self-Review" in html
    assert "For Review" in html
    assert "Blocked" in html
    assert "Done" in html
    assert "Canceled" in html


def test_board_html_io_roundtrip(tmp_path: Path):
    assert ENCODING == "utf-8"
    deep = tmp_path / "a" / "b" / "c" / "out.html"
    payload = "<!DOCTYPE html>\n<html>Ценность: café — 日本語</html>\n"
    write_html(deep, payload)
    assert deep.is_file()
    raw = deep.read_bytes()
    assert raw == payload.encode("utf-8")
    assert b"\r" not in raw
    assert read_task_text(deep) == payload
    # exist_ok=True: rewrite same path
    write_html(deep, payload + "<!--2-->\n")
    assert read_task_text(deep).endswith("<!--2-->\n")
    # non-utf8 bytes → decode via ENCODING fails closed
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe not utf-8")
    try:
        read_task_text(bad)
        raised = False
    except UnicodeDecodeError:
        raised = True
    assert raised is True
