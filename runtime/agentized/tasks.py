"""Task registry — status vocab for status_gates + schema facade (AGE-45).

Vocab/FIELD_RE stay defined here so ``status_gates`` can import them without a
cycle. ``task_schema`` must not import ``status_gates`` at module import time;
it lazy-loads vocab helpers. This module then re-exports schema helpers eagerly.
"""

from __future__ import annotations

import re

# --- vocabulary surface (imported by status_gates; keep before schema import) ---
# One canonical list + aliases (CLI choices + status_gates).
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
STATUS_ALIASES: dict[str, str] = {"dropped": "canceled", "queued": "queue"}
ALL_STATUSES: tuple[str, ...] = CANONICAL_STATUSES + ("dropped", "queued")

TASK_ID_RE = re.compile(r"^T-\d{6}-[a-z0-9]{3,8}$")
# [ \t]* — not \s* — so an empty field cannot swallow the next header line.
# Extended keys shared with status_gates (header-block scan there; whole-file findall here).
FIELD_RE = re.compile(
    r"^(статус|теги|родитель|claim|blocked_reason|blocked_deadline|"
    r"review_note|acceptance_note|pr):[ \t]*(.*)$",
    re.MULTILINE,
)

# --- schema facade (AGE-45); ACTIVE_STATUSES is INDEX_ACTIVE via schema ---
from .task_schema import (
    ACTIVE_STATUSES,
    TaskMeta,
    allocate_task_id,
    append_progress,
    dependency_cycles_for_dir,
    list_tasks,
    parse_task,
    rebuild_task_index,
    render_task_file,
    set_field,
    unknown_depends_on_ids,
    utc_now_stamp,
    validate_task_status,
)

__all__ = [
    "ACTIVE_STATUSES",
    "ALL_STATUSES",
    "CANONICAL_STATUSES",
    "FIELD_RE",
    "STATUS_ALIASES",
    "TASK_ID_RE",
    "TaskMeta",
    "allocate_task_id",
    "append_progress",
    "dependency_cycles_for_dir",
    "list_tasks",
    "parse_task",
    "rebuild_task_index",
    "render_task_file",
    "set_field",
    "unknown_depends_on_ids",
    "utc_now_stamp",
    "validate_task_status",
]
