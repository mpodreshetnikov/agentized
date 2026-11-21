"""Golden asserts for board_html_ui — keep presentation mutants at 100%."""
from __future__ import annotations

from agentized import board_html_ui as ui


def test_defaults_and_for_review_note():
    assert ui.DEFAULT_LANG == "ru"
    assert ui.DEFAULT_TITLE == "Доска задач Agentized"
    assert not hasattr(ui, "EMPTY_COLUMN_HTML")
    assert ui.for_review_note("ru", ["Maxim"]) == "только Maxim"
    assert ui.for_review_note("en", ["Maxim"]) == "only Maxim"
    assert ui.for_review_note("ru", []) == "только рецензент"
    assert ui.for_review_note("en", []) == "only reviewer"
    assert ui.for_review_note("ru", ["Alice", "Bob"]) == "только Alice, Bob"
    assert ui.for_review_note("en", ["Alice", "Bob"]) == "only Alice, Bob"
    assert ui.for_review_note("ru", ["Alice", "  ", "", "Bob"]) == "только Alice, Bob"
    assert ui.for_review_note("en", ["", "Maxim", " "]) == "only Maxim"


def test_ui_ru_en_exact_keys_and_values():
    assert set(ui.UI) == {"ru", "en"}
    assert ui.UI["ru"] == {
        "intro": "Канбан из context/tasks — статический HTML, без сети.",
        "status": "Статус", "claim": "Исполнитель", "blocked": "Блок",
        "deadline": "Дедлайн", "parent": "Родитель", "subtasks": "Подзадачи",
        "age": "В статусе", "overdue": "Просрочено",
        "generated": "Сгенерировано", "empty": "(пусто)",
        "col_open": "Открыто", "col_queue": "Очередь",
        "col_in_progress": "В работе", "col_for_review": "На ревью",
        "col_blocked": "Заблокировано", "col_done": "Готово",
        "col_canceled": "Отменено", "st_idea": "идея", "st_open": "открыта",
        "st_queue": "очередь", "st_in-progress": "в работе",
        "st_self-review": "самопроверка", "st_for-review": "на ревью",
        "st_blocked": "заблокирована", "st_done": "готово",
        "st_canceled": "отменена", "hours_unit": "ч",
    }
    assert ui.UI["en"] == {
        "intro": "Kanban from context/tasks — static HTML, no network.",
        "status": "Status", "claim": "Claim", "blocked": "Blocked",
        "deadline": "Deadline", "parent": "Parent", "subtasks": "Subtasks",
        "age": "In status", "overdue": "Overdue",
        "generated": "Generated", "empty": "(empty)",
        "col_open": "Open", "col_queue": "Queue",
        "col_in_progress": "In Progress", "col_for_review": "For Review",
        "col_blocked": "Blocked", "col_done": "Done",
        "col_canceled": "Canceled", "st_idea": "idea", "st_open": "open",
        "st_queue": "queue", "st_in-progress": "in progress",
        "st_self-review": "self-review", "st_for-review": "for review",
        "st_blocked": "blocked", "st_done": "done",
        "st_canceled": "canceled", "hours_unit": "h",
    }
    assert "updated" not in ui.UI["ru"] and "updated" not in ui.UI["en"]


def test_css_exact_golden():
    assert ui.CSS == ':root{--bg:#0f1419;--col:#1a2332;--card:#243044;--fg:#e7ecf3;--muted:#9aa7b8;--acc:#5b9fd4;--warn:#e8a060;--bad:#e8a0a0}*{box-sizing:border-box}body{margin:0;font-family:ui-sans-serif,system-ui,sans-serif;background:var(--bg);color:var(--fg)}header{padding:1.25rem 1.5rem;border-bottom:1px solid #2a3548}header h1{margin:0;font-size:1.35rem;font-weight:650}header p{margin:.35rem 0 0;color:var(--muted);font-size:.9rem}.board{display:flex;gap:.55rem;padding:1rem;overflow-x:auto;align-items:flex-start}.column{flex:0 0 10rem;background:var(--col);border-radius:8px;padding:.6rem;min-height:12rem}.column h2{margin:0 0 .6rem;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}.column .count{color:var(--acc);font-weight:500}.column .col-note{display:block;font-size:.68rem;font-weight:500;text-transform:none;letter-spacing:0;color:var(--acc);margin-top:.2rem}.card{background:var(--card);border-radius:6px;padding:.55rem .6rem;margin:0 0 .5rem}.card.overdue{outline:1px solid var(--warn)}.card-title{margin:0 0 .3rem;font-size:.88rem;line-height:1.3}.card-id,.card-status,.card-claim,.card-desc,.card-blocked,.card-deadline,.card-parent,.card-subtasks,.card-age{margin:.15rem 0;font-size:.72rem;color:var(--muted)}.card-desc{color:var(--fg)}.card-blocked,.card-overdue{color:var(--bad)}.empty{color:var(--muted);font-size:.75rem;font-style:italic}'
    assert "flex:0 0 10rem" in ui.CSS
    assert "flex:0 0 16rem" not in ui.CSS
    assert ".card.overdue" in ui.CSS
