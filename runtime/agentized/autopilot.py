"""WIP autopilot + board metrics data hooks (``board.json`` / ``board/metrics.json``).

CLI: ``agentized autopilot``. HTML render is ``agentized board`` (AGE-37). Fail-closed JSON/ints/paths.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT
from .quality_io import read_json_object, write_json_object
from .tasks import list_tasks

BOARD_FILENAME = "board.json"
DEFAULT_METRICS_REL = "board/metrics.json"
DEFAULT_WIP_LIMIT = 3
DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 3650

# Lead status set (#25 owns schema; autopilot defaults use queue/open + WIP).
BOARD_STATUSES = (
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
DEFAULT_PICK_FROM = ["queue", "open"]
DEFAULT_COUNT_AS_WIP = ["in-progress", "self-review"]
QUEUE_STATUSES = frozenset({"open", "queue"})

PROGRESS_LINE_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC: (.+)$", re.MULTILINE
)
TASK_ID_DAY_RE = re.compile(r"^T-(\d{6})-")
STATUS_DONE_RE = re.compile(r"status\s*→\s*done|статус\s*→\s*done", re.IGNORECASE)
STATUS_BLOCKED_RE = re.compile(
    r"status\s*→\s*blocked|статус\s*→\s*blocked", re.IGNORECASE
)


def default_board_config() -> dict[str, Any]:
    return {
        "version": 1,
        "wip_limit": DEFAULT_WIP_LIMIT,
        "autopilot": {
            "enabled": True,
            "pick_from": list(DEFAULT_PICK_FROM),
            "count_as_wip": list(DEFAULT_COUNT_AS_WIP),
        },
        "metrics": {
            "throughput_window_days": DEFAULT_WINDOW_DAYS,
            "output": DEFAULT_METRICS_REL,
        },
    }


def _require_positive_int(value: Any, *, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be >= 1") from exc
    if number < 1:
        raise ValueError(f"{field} must be >= 1")
    return number


def _require_window_days(value: Any) -> int:
    number = _require_positive_int(value, field="throughput_window_days")
    if number > MAX_WINDOW_DAYS:
        raise ValueError(f"throughput_window_days must be <= {MAX_WINDOW_DAYS}")
    return number


def _as_str_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        return list(fallback)
    return [str(item) for item in value]


def _require_safe_rel(raw: Any, *, field: str) -> str:
    text = str(raw).strip() if raw is not None else ""
    path = Path(text)
    if text == "" or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a safe relative path")
    return path.as_posix()


def _validate_metrics_rel(raw: Any) -> str:
    if raw is None:
        return DEFAULT_METRICS_REL
    return _require_safe_rel(raw, field="metrics.output")


def _context_dir(root: Path, context_rel: str) -> Path:
    """Resolved context directory; must stay under ``root`` (no ``..`` / symlink escape)."""
    root_res = root.resolve()
    rel = _require_safe_rel(context_rel, field="context")
    ctx = (root_res / rel).resolve()
    try:
        ctx.relative_to(root_res)
    except ValueError as exc:
        raise ValueError("context path escapes repository root") from exc
    return ctx


def _under_context(root: Path, context_rel: str, *parts: str) -> Path:
    """Resolved path under context; reject lexical and symlink escapes before write."""
    ctx = _context_dir(root, context_rel)
    target = ctx.joinpath(*parts).resolve()
    try:
        target.relative_to(ctx)
    except ValueError as exc:
        raise ValueError("path escapes context directory") from exc
    return target


def board_config_path(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    return _under_context(root, context_rel, BOARD_FILENAME)


def metrics_path(
    root: Path, cfg: dict[str, Any], context_rel: str = DEFAULT_CONTEXT
) -> Path:
    section = cfg.get("metrics")
    if not isinstance(section, dict):
        section = {}
    rel = _validate_metrics_rel(section.get("output"))
    return _under_context(root, context_rel, *Path(rel).parts)


def _normalize_board(base: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Merge user data onto defaults; invalid ints/paths raise."""
    if not isinstance(data, dict):
        raise ValueError("board.json must be a JSON object")
    out = dict(base)
    out.update(data)
    out["wip_limit"] = _require_positive_int(out.get("wip_limit"), field="wip_limit")

    auto_raw = out.get("autopilot")
    auto_in = auto_raw if isinstance(auto_raw, dict) else {}
    out["autopilot"] = {
        "enabled": bool(auto_in.get("enabled", True)),
        "pick_from": _as_str_list(auto_in.get("pick_from"), DEFAULT_PICK_FROM),
        "count_as_wip": _as_str_list(auto_in.get("count_as_wip"), DEFAULT_COUNT_AS_WIP),
    }

    metrics_raw = out.get("metrics")
    metrics_in = metrics_raw if isinstance(metrics_raw, dict) else {}
    out["metrics"] = {
        "throughput_window_days": _require_window_days(
            metrics_in.get("throughput_window_days", DEFAULT_WINDOW_DAYS)
        ),
        "output": _validate_metrics_rel(metrics_in.get("output")),
    }
    return out


def load_board(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    path = board_config_path(root, context_rel)
    base = default_board_config()
    if not path.exists():
        return base
    data = read_json_object(path)
    return _normalize_board(base, data)


def save_board(
    root: Path, data: dict[str, Any], context_rel: str = DEFAULT_CONTEXT
) -> Path:
    path = board_config_path(root, context_rel)
    normalized = _normalize_board(default_board_config(), data)
    write_json_object(path, normalized)
    return path


def ensure_board_config(
    root: Path, context_rel: str = DEFAULT_CONTEXT
) -> dict[str, Any]:
    """Pin default board.json without clobbering user edits."""
    path = board_config_path(root, context_rel)
    created = not path.exists()
    if created:
        save_board(root, default_board_config(), context_rel)
    else:
        load_board(root, context_rel)  # validate existing
    return {"path": str(path.relative_to(root.resolve())), "created": created}


def parse_progress_events(text: str) -> list[tuple[datetime, str]]:
    events: list[tuple[datetime, str]] = []
    for stamp, msg in PROGRESS_LINE_RE.findall(text):
        try:
            dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        events.append((dt, msg.strip()))
    return events


def task_id_day_utc(task_id: str) -> datetime | None:
    m = TASK_ID_DAY_RE.match(task_id)
    if m is None:
        return None
    try:
        return datetime.strptime(m.group(1), "%y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def task_created_at(
    task_id: str, events: list[tuple[datetime, str]]
) -> datetime | None:
    if events:
        return events[0][0]
    return task_id_day_utc(task_id)


def task_completed_at(events: list[tuple[datetime, str]]) -> datetime | None:
    for dt, msg in reversed(events):
        if STATUS_DONE_RE.search(msg):
            return dt
    return None


def task_blocked_since(events: list[tuple[datetime, str]]) -> datetime | None:
    for dt, msg in reversed(events):
        if STATUS_BLOCKED_RE.search(msg):
            return dt
    return None


def hours_between(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600.0)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _max_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values)


def _task_events(task: Any) -> list[tuple[datetime, str]]:
    if not task.path.exists():
        return []
    try:
        text = task.path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{task.path.name}: not valid UTF-8") from exc
    return parse_progress_events(text)


def wip_tasks(tasks: list, cfg: dict[str, Any]) -> list:
    auto = cfg.get("autopilot")
    auto_dict = auto if isinstance(auto, dict) else {}
    statuses = set(_as_str_list(auto_dict.get("count_as_wip"), DEFAULT_COUNT_AS_WIP))
    return [task for task in tasks if task.status in statuses]


def pick_next_task(
    tasks: list,
    cfg: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Recommend next queue/open task when under WIP limit. Never claims."""
    auto = cfg.get("autopilot")
    auto_dict = auto if isinstance(auto, dict) else {}
    limit = _require_positive_int(
        cfg.get("wip_limit", DEFAULT_WIP_LIMIT), field="wip_limit"
    )
    current = wip_tasks(tasks, cfg)
    enabled = bool(auto_dict.get("enabled", True))
    result: dict[str, Any] = {
        "ok": True,
        "wip_limit": limit,
        "wip_current": len(current),
        "under_limit": len(current) < limit,
        "enabled": enabled,
        "task": None,
    }
    if not enabled:
        result["reason"] = "autopilot disabled"
        return result
    if len(current) >= limit:
        result["reason"] = f"WIP at limit ({len(current)}/{limit})"
        return result
    pick_from = set(_as_str_list(auto_dict.get("pick_from"), DEFAULT_PICK_FROM))
    candidates = [task for task in tasks if task.status in pick_from]
    if not candidates:
        result["reason"] = "no pickable tasks"
        return result

    def rank(task: Any) -> tuple[datetime, str]:
        created = task_created_at(task.task_id, _task_events(task))
        if created is None:
            return (now, task.task_id)
        return (created, task.task_id)

    chosen = min(candidates, key=rank)
    result["task"] = {
        "id": chosen.task_id,
        "title": chosen.title,
        "status": chosen.status,
        "path": chosen.path.name,
    }
    result["reason"] = "picked oldest open under WIP"
    return result


def compute_metrics(
    tasks_dir: Path,
    cfg: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    tasks = list_tasks(tasks_dir)
    metrics_cfg = cfg.get("metrics")
    metrics_dict = metrics_cfg if isinstance(metrics_cfg, dict) else {}
    window_days = _require_window_days(
        metrics_dict.get("throughput_window_days", DEFAULT_WINDOW_DAYS)
    )
    window_start = now - timedelta(days=window_days)

    counts = {status: 0 for status in BOARD_STATUSES}
    counts["other"] = 0
    cycle_hours: list[float] = []
    queue_hours: list[float] = []
    blocked_hours: list[float] = []
    done_in_window = 0

    for task in tasks:
        if task.status in BOARD_STATUSES:
            counts[task.status] += 1
        else:
            counts["other"] += 1
        events = _task_events(task)
        created = task_created_at(task.task_id, events)

        if (
            task.status in QUEUE_STATUSES
            and created is not None
            and created <= now
        ):
            queue_hours.append(hours_between(created, now))
        if task.status == "blocked":
            since = task_blocked_since(events)
            if since is not None and since <= now:
                blocked_hours.append(hours_between(since, now))
        if task.status == "done":
            completed = task_completed_at(events)
            if (
                created is not None
                and completed is not None
                and created <= completed <= now
            ):
                cycle_hours.append(hours_between(created, completed))
            if (
                completed is not None
                and window_start <= completed <= now
            ):
                done_in_window += 1

    wip = wip_tasks(tasks, cfg)
    limit = _require_positive_int(
        cfg.get("wip_limit", DEFAULT_WIP_LIMIT), field="wip_limit"
    )
    next_pick = pick_next_task(tasks, cfg, now=now)
    auto = cfg.get("autopilot")
    auto_dict = auto if isinstance(auto, dict) else {}
    reason = next_pick.get("reason")
    if reason is None:
        reason = ""

    return {
        "version": 1,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wip": {
            "limit": limit,
            "current": len(wip),
            "under_limit": len(wip) < limit,
            "task_ids": [task.task_id for task in wip],
        },
        "counts": counts,
        "throughput": {
            "window_days": window_days,
            "done_count": done_in_window,
            "per_day": round(done_in_window / float(window_days), 4),
        },
        "cycle_time": {
            "samples": len(cycle_hours),
            "avg_hours": _avg(cycle_hours),
            "p50_hours": _median(cycle_hours),
        },
        "queue_age": {
            "samples": len(queue_hours),
            "avg_hours": _avg(queue_hours),
            "max_hours": _max_or_none(queue_hours),
        },
        "blocked_age": {
            "samples": len(blocked_hours),
            "avg_hours": _avg(blocked_hours),
            "max_hours": _max_or_none(blocked_hours),
        },
        "next_task": next_pick.get("task"),
        "autopilot": {
            "enabled": bool(auto_dict.get("enabled", True)),
            "reason": reason,
        },
    }


def write_metrics(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    now: datetime | None = None,
) -> dict[str, Any]:
    ensure_board_config(root, context_rel)
    when = now if now is not None else datetime.now(timezone.utc)
    cfg = load_board(root, context_rel)
    tasks_dir = root / context_rel / "tasks"
    payload = compute_metrics(tasks_dir, cfg, now=when)
    path = metrics_path(root, cfg, context_rel)
    write_json_object(path, payload)
    return {"path": str(path.relative_to(root.resolve())), "metrics": payload}


def load_metrics_file(
    root: Path, context_rel: str = DEFAULT_CONTEXT
) -> dict[str, Any] | None:
    cfg = load_board(root, context_rel)
    path = metrics_path(root, cfg, context_rel)
    if not path.exists():
        return None
    return read_json_object(path)


def set_wip_limit(
    root: Path, limit: int, *, context_rel: str = DEFAULT_CONTEXT
) -> dict[str, Any]:
    data = load_board(root, context_rel)
    data["wip_limit"] = _require_positive_int(limit, field="wip_limit")
    save_board(root, data, context_rel)
    return load_board(root, context_rel)
