"""Static self-contained board.html from context/tasks/*.md (AGE-37).

Harness-independent kanban. No external assets / network.
Deterministic: same inputs → same bytes unless generated_at is set.

Canonical display statuses match the Dashboard V1 set. Ownership of the
shared status-gate module remains with AGE-22 (`board.py` / status_gates);
this module only renders markdown → HTML.
"""
from __future__ import annotations

import html
import re
from collections import defaultdict
from pathlib import Path

from .tasks import TaskMeta, parse_task

# Canonical statuses for board columns (display). Same set as Dashboard V1.
CANONICAL_STATUSES: tuple[str, ...] = (
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

STATUS_ALIASES: dict[str, str] = {
    "dropped": "canceled",
    "queued": "queue",
}

# idea/open/queue share the Open / Queue column.
COLUMN_FOR_STATUS: dict[str, str] = {
    "idea": "open",
    "open": "open",
    "queue": "open",
    "in-progress": "in-progress",
    "self-review": "self-review",
    "for-review": "for-review",
    "blocked": "blocked",
    "done": "done",
    "canceled": "canceled",
}

BOARD_COLUMNS: tuple[tuple[str, str], ...] = (
    ("open", "Open / Queue"),
    ("in-progress", "In Progress"),
    ("self-review", "Self-Review"),
    ("for-review", "For Review"),
    ("blocked", "Blocked"),
    ("done", "Done"),
    ("canceled", "Canceled"),
)

VALUE_EXTRACT_RE = re.compile(r"(?im)^\s*Ценность:\s*(.+?)\s*$")
FIELD_RE = re.compile(
    r"^(статус|теги|родитель|claim|blocked_reason|blocked_deadline|"
    r"review_note|acceptance_note|pr):\s*(.*)$",
    re.MULTILINE,
)
DEFAULT_TITLE = "Agentized task board"
FALLBACK_COLUMN = "open"
EMPTY_COLUMN_HTML = '<p class="empty">(empty)</p>'
_CSS = (
    ":root{--bg:#0f1419;--col:#1a2332;--card:#243044;--fg:#e7ecf3;"
    "--muted:#9aa7b8;--acc:#5b9fd4}"
    "*{box-sizing:border-box}"
    "body{margin:0;font-family:ui-sans-serif,system-ui,sans-serif;"
    "background:var(--bg);color:var(--fg)}"
    "header{padding:1.25rem 1.5rem;border-bottom:1px solid #2a3548}"
    "header h1{margin:0;font-size:1.35rem;font-weight:650}"
    "header p{margin:.35rem 0 0;color:var(--muted);font-size:.9rem}"
    ".board{display:flex;gap:.75rem;padding:1rem;overflow-x:auto;"
    "align-items:flex-start}"
    ".column{flex:0 0 16rem;background:var(--col);border-radius:8px;"
    "padding:.75rem;min-height:12rem}"
    ".column h2{margin:0 0 .75rem;font-size:.85rem;text-transform:uppercase;"
    "letter-spacing:.04em;color:var(--muted);font-weight:600}"
    ".column .count{color:var(--acc);font-weight:500}"
    ".card{background:var(--card);border-radius:6px;padding:.7rem .75rem;"
    "margin:0 0 .6rem}"
    ".card-title{margin:0 0 .35rem;font-size:.95rem;line-height:1.3}"
    ".card-id,.card-status,.card-claim,.card-value,.card-blocked,"
    ".card-deadline,.card-parent,.card-subtasks{margin:.2rem 0;"
    "font-size:.78rem;color:var(--muted)}"
    ".card-value{color:var(--fg)}"
    ".card-blocked{color:#e8a0a0}"
    ".empty{color:var(--muted);font-size:.8rem;font-style:italic}"
)
BOARD_INTRO = (
    "Harness-independent kanban from context/tasks — static, no network."
)


def escape(text: str | None) -> str:
    """HTML-escape task content for safe embedding."""
    return html.escape(text or "", quote=True)


def normalize_status(raw: str | None) -> str:
    """Map aliases; empty → idea for display columns only."""
    s = (raw or "").strip().lower()
    if not s:
        return "idea"
    return STATUS_ALIASES.get(s, s)


def column_for_status(status: str) -> str:
    """Board column id for a normalized status; unknown → open."""
    return COLUMN_FOR_STATUS.get(status, FALLBACK_COLUMN)


def _plain(val: str | None) -> str:
    v = (val or "").strip()
    if not v or v.startswith("_"):
        return ""
    return v


def extract_value_line(text: str | None) -> str:
    m = VALUE_EXTRACT_RE.search(text or "")
    return m.group(1).strip() if m else ""


def extract_fields(text: str | None) -> dict[str, str]:
    return {k: v.strip() for k, v in FIELD_RE.findall(text or "")}


def _card_data(meta: TaskMeta, text: str) -> dict[str, str]:
    fields = extract_fields(text)
    status = normalize_status(meta.status)
    return {
        "id": meta.task_id,
        "title": meta.title,
        "status": status,
        "value": extract_value_line(text),
        "claim": _plain(meta.claim),
        "parent": _plain(meta.parent),
        "blocked_reason": _plain(fields.get("blocked_reason") or ""),
        "blocked_deadline": _plain(fields.get("blocked_deadline") or ""),
        "column": column_for_status(status),
    }


def collect_board_cards(tasks_dir: Path) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for path in sorted(tasks_dir.glob("T-*.md")):
        meta = parse_task(path)
        if meta is None:
            continue
        text = path.read_text(encoding="utf-8")
        cards.append(_card_data(meta, text))
    return cards


def _subtask_ids(cards: list[dict[str, str]]) -> dict[str, list[str]]:
    by_parent: dict[str, list[str]] = defaultdict(list)
    ids = {c["id"] for c in cards}
    for c in cards:
        parent = c["parent"]
        if parent and parent in ids:
            by_parent[parent].append(c["id"])
    for key in by_parent:
        by_parent[key] = sorted(by_parent[key])
    return by_parent


def _render_card(card: dict[str, str], children: list[str]) -> str:
    parts = [
        '<article class="card">',
        f'<h3 class="card-title">{escape(card["title"])}</h3>',
        f'<p class="card-id">{escape(card["id"])}</p>',
    ]
    if card["value"]:
        parts.append(f'<p class="card-value">{escape(card["value"])}</p>')
    parts.append(f'<p class="card-status">Status: {escape(card["status"])}</p>')
    if card["claim"]:
        parts.append(f'<p class="card-claim">Claim: {escape(card["claim"])}</p>')
    if card["status"] == "blocked":
        if card["blocked_reason"]:
            parts.append(
                f'<p class="card-blocked">Blocked: {escape(card["blocked_reason"])}</p>'
            )
        if card["blocked_deadline"]:
            parts.append(
                f'<p class="card-deadline">Deadline: {escape(card["blocked_deadline"])}</p>'
            )
    if card["parent"]:
        parts.append(f'<p class="card-parent">Parent: {escape(card["parent"])}</p>')
    if children:
        kids = ", ".join(escape(c) for c in children)
        parts.append(f'<p class="card-subtasks">Subtasks: {kids}</p>')
    parts.append("</article>")
    return "\n".join(parts)


def _render_column(
    col_id: str,
    col_label: str,
    items: list[dict[str, str]],
    children_map: dict[str, list[str]],
) -> str:
    if not items:
        body = EMPTY_COLUMN_HTML
    else:
        body = "\n".join(
            _render_card(card, children_map.get(card["id"]) or []) for card in items
        )
    return (
        f'<section class="column" data-column="{escape(col_id)}">\n'
        f'<h2>{escape(col_label)} <span class="count">({len(items)})</span></h2>\n'
        f"{body}\n"
        f"</section>"
    )


def render_board_html(
    cards: list[dict[str, str]],
    *,
    generated_at: str | None = None,
    title: str = DEFAULT_TITLE,
) -> str:
    """Render deterministic board HTML. Pass generated_at only when stamp desired."""
    children_map = _subtask_ids(cards)
    by_col: dict[str, list[dict[str, str]]] = {cid: [] for cid, _ in BOARD_COLUMNS}
    for card in cards:
        raw = card.get("column")
        if raw not in by_col:
            raw = FALLBACK_COLUMN
        by_col[raw].append(card)

    columns_html: list[str] = []
    for col_id, col_label in BOARD_COLUMNS:
        items = sorted(by_col[col_id], key=lambda c: c["id"])
        columns_html.append(_render_column(col_id, col_label, items, children_map))

    stamp = ""
    if generated_at:
        stamp = f'\n<p class="stamp">Generated: {escape(generated_at)}</p>'

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        "<header>\n"
        f"<h1>{escape(title)}</h1>\n"
        f"<p>{BOARD_INTRO}</p>"
        f"{stamp}\n"
        "</header>\n"
        '<main class="board">\n'
        + "\n".join(columns_html)
        + "\n</main>\n"
        "</body>\n"
        "</html>\n"
    )


def generate_board(
    tasks_dir: Path,
    *,
    generated_at: str | None = None,
    title: str = DEFAULT_TITLE,
) -> str:
    cards = collect_board_cards(tasks_dir)
    return render_board_html(cards, generated_at=generated_at, title=title)


def write_board(
    tasks_dir: Path,
    out_path: Path,
    *,
    generated_at: str | None = None,
    title: str = DEFAULT_TITLE,
) -> Path:
    html_text = generate_board(tasks_dir, generated_at=generated_at, title=title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8", newline="\n")
    return out_path
