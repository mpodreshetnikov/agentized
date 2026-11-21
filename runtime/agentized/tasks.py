"""Task registry — status vocab for status_gates + schema facade (AGE-45).

Vocab/FIELD_RE stay defined here so ``status_gates`` can import them without a
cycle. ``datetime`` / ``secrets`` / ``re`` / ``timezone`` live on this module so
verbatim ``test_tasks`` monkeypatches keep working through schema helpers.
"""

from __future__ import annotations

import re
import secrets  # noqa: F401 — schema/tests monkeypatch via tasks.secrets
from datetime import datetime, timezone  # noqa: F401 — tasks.datetime/timezone
from typing import Any

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
# Claim / INDEX sections — main layout only (not INDEX_ACTIVE).
CLAIM_STATUSES: tuple[str, ...] = ("open", "in-progress", "blocked")

TASK_ID_RE = re.compile(r"^T-\d{6}-[a-z0-9]{3,8}$")
# [ \t]* — not \s* — so an empty field cannot swallow the next header line.
# Extended keys shared with status_gates (header-block scan there; whole-file findall here).
FIELD_RE = re.compile(
    r"^(статус|теги|родитель|claim|blocked_reason|blocked_deadline|"
    r"review_note|acceptance_note|pr):[ \t]*(.*)$",
    re.MULTILINE,
)

# --- schema facade (AGE-45) ---
from .task_schema import (
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


def __getattr__(name: str) -> Any:
    # ACTIVE_STATUSES ↔ status_gates.INDEX_ACTIVE_STATUSES (lazy identity).
    if name == "ACTIVE_STATUSES":
        from .task_schema import ACTIVE_STATUSES

        return ACTIVE_STATUSES
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [  # noqa: F822  # ACTIVE_STATUSES via __getattr__
    "ACTIVE_STATUSES",
    "ALL_STATUSES",
    "CANONICAL_STATUSES",
    "CLAIM_STATUSES",
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
