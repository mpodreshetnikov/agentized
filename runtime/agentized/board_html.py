"""Static self-contained board.html from context/tasks/*.md (AGE-37).

Renderer only — CLI `agentized board` writes HTML. Autopilot/metrics are
`agentized autopilot` (AGE-30/#19). Status gates → AGE-22; status_guard → AGE-38.

Fail-loud on bad task files. Deterministic HTML unless generated_at is set.
"""
from __future__ import annotations

import html
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .board_html_io import read_task_text, write_html
from .board_html_ui import (
    CSS as _CSS,
    DEFAULT_LANG,
    DEFAULT_TITLE,
    EMPTY_COLUMN_HTML,
    FOR_REVIEW_NOTE,
    UI,
)
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

# Self-review sits in Queue (Maxim). idea/open share Open.
COLUMN_FOR_STATUS: dict[str, str] = {
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

OVERDUE_HOURS = 12
JOIN_NL = "\n"

HEADER_RE = re.compile(
    r"^#\s+(T-\d{6}-[a-z0-9]+)\s*[—\-–]\s*(.+)$",
)
VALUE_EXTRACT_RE = re.compile(r"(?im)^[ \t]*Ценность:[ \t]*(.+?)[ \t]*$")
GOAL_RE = re.compile(
    r"(?ims)^##\s*Цель\s*\n+(.*?)(?=^##\s|\Z)",
)
# [ \t]* — not \s* — so blank `статус:` does not swallow the next line.
FIELD_RE = re.compile(
    r"^(статус|теги|родитель|claim|blocked_reason|blocked_deadline|"
    r"review_note|acceptance_note|pr):[ \t]*(.*)$",
    re.MULTILINE,
)
PROGRESS_STAMP_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC:.*"
    r"(?:статус|status)\s*→\s*([^\s,;]+)",
    re.MULTILINE | re.IGNORECASE,
)
PROGRESS_ANY_STAMP_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC:",
    re.MULTILINE,
)

# Re-export presentation constants for tests / CLI docs.
__all__ = (
    "BoardError",
    "CANONICAL_STATUSES",
    "COLUMN_FOR_STATUS",
    "DEFAULT_LANG",
    "DEFAULT_TITLE",
    "EMPTY_COLUMN_HTML",
    "FOR_REVIEW_NOTE",
    "JOIN_NL",
    "OVERDUE_HOURS",
    "STATUS_ALIASES",
    "UI",
    "_CSS",
    "age_hours",
    "board_columns",
    "collect_board_cards",
    "column_for_status",
    "escape",
    "extract_description",
    "extract_fields",
    "extract_goal_blurb",
    "extract_value_line",
    "generate_board",
    "human_status",
    "is_queue_overdue",
    "normalize_status",
    "parse_status_changed_at",
    "render_board_html",
    "require_status",
    "require_task_header",
    "ui_for",
    "write_board",
)


@dataclass(frozen=True)
class BoardError(Exception):
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


def ui_for(lang: str) -> dict[str, str]:
    key = (lang or DEFAULT_LANG).strip().lower()
    if key not in UI:
        raise BoardError("<lang>", f"unknown lang {lang!r}; expected ru|en")
    return UI[key]


def board_columns(lang: str = DEFAULT_LANG) -> tuple[tuple[str, str], ...]:
    u = ui_for(lang)
    return (
        ("open", u["col_open"]),
        ("queue", u["col_queue"]),
        ("in-progress", u["col_in_progress"]),
        ("for-review", u["col_for_review"]),
        ("blocked", u["col_blocked"]),
        ("done", u["col_done"]),
        ("canceled", u["col_canceled"]),
    )


def escape(text: str | None) -> str:
    return html.escape("" if text is None else text)


def normalize_status(raw: str | None) -> str:
    """Map aliases only; empty stays empty (caller refuses)."""
    s = ("" if raw is None else raw).strip().lower()
    if not s:
        return ""
    return STATUS_ALIASES.get(s, s)


def require_status(raw: str | None, *, path: str) -> str:
    st = normalize_status(raw)
    if not st:
        raise BoardError(path, "missing status")
    if st not in CANONICAL_STATUSES:
        raise BoardError(path, f"unknown status {raw!r}")
    return st


def column_for_status(status: str) -> str:
    return COLUMN_FOR_STATUS[status]


def human_status(status: str, lang: str = DEFAULT_LANG) -> str:
    u = ui_for(lang)
    return u.get(f"st_{status}", status)


def _plain(val: str | None) -> str:
    v = ("" if val is None else val).strip()
    if not v or v.startswith("_"):
        return ""
    return v


def extract_value_line(text: str | None) -> str:
    if text is None:
        return ""
    m = VALUE_EXTRACT_RE.search(text)
    return m.group(1).strip() if m else ""


def extract_goal_blurb(text: str | None) -> str:
    """Short plain description from ## Цель (first non-empty line)."""
    if text is None:
        return ""
    m = GOAL_RE.search(text)
    if not m:
        return ""
    for line in m.group(1).splitlines():
        s = line.strip()
        if not s or s.startswith("_"):
            continue
        return s
    return ""


def extract_description(text: str | None) -> str:
    """Prefer Цель blurb; fall back to Ценность."""
    goal = extract_goal_blurb(text)
    if goal:
        return goal
    return extract_value_line(text)


def extract_fields(text: str | None) -> dict[str, str]:
    if text is None:
        return {}
    return {k: v.strip() for k, v in FIELD_RE.findall(text)}


def parse_status_changed_at(text: str) -> datetime | None:
    """Last Progress stamp that mentions status → …; else last Progress stamp."""
    matches = list(PROGRESS_STAMP_RE.finditer(text))
    if matches:
        stamp = matches[-1].group(1)
    else:
        any_m = list(PROGRESS_ANY_STAMP_RE.finditer(text))
        if not any_m:
            return None
        stamp = any_m[-1].group(1)
    return datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def age_hours(since: datetime | None, *, now: datetime) -> float | None:
    """Age in hours. Caller supplies ``now`` (resolve wall-clock upstream)."""
    if since is None:
        return None
    return (now - since).total_seconds() / 3600.0


def is_queue_overdue(status: str, hours: float | None) -> bool:
    """Queue + self-review actionable overdue after OVERDUE_HOURS."""
    if status not in {"queue", "self-review"}:
        return False
    if hours is None:
        return True
    return hours > OVERDUE_HOURS


def require_task_header(text: str, path: Path) -> re.Match[str]:
    """Validate header; return match with task id + title groups."""
    if not isinstance(path, Path):
        raise TypeError("require_task_header path must be pathlib.Path")
    if not text.strip():
        raise BoardError(str(path), "empty file")
    first = text.splitlines()[0].strip()
    matched = HEADER_RE.match(first)
    if not matched:
        raise BoardError(str(path), "unparseable or missing # T-… — title header")
    return matched


def _card_data(
    task_id: str,
    title: str,
    text: str,
    *,
    path: Path,
    lang: str,
    now: datetime,
) -> dict[str, str]:
    fields = extract_fields(text)
    status = require_status(fields.get("статус"), path=str(path))
    changed = parse_status_changed_at(text)
    hours = age_hours(changed, now=now)
    overdue = is_queue_overdue(status, hours)
    age_label = ""
    if changed is not None:
        age_label = changed.strftime("%Y-%m-%d %H:%M UTC")
        if hours is not None:
            age_label = f"{age_label} ({hours:.1f}h)"
    return {
        "id": task_id,
        "title": title,
        "status": status,
        "status_label": human_status(status, lang),
        "description": extract_description(text),
        "claim": _plain(fields.get("claim")),
        "parent": _plain(fields.get("родитель")),
        "blocked_reason": _plain(fields.get("blocked_reason")),
        "blocked_deadline": _plain(fields.get("blocked_deadline")),
        "column": column_for_status(status),
        "updated": age_label,
        "overdue": "1" if overdue else "",
    }


def collect_board_cards(
    tasks_dir: Path,
    *,
    lang: str = DEFAULT_LANG,
    now: datetime,
) -> list[dict[str, str]]:
    if not tasks_dir.is_dir():
        raise BoardError(str(tasks_dir), "missing context/tasks directory")
    cards: list[dict[str, str]] = []
    paths = sorted(tasks_dir.glob("T-*.md"))
    for path in paths:
        text = read_task_text(path)
        matched = require_task_header(text, path)
        cards.append(
            _card_data(
                matched.group(1),
                matched.group(2).strip(),
                text,
                path=path,
                lang=lang,
                now=now,
            )
        )
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


def _render_card(card: dict[str, str], children: list[str], u: dict[str, str]) -> str:
    overdue_cls = " overdue" if card.get("overdue") else ""
    parts = [
        f'<article class="card{overdue_cls}">',
        f'<h3 class="card-title">{escape(card["title"])}</h3>',
        f'<p class="card-id">{escape(card["id"])}</p>',
    ]
    if card.get("description"):
        parts.append(f'<p class="card-desc">{escape(card["description"])}</p>')
    parts.append(
        f'<p class="card-status">{escape(u["status"])}: '
        f'{escape(card["status_label"])}</p>'
    )
    if card.get("updated"):
        parts.append(
            f'<p class="card-age">{escape(u["updated"])}: {escape(card["updated"])}</p>'
        )
    if card.get("overdue"):
        parts.append(
            f'<p class="card-overdue">{escape(u["overdue"])} '
            f"(&gt;{OVERDUE_HOURS}h)</p>"
        )
    if card.get("claim"):
        parts.append(
            f'<p class="card-claim">{escape(u["claim"])}: {escape(card["claim"])}</p>'
        )
    if card["status"] == "blocked":
        if card.get("blocked_reason"):
            parts.append(
                f'<p class="card-blocked">{escape(u["blocked"])}: '
                f'{escape(card["blocked_reason"])}</p>'
            )
        if card.get("blocked_deadline"):
            parts.append(
                f'<p class="card-deadline">{escape(u["deadline"])}: '
                f'{escape(card["blocked_deadline"])}</p>'
            )
    if card.get("parent"):
        parts.append(
            f'<p class="card-parent">{escape(u["parent"])}: {escape(card["parent"])}</p>'
        )
    if children:
        kids = ", ".join(escape(c) for c in children)
        parts.append(f'<p class="card-subtasks">{escape(u["subtasks"])}: {kids}</p>')
    parts.append("</article>")
    return JOIN_NL.join(parts)


def _render_column(
    col_id: str,
    col_label: str,
    items: list[dict[str, str]],
    children_map: dict[str, list[str]],
    u: dict[str, str],
) -> str:
    empty_html = f'<p class="empty">{escape(u["empty"])}</p>'
    if not items:
        body = empty_html
    else:
        body = JOIN_NL.join(
            _render_card(card, children_map.get(card["id"]) or [], u) for card in items
        )
    note = ""
    if col_id == "for-review":
        note = f'\n<span class="col-note">{escape(u["for_review_note"])}</span>'
    return (
        f'<section class="column" data-column="{escape(col_id)}">\n'
        f'<h2>{escape(col_label)} <span class="count">({len(items)})</span>'
        f"{note}</h2>\n"
        f"{body}\n"
        f"</section>"
    )


def render_board_html(
    cards: list[dict[str, str]],
    *,
    generated_at: str | None = None,
    title: str = DEFAULT_TITLE,
    lang: str = DEFAULT_LANG,
) -> str:
    u = ui_for(lang)
    columns = board_columns(lang)
    children_map = _subtask_ids(cards)
    by_col: dict[str, list[dict[str, str]]] = {cid: [] for cid, _ in columns}
    for card in cards:
        raw = card.get("column")
        if raw not in by_col:
            raise BoardError(card.get("id") or "?", f"unknown column {raw!r}")
        by_col[raw].append(card)

    columns_html: list[str] = []
    for col_id, col_label in columns:
        items = sorted(by_col[col_id], key=lambda c: c["id"])
        columns_html.append(_render_column(col_id, col_label, items, children_map, u))

    if generated_at:
        stamp = (
            f'\n<p class="stamp">{escape(u["generated"])}: '
            f"{escape(generated_at)}</p>"
        )
    else:
        stamp = ""

    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{escape(lang)}">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        "<header>\n"
        f"<h1>{escape(title)}</h1>\n"
        f"<p>{escape(u['intro'])}</p>"
        f"{stamp}\n"
        "</header>\n"
        '<main class="board">\n'
        + JOIN_NL.join(columns_html)
        + "\n</main>\n"
        "</body>\n"
        "</html>\n"
    )


def generate_board(
    tasks_dir: Path,
    *,
    generated_at: str | None = None,
    title: str = DEFAULT_TITLE,
    lang: str = DEFAULT_LANG,
    now: datetime,
) -> str:
    cards = collect_board_cards(tasks_dir, lang=lang, now=now)
    return render_board_html(
        cards, generated_at=generated_at, title=title, lang=lang
    )


def write_board(
    tasks_dir: Path,
    out_path: Path,
    *,
    generated_at: str | None = None,
    title: str = DEFAULT_TITLE,
    lang: str = DEFAULT_LANG,
    now: datetime,
) -> Path:
    html_text = generate_board(
        tasks_dir,
        generated_at=generated_at,
        title=title,
        lang=lang,
        now=now,
    )
    write_html(out_path, html_text)
    return out_path
