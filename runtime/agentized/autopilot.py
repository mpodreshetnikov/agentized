"""WIP autopilot + board metrics (``agentized autopilot``). HTML board is AGE-37."""
from __future__ import annotations

import re
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .context_paths import require_safe_rel, under_context
from .paths import DEFAULT_CONTEXT
from .quality_io import read_json_object, write_json_object
from .tasks import list_tasks

# After #25 merges: ``from .status_gates import CANONICAL_STATUSES, normalize_status``.
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
STATUS_ALIASES = {"dropped": "canceled", "queued": "queue"}
CANONICAL_STATUSES = BOARD_STATUSES

BOARD_FILENAME = "board.json"
DEFAULT_METRICS_REL = "board/metrics.json"
DEFAULT_WIP_LIMIT = 3
DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 3650
DEFAULT_PICK_FROM = ["queue", "open"]
DEFAULT_COUNT_AS_WIP = ["in-progress", "self-review"]
QUEUE_STATUSES = frozenset({"open", "queue"})

PROGRESS_LINE_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC: (.+)$", re.MULTILINE
)
TASK_ID_DAY_RE = re.compile(r"^T-(\d{6})-")
# Progress stamps from ``agentized status`` (status-change record).
STATUS_ARROW_RE = re.compile(
    r"(?:status|статус)\s*→\s*([^\s,;]+)", re.IGNORECASE
)


def normalize_status(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    return STATUS_ALIASES.get(s, s)


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


def _require_bool(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _require_status_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list of canonical statuses")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field} entries must be strings")
        st = normalize_status(item)
        if st not in CANONICAL_STATUSES:
            raise ValueError(f"{field}: unknown status {item!r}")
        out.append(st)
    return out


def _validate_metrics_rel(raw: Any) -> str:
    if raw is None:
        return DEFAULT_METRICS_REL
    return require_safe_rel(raw, field="metrics.output")


def board_config_path(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    return under_context(root, context_rel, BOARD_FILENAME)


def metrics_path(
    root: Path, cfg: dict[str, Any], context_rel: str = DEFAULT_CONTEXT
) -> Path:
    section = cfg.get("metrics")
    if not isinstance(section, dict):
        section = {}
    rel = _validate_metrics_rel(section.get("output"))
    return under_context(root, context_rel, *Path(rel).parts)


def _normalize_autopilot(auto_raw: Any) -> dict[str, Any]:
    if auto_raw is None:
        auto_in: dict[str, Any] = {}
    elif not isinstance(auto_raw, dict):
        raise ValueError("autopilot must be an object")
    else:
        auto_in = auto_raw
    if "enabled" not in auto_in:
        enabled = True
    else:
        enabled = _require_bool(auto_in["enabled"], field="autopilot.enabled")
    if "pick_from" not in auto_in:
        pick_from = list(DEFAULT_PICK_FROM)
    else:
        pick_from = _require_status_list(auto_in["pick_from"], field="autopilot.pick_from")
    if "count_as_wip" not in auto_in:
        count_as_wip = list(DEFAULT_COUNT_AS_WIP)
    else:
        count_as_wip = _require_status_list(
            auto_in["count_as_wip"], field="autopilot.count_as_wip"
        )
    return {
        "enabled": enabled,
        "pick_from": pick_from,
        "count_as_wip": count_as_wip,
    }


def _normalize_board(base: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("board.json must be a JSON object")
    out = dict(base)
    out.update(data)
    out["wip_limit"] = _require_positive_int(out.get("wip_limit"), field="wip_limit")
    out["autopilot"] = _normalize_autopilot(out.get("autopilot"))
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
    return _normalize_board(base, read_json_object(path))


def save_board(
    root: Path, data: dict[str, Any], context_rel: str = DEFAULT_CONTEXT
) -> Path:
    path = board_config_path(root, context_rel)
    write_json_object(path, _normalize_board(default_board_config(), data))
    return path


def ensure_board_config(
    root: Path, context_rel: str = DEFAULT_CONTEXT
) -> dict[str, Any]:
    path = board_config_path(root, context_rel)
    created = not path.exists()
    if created:
        save_board(root, default_board_config(), context_rel)
    else:
        load_board(root, context_rel)
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


def _status_from_progress_msg(msg: str) -> str | None:
    m = STATUS_ARROW_RE.search(msg)
    if m is None:
        return None
    st = normalize_status(m.group(1))
    return st if st in CANONICAL_STATUSES else None


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
        if _status_from_progress_msg(msg) == "done":
            return dt
    return None


def task_blocked_since(events: list[tuple[datetime, str]]) -> datetime | None:
    for dt, msg in reversed(events):
        if _status_from_progress_msg(msg) == "blocked":
            return dt
    return None


def hours_between(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600.0)


def _avg(values: list[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _median(values: list[float]) -> float | None:
    return None if not values else float(statistics.median(values))


def _max_or_none(values: list[float]) -> float | None:
    return None if not values else max(values)


def _task_events(task: Any) -> list[tuple[datetime, str]]:
    if not task.path.exists():
        return []
    try:
        text = task.path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{task.path.name}: not valid UTF-8") from exc
    return parse_progress_events(text)


def _autopilot_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return _normalize_autopilot(cfg.get("autopilot"))


def wip_tasks(tasks: list, cfg: dict[str, Any]) -> list:
    statuses = set(_autopilot_cfg(cfg)["count_as_wip"])
    return [t for t in tasks if normalize_status(t.status) in statuses]


def pick_next_task(
    tasks: list,
    cfg: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    auto = _autopilot_cfg(cfg)
    limit = _require_positive_int(
        cfg.get("wip_limit", DEFAULT_WIP_LIMIT), field="wip_limit"
    )
    current = wip_tasks(tasks, cfg)
    enabled = auto["enabled"]
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
    pick_from = set(auto["pick_from"])
    candidates = [t for t in tasks if normalize_status(t.status) in pick_from]
    if not candidates:
        result["reason"] = "no pickable tasks"
        return result

    def rank(task: Any) -> tuple[datetime, str]:
        created = task_created_at(task.task_id, _task_events(task))
        return (now if created is None else created, task.task_id)

    chosen = min(candidates, key=rank)
    result["task"] = {
        "id": chosen.task_id,
        "title": chosen.title,
        "status": normalize_status(chosen.status) or chosen.status,
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
    auto = _autopilot_cfg(cfg)

    counts = {status: 0 for status in BOARD_STATUSES}
    counts["other"] = 0
    cycle_hours: list[float] = []
    queue_hours: list[float] = []
    blocked_hours: list[float] = []
    done_in_window = 0

    for task in tasks:
        st = normalize_status(task.status)
        if st in BOARD_STATUSES:
            counts[st] += 1
        else:
            counts["other"] += 1
        events = _task_events(task)
        created = task_created_at(task.task_id, events)

        if st in QUEUE_STATUSES and created is not None and created <= now:
            queue_hours.append(hours_between(created, now))
        if st == "blocked":
            since = task_blocked_since(events)
            if since is not None and since <= now:
                blocked_hours.append(hours_between(since, now))
        if st == "done":
            completed = task_completed_at(events)
            if (
                created is not None
                and completed is not None
                and created <= completed <= now
            ):
                cycle_hours.append(hours_between(created, completed))
            if completed is not None and window_start <= completed <= now:
                done_in_window += 1

    wip = wip_tasks(tasks, cfg)
    limit = _require_positive_int(
        cfg.get("wip_limit", DEFAULT_WIP_LIMIT), field="wip_limit"
    )
    next_pick = pick_next_task(tasks, cfg, now=now)
    reason = next_pick.get("reason") or ""

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
        "timing_source": "progress_status_arrows",
        "next_task": next_pick.get("task"),
        "autopilot": {"enabled": auto["enabled"], "reason": reason},
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
    payload = compute_metrics(under_context(root, context_rel, "tasks"), cfg, now=when)
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
