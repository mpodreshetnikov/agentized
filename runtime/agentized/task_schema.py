"""Task schema helpers (AGE-26)."""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Status vocab from main status_gates (#37). Do not import status_gates at
# module import time — tasks.py loads this module while status_gates is still
# initializing. ACTIVE mirrors INDEX_ACTIVE values from status_gates.
ACTIVE_STATUSES: tuple[str, ...] = (
    "open",
    "queue",
    "in-progress",
    "self-review",
    "for-review",
    "blocked",
)

_STATUS_GATE_EXPORTS = frozenset(
    {
        "ALL_STATUSES",
        "CANONICAL_STATUSES",
        "INDEX_ACTIVE_STATUSES",
        "MSG_UNKNOWN_STATUS",
        "is_known_status",
        "normalize_status",
    }
)


def __getattr__(name: str):
    if name in _STATUS_GATE_EXPORTS:
        from . import status_gates as _sg

        return getattr(_sg, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def validate_task_status(status: str | None) -> list[str]:
    """Return errors when status is empty or not in the canonical vocabulary."""
    from .status_gates import MSG_UNKNOWN_STATUS, is_known_status, normalize_status

    st = normalize_status(status)
    if not st:
        return ["status is required"]
    if not is_known_status(st):
        return [MSG_UNKNOWN_STATUS.format(st=st)]
    return []


KINDS = ("feature", "bug", "debt", "chore", "spike", "docs")
PRIORITIES = ("p0", "p1", "p2", "p3")
TASK_ID_RE = re.compile(r"^T-\d{6}-[a-z0-9]{3,8}$")
TITLE_RE = re.compile(r"^#\s+(T-\d{6}-[a-z0-9]+)\s*[—\-–]\s*(.+)$")
FIELD_RE = re.compile(
    r"^(статус|теги|родитель|claim|kind|priority|owner|depends_on|blocked_by|"
    r"blocked_reason|blocked_deadline|exit|acceptance_note|review_note|pr|"
    r"orbit_id|superseded_by):[ \t]*(.*)$",
    re.MULTILINE,
)
LIST_SPLIT_RE = re.compile(r"[,\s]+")
SKIP_NAMES = frozenset({"INDEX.md", "TEMPLATE.md"})
PLACEHOLDER_PARENT = "_(пусто для корневой задачи; для подзадачи — путь или id родителя)_"
PLACEHOLDER_CLAIM = "_(пусто или кто ведёт)_"
PLACEHOLDER_TAGS = "_(нет)_"
PLACEHOLDER_SECTION = "_(append-only)_"
PLACEHOLDER_EMPTY = "_(пусто)_"
DEFAULT_GOAL = "Что должно быть сделано."
PROGRESS_MARKER = "## Progress"
INDEX_TITLE = "# Задачи — живой индекс"
INDEX_INTRO = "Генерируемый список **активной** работы. Не полный архив истории."
INDEX_SEARCH = "Поиск: этот индекс + grep по id / title / tags. Не обходи весь каталог `tasks/`."
INDEX_FOOTER = (
    "Новые задачи — по [`TEMPLATE.md`](TEMPLATE.md). Файлы задач лежат рядом с этим индексом; "
    "при смене статуса файл **не перемещается**."
)
ID_ALLOCATE_ERROR = "не удалось выделить уникальный id задачи"


@dataclass
class TaskMeta:
    path: Path
    task_id: str
    title: str
    status: str
    tags: str
    parent: str
    claim: str
    kind: str = ""
    priority: str = ""
    owner: str = ""
    depends_on: list[str] = field(default_factory=list)
    blocked_by: str = ""
    exit: str = ""
    superseded_by: str = ""
    orbit_id: str = ""


def _strip_outer_brackets(text: str) -> str:
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        return text[1:-1].strip()
    return text


def _strip_one_quote(part: str) -> str:
    if len(part) < 2:
        return part
    if part[0] == "'" and part[-1] == "'":
        return part[1:-1]
    if part[0] == '"' and part[-1] == '"':
        return part[1:-1]
    return part


def parse_id_list(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text or text.startswith("_"):
        return []
    text = _strip_outer_brackets(text)
    out: list[str] = []
    for part in LIST_SPLIT_RE.split(text):
        part = _strip_one_quote(part.strip())
        if part:
            out.append(part)
    return out


def format_id_list(ids: Iterable[str]) -> str:
    items = [i for i in ids if i]
    if not items:
        return ""
    return "[" + ", ".join(items) + "]"


def unknown_depends_on_ids(
    tasks: list[TaskMeta],
) -> list[tuple[str, str]]:
    """Return (task_id, missing_dep_id) for depends_on ids with no task file."""
    known = {t.task_id for t in tasks}
    missing: list[tuple[str, str]] = []
    for t in tasks:
        for dep in t.depends_on:
            if dep not in known:
                missing.append((t.task_id, dep))
    return missing


def validate_kind_priority(kind: str, priority: str) -> list[str]:
    errs: list[str] = []
    if kind and kind not in KINDS:
        errs.append(f"unknown kind {kind!r}; expected one of {KINDS}")
    if priority and priority not in PRIORITIES:
        errs.append(f"unknown priority {priority!r}; expected one of {PRIORITIES}")
    return errs


def find_dependency_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Return simple cycles in depends_on graph (each cycle as id list)."""
    cycles: list[list[str]] = []
    seen_cycle: set[tuple[str, ...]] = set()
    visiting: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> None:
        if node in visiting:
            if node in stack:
                start = stack.index(node)
                cycle = stack[start:] + [node]
                key = tuple(sorted(cycle[:-1]))
                if key not in seen_cycle:
                    seen_cycle.add(key)
                    cycles.append(cycle)
            return
        if node not in graph:
            return
        visiting.add(node)
        stack.append(node)
        for nxt in graph.get(node) or []:
            dfs(nxt)
        stack.pop()
        visiting.remove(node)

    for start in sorted(graph):
        dfs(start)
    return cycles


def dependency_graph(tasks: Iterable[object]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for t in tasks:
        tid = getattr(t, "task_id", None)
        deps = getattr(t, "depends_on", None) or []
        if not tid:
            continue
        if isinstance(deps, str):
            deps = parse_id_list(deps)
        graph[str(tid)] = [str(d) for d in deps]
    return graph


def utc_now_stamp() -> str:
    return datetime.now(UTC).strftime("%y%m%d")


def allocate_task_id(tasks_dir: Path, day: str | None = None) -> str:
    day = day if day is not None else utc_now_stamp()
    existing = {p.stem for p in tasks_dir.glob("T-*.md")}
    for _ in range(64):
        suffix = secrets.token_hex(2)
        candidate = f"T-{day}-{suffix}"
        if candidate not in existing:
            return candidate
    raise RuntimeError(ID_ALLOCATE_ERROR)


def parse_task(path: Path) -> TaskMeta | None:
    if path.name in SKIP_NAMES or not path.name.endswith(".md"):
        return None
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    m = TITLE_RE.match(lines[0]) if lines else None
    if not m:
        stem = path.stem
        if not TASK_ID_RE.match(stem):
            return None
        task_id, title = stem, stem
    else:
        task_id, title = m.group(1), m.group(2).strip()
    fields = {k: v.strip() for k, v in FIELD_RE.findall(text)}

    def field(name: str, default: str = "") -> str:
        return (fields.get(name) or default).strip()

    return TaskMeta(
        path=path,
        task_id=task_id,
        title=title,
        status=field("статус", "idea"),
        tags=field("теги"),
        parent=field("родитель"),
        claim=field("claim"),
        kind=field("kind"),
        priority=field("priority"),
        owner=field("owner"),
        depends_on=parse_id_list(fields.get("depends_on") or ""),
        blocked_by=field("blocked_by"),
        exit=field("exit"),
        superseded_by=field("superseded_by"),
        orbit_id=field("orbit_id"),
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
    kind: str = "",
    priority: str = "",
    owner: str = "",
    depends_on: list[str] | None = None,
    blocked_by: str = "",
    blocked_reason: str = "",
    blocked_deadline: str = "",
    exit: str = "",
    acceptance_note: str = "",
    review_note: str = "",
    pr: str = "",
    orbit_id: str = "",
    superseded_by: str = "",
    goal: str = DEFAULT_GOAL,
    value: str = "",
) -> str:
    parent_val = parent or PLACEHOLDER_PARENT
    claim_val = claim or PLACEHOLDER_CLAIM
    tags_val = tags or PLACEHOLDER_TAGS
    lines = [
        f"# {task_id} — {title}",
        "",
        f"статус: {status}",
        f"теги: {tags_val}",
        f"родитель: {parent_val}",
        f"claim: {claim_val}",
    ]
    if kind:
        lines.append(f"kind: {kind}")
    if priority:
        lines.append(f"priority: {priority}")
    if owner:
        lines.append(f"owner: {owner}")
    deps = format_id_list(depends_on or [])
    if deps:
        lines.append(f"depends_on: {deps}")
    if blocked_by:
        lines.append(f"blocked_by: {blocked_by}")
    if blocked_reason:
        lines.append(f"blocked_reason: {blocked_reason}")
    if blocked_deadline:
        lines.append(f"blocked_deadline: {blocked_deadline}")
    if exit:
        lines.append(f"exit: {exit}")
    if acceptance_note:
        lines.append(f"acceptance_note: {acceptance_note}")
    if review_note:
        lines.append(f"review_note: {review_note}")
    if pr:
        lines.append(f"pr: {pr}")
    if orbit_id:
        lines.append(f"orbit_id: {orbit_id}")
    if superseded_by:
        lines.append(f"superseded_by: {superseded_by}")
    lines.append("")
    if value:
        lines.extend([f"Ценность: {value}", ""])
    lines.extend(
        [
            "## Цель",
            "",
            goal,
            "",
            PROGRESS_MARKER,
            "",
            PLACEHOLDER_SECTION,
            "",
            "## Decision Log",
            "",
            PLACEHOLDER_SECTION,
            "",
        ]
    )
    return "\n".join(lines)


def set_field(text: str, field_name: str, value: str) -> str:
    # [ \t]* — not \s* — so an empty field line cannot swallow the next header.
    pattern = re.compile(rf"^{re.escape(field_name)}:[ \t]*.*$", re.MULTILINE)
    replacement = f"{field_name}: {value}"
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
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    line = f"- {stamp}: {entry}"
    idx = text.find(PROGRESS_MARKER)
    if idx == -1:
        return text.rstrip() + f"\n\n{PROGRESS_MARKER}\n\n{line}\n"
    before = text[:idx]
    after = text[idx + len(PROGRESS_MARKER) :]
    marker = "\n## "
    cut = after.find(marker)
    if cut == -1:
        progress_body = after.rstrip() + "\n" + line + "\n"
        return before + PROGRESS_MARKER + progress_body
    progress_body = after[:cut].rstrip() + "\n" + line + "\n"
    rest = after[cut:]
    return before + PROGRESS_MARKER + progress_body + rest


def dependency_cycles_for_dir(tasks_dir: Path) -> list[list[str]]:
    return find_dependency_cycles(dependency_graph(list_tasks(tasks_dir)))


def rebuild_task_index(tasks_dir: Path) -> str:
    from .status_gates import normalize_status

    tasks = list_tasks(tasks_dir)
    buckets: dict[str, list[str]] = {s: [] for s in ACTIVE_STATUSES}
    for t in tasks:
        st = normalize_status(t.status)
        if st not in buckets:
            continue
        parent = f" (родитель: {t.parent})" if t.parent and not t.parent.startswith("_") else ""
        claim = f" · claim: {t.claim}" if t.claim and not t.claim.startswith("_") else ""
        buckets[st].append(f"- [{t.task_id}]({t.path.name}) — {t.title}{parent}{claim}")

    def section(name: str) -> str:
        rows = buckets[name]
        body = "\n".join(rows) if rows else PLACEHOLDER_EMPTY
        return f"## {name}\n\n{body}"

    status_label = " · ".join(f"`{s}`" for s in ACTIVE_STATUSES)
    chunks = [
        INDEX_TITLE,
        INDEX_INTRO,
        f"Статусы в индексе: {status_label}.",
        INDEX_SEARCH,
    ]
    for name in ACTIVE_STATUSES:
        chunks.append(section(name))
    chunks.append(INDEX_FOOTER)
    return "\n\n".join(chunks) + "\n"
