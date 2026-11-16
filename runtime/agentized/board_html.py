"""Static self-contained board.html from context/tasks/*.md (AGE-37).

Renderer only — CLI `agentized board` writes HTML. Autopilot/metrics are
`agentized autopilot` (AGE-30/#19). Status gates → AGE-22; status_guard → AGE-38.

Fail-loud on bad task files. Deterministic HTML unless generated_at is set.
"""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .board_html_io import ENCODING, read_task_text, write_html
from .board_html_ui import (
    CSS as _CSS,
    DEFAULT_LANG,
    DEFAULT_TITLE,
    EMPTY_COLUMN_HTML,
    UI,
    for_review_note,
)
from .status_gates import (
    CANONICAL_STATUSES,
    COLUMN_FOR_STATUS,
    STATUS_ALIASES,
    normalize_status,
)

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
# Optional статус|status|task before →; captures destination status.
PROGRESS_ARROW_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC:.*"
    r"(?:(?:статус|status|task)\s*)?→\s*([^\s,;]+)",
    re.MULTILINE | re.IGNORECASE,
)
PROGRESS_ANY_STAMP_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC:",
    re.MULTILINE,
)

__all__ = (
    "BoardError",
    "CANONICAL_STATUSES",
    "COLUMN_FOR_STATUS",
    "DEFAULT_LANG",
    "DEFAULT_TITLE",
    "EMPTY_COLUMN_HTML",
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
    "for_review_note",
    "generate_board",
    "header_block",
    "human_status",
    "is_queue_overdue",
    "load_human_participants",
    "normalize_status",  # re-export status_gates
    "parse_status_changed_at",
    "remember_task_id",
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
    """Seven board columns; ids align with status_gates.COLUMN_FOR_STATUS values."""
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


def header_block(text: str) -> str:
    """Fields live only before the first markdown ``##`` section."""
    if text.startswith("##"):
        return ""
    idx = text.find("\n##")
    if idx == -1:
        return text
    return text[:idx]


def extract_fields(text: str | None, *, path: str = "<text>") -> dict[str, str]:
    if text is None:
        return {}
    header = header_block(text)
    out: dict[str, str] = {}
    for m in FIELD_RE.finditer(header):
        key = m.group(1)
        if key in out:
            raise BoardError(path, f"duplicate field {key}")
        out[key] = m.group(2).strip()
    return out


def _parse_stamp(stamp_s: str, *, path: str, now: datetime) -> datetime:
    try:
        stamp = datetime.strptime(stamp_s, "%Y-%m-%d %H:%M").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise BoardError(path, f"bad progress stamp {stamp_s!r}") from None
    if stamp > now:
        raise BoardError(path, f"future progress stamp {stamp_s}")
    return stamp


def parse_status_changed_at(
    text: str,
    status: str,
    *,
    path: str,
    now: datetime,
) -> datetime | None:
    """Last Progress stamp with ``→ <current status>``. No match → None."""
    want = normalize_status(status)
    # Validate every Progress stamp (bad/future → BoardError).
    for any_m in PROGRESS_ANY_STAMP_RE.finditer(text):
        _parse_stamp(any_m.group(1), path=path, now=now)
    last: datetime | None = None
    for m in PROGRESS_ARROW_RE.finditer(text):
        stamp = _parse_stamp(m.group(1), path=path, now=now)
        dest = normalize_status(m.group(2))
        if dest == want:
            last = stamp
    return last


def age_hours(since: datetime | None, *, now: datetime) -> float | None:
    """Age in hours. Caller supplies ``now`` (resolve wall-clock upstream)."""
    if not isinstance(now, datetime):
        raise TypeError("age_hours now must be datetime")
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


def load_human_participants(context_dir: Path) -> list[str]:
    path = context_dir / "merge_policy.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_bytes().decode(ENCODING))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BoardError(str(path), f"invalid merge_policy: {exc}") from None
    if "human_participants" not in data:
        return []
    raw = data["human_participants"]
    if not isinstance(raw, list):
        raise BoardError(str(path), "human_participants must be a list")
    return [str(x).strip() for x in raw if str(x).strip()]


def remember_task_id(seen: dict[str, Path], task_id: str, path: Path) -> None:
    """Record task id; duplicate id → BoardError (exact path + reason)."""
    if not isinstance(path, Path):
        raise TypeError("remember_task_id path must be pathlib.Path")
    if task_id in seen:
        raise BoardError(
            str(path),
            f"duplicate task id {task_id} (also {seen[task_id]})",
        )
    seen[task_id] = path


def _read_task(path: Path) -> str:
    try:
        return read_task_text(path)
    except UnicodeDecodeError as exc:
        raise BoardError(str(path), f"invalid utf-8: {exc.reason}") from None


def _card_data(
    task_id: str,
    title: str,
    text: str,
    *,
    path: Path,
    lang: str,
    now: datetime,
) -> dict[str, str]:
    fields = extract_fields(text, path=str(path))
    status = require_status(fields.get("статус"), path=str(path))
    changed = parse_status_changed_at(text, status, path=str(path), now=now)
    hours = age_hours(changed, now=now)
    overdue = is_queue_overdue(status, hours)
    u = ui_for(lang)
    unit = u["hours_unit"]
    age_label = ""
    if changed is not None:
        age_label = changed.strftime("%Y-%m-%d %H:%M UTC")
        if hours is not None:
            age_label = f"{age_label} ({hours:.1f}{unit})"
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
    seen_ids: dict[str, Path] = {}
    paths = sorted(tasks_dir.glob("T-*.md"))
    for path in paths:
        text = _read_task(path)
        matched = require_task_header(text, path)
        task_id = matched.group(1)
        if task_id != path.stem:
            raise BoardError(
                str(path),
                f"header id {task_id!r} != file stem {path.stem!r}",
            )
        remember_task_id(seen_ids, task_id, path)
        cards.append(
            _card_data(
                task_id,
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
    unit = u["hours_unit"]
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
            f'<p class="card-age">{escape(u["age"])}: {escape(card["updated"])}</p>'
        )
    if card.get("overdue"):
        parts.append(
            f'<p class="card-overdue">{escape(u["overdue"])} '
            f"(&gt;{OVERDUE_HOURS}{unit})</p>"
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
    *,
    review_note: str = "",
) -> str:
    empty_html = f'<p class="empty">{escape(u["empty"])}</p>'
    if not items:
        body = empty_html
    else:
        body = JOIN_NL.join(
            _render_card(card, children_map.get(card["id"]) or [], u) for card in items
        )
    note = ""
    if col_id == "for-review" and review_note:
        note = f'\n<span class="col-note">{escape(review_note)}</span>'
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
    reviewers: Sequence[str] | None = None,
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

    note = for_review_note(lang, list(reviewers or ()))
    columns_html: list[str] = []
    for col_id, col_label in columns:
        items = sorted(by_col[col_id], key=lambda c: c["id"])
        columns_html.append(
            _render_column(
                col_id, col_label, items, children_map, u, review_note=note
            )
        )

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
    reviewers: Sequence[str] | None = None,
) -> str:
    cards = collect_board_cards(tasks_dir, lang=lang, now=now)
    if reviewers is None:
        reviewers = load_human_participants(tasks_dir.parent)
    return render_board_html(
        cards,
        generated_at=generated_at,
        title=title,
        lang=lang,
        reviewers=reviewers,
    )


def write_board(
    tasks_dir: Path,
    out_path: Path,
    *,
    generated_at: str | None = None,
    title: str = DEFAULT_TITLE,
    lang: str = DEFAULT_LANG,
    now: datetime,
    reviewers: Sequence[str] | None = None,
) -> Path:
    html_text = generate_board(
        tasks_dir,
        generated_at=generated_at,
        title=title,
        lang=lang,
        now=now,
        reviewers=reviewers,
    )
    write_html(out_path, html_text)
    return out_path
