"""ADR create helper (AGE-44)."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .tasks import TASK_ID_RE

ADR_ALLOCATE_ERROR = "не удалось выделить уникальный ADR id"
DEFAULT_SLUG = "adr"
ADR_STATUSES = ("proposed", "accepted", "superseded", "deprecated")
ADR_STATUS_ERROR = "неизвестный ADR status {status!r}; ожидалось одно из {allowed}"
ADR_TITLE_EMPTY = "ADR title must be non-empty"
ADR_TITLE_CONTROL = "ADR title must not contain newlines or control characters"
ADR_TASK_ID_ERROR = "неверный task id {task_id!r}; ожидался формат T-YYMMDD-xxxx"

_CYR_TRANS = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def utc_day(now: datetime | None = None) -> str:
    stamp = now if now is not None else datetime.now(timezone.utc)
    return stamp.strftime("%y%m%d")


def allocate_adr_id(
    decisions_dir: Path,
    day: str | None = None,
    *,
    now: datetime | None = None,
) -> str:
    day = day if day is not None else utc_day(now)
    existing_ids: set[str] = set()
    for path in decisions_dir.glob("ADR-*.md"):
        parts = path.stem.split("-")
        if len(parts) >= 3:
            existing_ids.add(f"{parts[0]}-{parts[1]}-{parts[2]}")
    for _ in range(64):
        suffix = secrets.token_hex(2)[:3]
        candidate = f"ADR-{day}-{suffix}"
        if candidate not in existing_ids:
            return candidate
    raise RuntimeError(ADR_ALLOCATE_ERROR)


def slugify(title: str) -> str:
    lowered = title.lower().translate(_CYR_TRANS)
    parts = [p for p in re.split(r"[^a-z0-9]+", lowered) if p]
    slug = "-".join(parts)[:48]
    if slug.endswith("-"):
        slug = slug[:-1]
    return slug or DEFAULT_SLUG


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


def validate_title(title: str) -> None:
    if not title or not title.strip():
        raise ValueError(ADR_TITLE_EMPTY)
    if any(ord(ch) < 32 for ch in title):
        raise ValueError(ADR_TITLE_CONTROL)


def validate_task_ids(tasks: list[str]) -> None:
    for task_id in tasks:
        if not TASK_ID_RE.match(task_id):
            raise ValueError(ADR_TASK_ID_ERROR.format(task_id=task_id))


def render_adr(
    adr_id: str,
    title: str,
    *,
    status: str = "proposed",
    tasks: list[str] | None = None,
    now: datetime | None = None,
) -> str:
    stamp = now if now is not None else datetime.now(timezone.utc)
    day = stamp.strftime("%Y-%m-%d")
    task_list = list(tasks) if tasks is not None else []
    tasks_line = "[" + ", ".join(task_list) + "]"
    return (
        f"---\n"
        f"id: {adr_id}\n"
        f"title: {_yaml_quote(title)}\n"
        f"status: {status}\n"
        f"date: {day}\n"
        f"tasks: {tasks_line}\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"## Context\n\n"
        f"_(why this decision is needed)_\n\n"
        f"## Decision\n\n"
        f"_(what we decided)_\n\n"
        f"## Consequences\n\n"
        f"_(what follows)_\n"
    )


def create_adr(
    decisions_dir: Path,
    title: str,
    *,
    status: str = "proposed",
    tasks: list[str] | None = None,
    now: datetime | None = None,
) -> Path:
    validate_title(title)
    if status not in ADR_STATUSES:
        raise ValueError(ADR_STATUS_ERROR.format(status=status, allowed=ADR_STATUSES))
    task_list = list(tasks) if tasks is not None else []
    validate_task_ids(task_list)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    adr_id = allocate_adr_id(decisions_dir, now=now)
    path = decisions_dir / f"{adr_id}-{slugify(title)}.md"
    path.write_text(
        render_adr(adr_id, title, status=status, tasks=task_list, now=now),
        encoding="utf-8",
    )
    return path
