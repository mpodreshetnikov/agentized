from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ACTIVE_STATUSES = ("open", "in-progress", "blocked")
ALL_STATUSES = ("idea", "open", "in-progress", "blocked", "done", "dropped")

TASK_ID_RE = re.compile(r"^T-\d{6}-[a-z0-9]{3,8}$")
FIELD_RE = re.compile(r"^(статус|теги|родитель|claim):\s*(.*)$", re.MULTILINE)


@dataclass
class TaskMeta:
    path: Path
    task_id: str
    title: str
    status: str
    tags: str
    parent: str
    claim: str


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
    return TaskMeta(
        path=path,
        task_id=task_id,
        title=title,
        status=(fields.get("статус") or "idea").strip(),
        tags=(fields.get("теги") or "").strip(),
        parent=(fields.get("родитель") or "").strip(),
        claim=(fields.get("claim") or "").strip(),
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
) -> str:
    parent_val = parent or "_(пусто для корневой задачи; для подзадачи — путь или id родителя)_"
    claim_val = claim or "_(пусто или кто ведёт)_"
    tags_val = tags or "_(нет)_"
    return (
        f"# {task_id} — {title}\n\n"
        f"статус: {status}\n"
        f"теги: {tags_val}\n"
        f"родитель: {parent_val}\n"
        f"claim: {claim_val}\n\n"
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

    return (
        "# Задачи — живой индекс\n\n"
        "Генерируемый список **активной** работы. Не полный архив истории.\n\n"
        "Статусы в индексе: `open` · `in-progress` · `blocked`.\n\n"
        "Поиск: этот индекс + grep по id / title / tags. Не обходи весь каталог `tasks/`.\n\n"
        f"{section('open')}\n"
        f"{section('in-progress')}\n"
        f"{section('blocked')}\n"
        "Новые задачи — по [`TEMPLATE.md`](TEMPLATE.md). Файлы задач лежат рядом с этим индексом; "
        "при смене статуса файл **не перемещается**.\n"
    )
