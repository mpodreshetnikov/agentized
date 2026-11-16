from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .status_gates import ALL_STATUSES as GATE_ALL_STATUSES
from .status_gates import normalize_status

ACTIVE_STATUSES = (
    "open",
    "queue",
    "in-progress",
    "self-review",
    "for-review",
    "blocked",
)
WORK_STATUSES = ACTIVE_STATUSES
ALL_STATUSES = GATE_ALL_STATUSES

TASK_ID_RE = re.compile(r"^T-\d{6}-[a-z0-9]{3,8}$")
FIELD_RE = re.compile(
    r"^(статус|теги|родитель|claim|blocked_reason|blocked_deadline|"
    r"review_note|acceptance_note|pr):[ \t]*(.*)$",
    re.MULTILINE,
)
VALUE_LINE_RE = re.compile(r"(?im)^\s*Ценность:\s*(.+?)\s*$")


@dataclass
class TaskMeta:
    path: Path
    task_id: str
    title: str
    status: str
    tags: str
    parent: str
    claim: str
    value: str = ""
    blocked_reason: str = ""
    blocked_deadline: str = ""
    review_note: str = ""
    acceptance_note: str = ""


def utc_now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%y%m%d")


def allocate_task_id(tasks_dir: Path, day: str | None = None) -> str:
    day = day or utc_now_stamp()
    existing = {p.stem for p in tasks_dir.glob("T-*.md")}
    for _ in range(64):
        suffix = secrets.token_hex(2)
        candidate = f"T-{day}-{suffix}"
        if candidate not in existing:
            return candidate
    raise RuntimeError("не удалось выделить уникальный id задачи")


def parse_task(path: Path) -> TaskMeta | None:
    if path.name in {"INDEX.md", "TEMPLATE.md"} or not path.name.endswith(".md"):
        return None
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text.strip() else ""
    m = re.match(r"^#\s+(T-\d{6}-[a-z0-9]+)\s*[—\-–]\s*(.+)$", first)
    if not m:
        stem = path.stem
        if not TASK_ID_RE.match(stem):
            return None
        task_id, title = stem, stem
    else:
        task_id, title = m.group(1), m.group(2).strip()
    fields = {k: v.strip() for k, v in FIELD_RE.findall(text)}
    value_m = VALUE_LINE_RE.search(text)
    raw_status = fields.get("статус")
    if raw_status is None:
        status = ""
    else:
        status = normalize_status(raw_status)
    return TaskMeta(
        path=path,
        task_id=task_id,
        title=title,
        status=status,
        tags=(fields.get("теги") or "").strip(),
        parent=(fields.get("родитель") or "").strip(),
        claim=(fields.get("claim") or "").strip(),
        value=(value_m.group(1).strip() if value_m else ""),
        blocked_reason=(fields.get("blocked_reason") or "").strip(),
        blocked_deadline=(fields.get("blocked_deadline") or "").strip(),
        review_note=(fields.get("review_note") or "").strip(),
        acceptance_note=(fields.get("acceptance_note") or "").strip(),
    )


def list_tasks(tasks_dir: Path) -> list[TaskMeta]:
    out: list[TaskMeta] = []
    for path in sorted(tasks_dir.glob("T-*.md")):
        meta = parse_task(path)
        if meta:
            out.append(meta)
    return out


def render_task_file(
    task_id: str,
    title: str,
    *,
    status: str = "open",
    tags: str = "",
    parent: str = "",
    claim: str = "",
    goal: str = "Что должно быть сделано.",
    value: str = "",
    blocked_reason: str = "",
    blocked_deadline: str = "",
    review_note: str = "",
    acceptance_note: str = "",
) -> str:
    parent_val = parent or "_(пусто для корневой задачи; для подзадачи — путь или id родителя)_"
    claim_val = claim or "_(пусто или кто ведёт)_"
    tags_val = tags or "_(нет)_"
    value_line = value.strip() or "_(одна фраза простым языком — зачем это людям)_"
    extras = ""
    if blocked_reason:
        extras += f"blocked_reason: {blocked_reason}\n"
    if blocked_deadline:
        extras += f"blocked_deadline: {blocked_deadline}\n"
    if review_note:
        extras += f"review_note: {review_note}\n"
    if acceptance_note:
        extras += f"acceptance_note: {acceptance_note}\n"
    return (
        f"# {task_id} — {title}\n\n"
        f"статус: {status}\n"
        f"теги: {tags_val}\n"
        f"родитель: {parent_val}\n"
        f"claim: {claim_val}\n"
        f"{extras}\n"
        f"Ценность: {value_line}\n\n"
        f"## Цель\n\n{goal}\n\n"
        f"## Progress\n\n_(append-only)_\n\n"
        f"## Decision Log\n\n_(append-only)_\n"
    )


def set_field(text: str, field: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(field)}:\s*.*$", re.MULTILINE)
    replacement = f"{field}: {value}"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    # insert after title block
    lines = text.splitlines()
    if not lines:
        return f"{replacement}\n"
    insert_at = 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    lines.insert(insert_at, replacement)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def append_progress(text: str, entry: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    line = f"- {stamp}: {entry}"
    marker = "## Progress"
    if marker not in text:
        return text.rstrip() + f"\n\n{marker}\n\n{line}\n"
    before, after = text.split(marker, 1)
    # after starts with optional newlines then content until next ##
    parts = after.split("\n## ", 1)
    progress_body = parts[0]
    rest = ("\n## " + parts[1]) if len(parts) > 1 else ""
    progress_body = progress_body.rstrip() + "\n" + line + "\n"
    return before + marker + progress_body + rest


def rebuild_task_index(tasks_dir: Path) -> str:
    tasks = list_tasks(tasks_dir)
    buckets = {s: [] for s in ACTIVE_STATUSES}
    for t in tasks:
        if t.status in buckets:
            parent = f" (родитель: {t.parent})" if t.parent and not t.parent.startswith("_") else ""
            claim = f" · claim: {t.claim}" if t.claim and not t.claim.startswith("_") else ""
            buckets[t.status].append(f"- [{t.task_id}]({t.path.name}) — {t.title}{parent}{claim}")

    def section(name: str) -> str:
        rows = buckets[name]
        body = "\n".join(rows) if rows else "_(пусто)_"
        return f"## {name}\n\n{body}\n"

    sections = "\n".join(section(name) for name in ACTIVE_STATUSES)
    status_list = " · ".join(f"`{s}`" for s in ACTIVE_STATUSES)
    return (
        "# Задачи — живой индекс\n\n"
        "Генерируемый список **активной** работы. Не полный архив истории.\n\n"
        f"Статусы в индексе: {status_list}.\n\n"
        "Поиск: этот индекс + grep по id / title / tags. Не обходи весь каталог `tasks/`.\n\n"
        f"{sections}\n"
        "Новые задачи — по [`TEMPLATE.md`](TEMPLATE.md). Файлы задач лежат рядом с этим индексом; "
        "при смене статуса файл **не перемещается**.\n"
    )
