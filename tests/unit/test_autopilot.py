from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentized import autopilot as board_mod
from agentized.autopilot import (
    BOARD_STATUSES,
    DEFAULT_COUNT_AS_WIP,
    DEFAULT_METRICS_REL,
    DEFAULT_PICK_FROM,
    DEFAULT_WIP_LIMIT,
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    board_config_path,
    compute_metrics,
    default_board_config,
    ensure_board_config,
    hours_between,
    load_board,
    load_metrics_file,
    metrics_path,
    parse_progress_events,
    normalize_status,
    pick_next_task,
    save_board,
    set_wip_limit,
    task_blocked_since,
    task_completed_at,
    task_created_at,
    task_id_day_utc,
    wip_tasks,
    write_metrics,
    _avg,
    _median,
    _max_or_none,
    _normalize_autopilot,
    _normalize_board,
    _require_bool,
    _require_status_list,
    _require_positive_int,
    _require_window_days,
    _validate_metrics_rel,
)
from agentized.context_paths import path_under, require_safe_rel, under_context
from agentized.tasks import list_tasks, render_task_file

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
EXPECTED_DEFAULT = {
    "version": 1,
    "wip_limit": 3,
    "autopilot": {
        "enabled": True,
        "pick_from": ["queue", "open"],
        "count_as_wip": ["in-progress", "self-review"],
    },
    "metrics": {"throughput_window_days": 7, "output": "board/metrics.json"},
}
PICK_KEYS = {"ok", "wip_limit", "wip_current", "under_limit", "enabled", "task", "reason"}
EMPTY_COUNTS = {
    s: 0
    for s in (
        "idea",
        "open",
        "queue",
        "in-progress",
        "self-review",
        "for-review",
        "blocked",
        "done",
        "canceled",
        "other",
    )
}

def _write_task(tasks, task_id, title, *, status, progress=None):
    text = render_task_file(task_id, title, status=status)
    if progress:
        text = text.replace("_(append-only)_", "\n".join(f"- {x}" for x in progress))
    path = tasks / f"{task_id}.md"
    path.write_text(text, encoding="utf-8")
    return path

def _cfg(**kw):
    base = {
        "wip_limit": 2,
        "autopilot": {"enabled": True, "pick_from": ["open"], "count_as_wip": ["in-progress"]},
        "metrics": {"throughput_window_days": 5, "output": "board/metrics.json"},
    }
    base.update(kw)
    return base

def test_defaults_helpers_normalize():
    assert default_board_config() == EXPECTED_DEFAULT
    assert (DEFAULT_WIP_LIMIT, DEFAULT_WINDOW_DAYS, DEFAULT_METRICS_REL) == (3, 7, "board/metrics.json")
    assert DEFAULT_PICK_FROM == ["queue", "open"]
    assert DEFAULT_COUNT_AS_WIP == ["in-progress", "self-review"]
    assert "queue" in BOARD_STATUSES and "canceled" in BOARD_STATUSES
    assert _require_positive_int(1, field="wip_limit") == 1
    assert _require_positive_int(5, field="wip_limit") == 5
    with pytest.raises(ValueError) as e0:
        _require_positive_int(0, field="wip_limit")
    assert e0.value.args == ("wip_limit must be >= 1",)
    with pytest.raises(ValueError) as e1:
        _require_positive_int("nope", field="throughput_window_days")
    assert e1.value.args == ("throughput_window_days must be >= 1",)
    assert normalize_status(None) == normalize_status("  ") == ""
    assert normalize_status("dropped") == "canceled"
    assert normalize_status("queued") == "queue"
    assert _require_bool(True, field="autopilot.enabled") is True
    with pytest.raises(ValueError) as eb:
        _require_bool("false", field="autopilot.enabled")
    assert eb.value.args == ("autopilot.enabled must be a boolean",)
    assert _require_status_list(["open", "dropped"], field="autopilot.pick_from") == [
        "open",
        "canceled",
    ]
    with pytest.raises(ValueError) as e_empty:
        _require_status_list([], field="autopilot.count_as_wip")
    assert e_empty.value.args == (
        "autopilot.count_as_wip must be a non-empty list of canonical statuses",
    )
    with pytest.raises(ValueError) as e_ty:
        _require_status_list(["in_progres"], field="autopilot.count_as_wip")
    assert e_ty.value.args == ("autopilot.count_as_wip: unknown status 'in_progres'",)
    with pytest.raises(ValueError) as e_ns:
        _require_status_list([1], field="autopilot.count_as_wip")
    assert e_ns.value.args == ("autopilot.count_as_wip entries must be strings",)
    assert _avg([]) is None and _avg([2.0, 4.0]) == 3.0
    assert _median([]) is None and _median([1.0, 3.0, 2.0]) == 2.0
    assert _max_or_none([]) is None and _max_or_none([1.0, 9.0]) == 9.0
    assert _validate_metrics_rel(None) == "board/metrics.json"
    assert _validate_metrics_rel("a/b.json") == "a/b.json"
    for bad in ("/abs.json", "foo/../bar.json", ""):
        with pytest.raises(ValueError) as ex:
            _validate_metrics_rel(bad)
        assert ex.value.args == ("metrics.output must be a safe relative path",)
    with pytest.raises(ValueError) as enone:
        require_safe_rel(None, field="context")
    assert enone.value.args == ("context must be a safe relative path",)
    assert _require_window_days(7) == 7
    assert _require_window_days(MAX_WINDOW_DAYS) == MAX_WINDOW_DAYS
    with pytest.raises(ValueError) as emax:
        _require_window_days(MAX_WINDOW_DAYS + 1)
    assert emax.value.args == (f"throughput_window_days must be <= {MAX_WINDOW_DAYS}",)
    with pytest.raises(ValueError) as eo:
        _normalize_board(default_board_config(), ["x"])  # type: ignore[arg-type]
    assert eo.value.args == ("board.json must be a JSON object",)
    with pytest.raises(ValueError) as ew:
        _normalize_board(default_board_config(), {"wip_limit": 0})
    assert ew.value.args == ("wip_limit must be >= 1",)
    with pytest.raises(ValueError) as ewin:
        _normalize_board(default_board_config(), {"metrics": {"throughput_window_days": -3}})
    assert ewin.value.args == ("throughput_window_days must be >= 1",)
    with pytest.raises(ValueError) as ehuge:
        _normalize_board(
            default_board_config(),
            {"metrics": {"throughput_window_days": MAX_WINDOW_DAYS + 1}},
        )
    assert ehuge.value.args == (f"throughput_window_days must be <= {MAX_WINDOW_DAYS}",)
    with pytest.raises(ValueError) as eout:
        _normalize_board(default_board_config(), {"metrics": {"output": "/abs/out.json"}})
    assert eout.value.args == ("metrics.output must be a safe relative path",)
    with pytest.raises(ValueError) as eauto:
        _normalize_board(default_board_config(), {"autopilot": "bad"})
    assert eauto.value.args == ("autopilot must be an object",)
    soft_m = _normalize_board(default_board_config(), {"metrics": "bad"})
    assert soft_m["metrics"] == {"throughput_window_days": 7, "output": DEFAULT_METRICS_REL}
    with pytest.raises(ValueError):
        _normalize_board(
            default_board_config(),
            {
                "autopilot": {
                    "enabled": "false",
                    "pick_from": ["open"],
                    "count_as_wip": ["in-progress"],
                }
            },
        )
    with pytest.raises(ValueError):
        _normalize_board(
            default_board_config(),
            {
                "autopilot": {
                    "enabled": True,
                    "pick_from": ["open"],
                    "count_as_wip": ["in_progres"],
                }
            },
        )
    assert _normalize_autopilot(None)["pick_from"] == DEFAULT_PICK_FROM
    with pytest.raises(ValueError) as e_en:
        _normalize_autopilot(
            {"enabled": "x", "pick_from": ["open"], "count_as_wip": ["in-progress"]}
        )
    assert e_en.value.args == ("autopilot.enabled must be a boolean",)
    with pytest.raises(ValueError) as e_pf:
        _normalize_autopilot(
            {"enabled": True, "pick_from": [], "count_as_wip": ["in-progress"]}
        )
    assert e_pf.value.args == (
        "autopilot.pick_from must be a non-empty list of canonical statuses",
    )
    with pytest.raises(ValueError) as e_cw:
        _normalize_autopilot(
            {"enabled": True, "pick_from": ["open"], "count_as_wip": ["nope"]}
        )
    assert e_cw.value.args == ("autopilot.count_as_wip: unknown status 'nope'",)
    missing = _normalize_board(
        default_board_config(),
        {"autopilot": {"pick_from": ["open"], "count_as_wip": ["in-progress"]}},
    )
    assert missing["autopilot"]["enabled"] is True
    coerced = _normalize_board(default_board_config(), {"wip_limit": "4"})
    assert coerced["wip_limit"] == 4 and type(coerced["wip_limit"]) is int
    assert set(k for k in coerced if "wip" in k.lower()) == {"wip_limit"}
    custom = _normalize_board(
        default_board_config(),
        {
            "wip_limit": 4,
            "autopilot": {"enabled": False, "pick_from": ["idea"], "count_as_wip": ["blocked"]},
            "metrics": {"throughput_window_days": 5, "output": "deep/out.json"},
        },
    )
    assert custom["wip_limit"] == 4
    assert custom["autopilot"] == {
        "enabled": False,
        "pick_from": ["idea"],
        "count_as_wip": ["blocked"],
    }
    assert custom["metrics"] == {"throughput_window_days": 5, "output": "deep/out.json"}

def test_board_io_fail_closed(tmp_path: Path):
    assert load_board(tmp_path, "context") == EXPECTED_DEFAULT
    info = ensure_board_config(tmp_path, "context")
    assert info == {"path": "context/board.json", "created": True}
    assert ensure_board_config(tmp_path, "context")["created"] is False
    assert board_config_path(tmp_path, "context") == (
        tmp_path / "context" / "board.json"
    ).resolve()
    (tmp_path / "context" / "board.json").write_text("{bad", encoding="utf-8")
    save_board(tmp_path, default_board_config(), "okctx")
    assert ensure_board_config(tmp_path, "okctx")["created"] is False
    with pytest.raises((OSError, ValueError, TypeError)):
        ensure_board_config(tmp_path, "context")
    save_board(tmp_path, default_board_config(), "context")
    nested = tmp_path / "deep"
    save_board(nested, {"wip_limit": 4}, "ctx/sub")
    assert (nested / "ctx" / "sub" / "board.json").is_file()
    assert ensure_board_config(tmp_path, "brandnew") == {
        "path": "brandnew/board.json",
        "created": True,
    }
    assert (tmp_path / "brandnew" / "board.json").is_file()
    assert load_board(tmp_path, "brandnew")["wip_limit"] == DEFAULT_WIP_LIMIT
    bad = tmp_path / "context" / "board.json"
    bad.write_text("{not-json", encoding="utf-8")
    with pytest.raises((OSError, ValueError, TypeError)):
        load_board(tmp_path, "context")
    bad.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_board(tmp_path, "context")
    save_board(tmp_path, default_board_config(), "context")
    set_wip_limit(tmp_path, 1, context_rel="context")
    assert load_board(tmp_path, "context")["wip_limit"] == 1
    set_wip_limit(tmp_path, 5, context_rel="context")
    assert load_board(tmp_path, "context")["wip_limit"] == 5
    with pytest.raises(ValueError) as ex:
        set_wip_limit(tmp_path, 0, context_rel="context")
    assert ex.value.args == ("wip_limit must be >= 1",)
    save_board(
        tmp_path,
        {"wip_limit": 9, "metrics": {"throughput_window_days": 5, "output": "other/metrics.json"}},
        "otherctx",
    )
    returned = set_wip_limit(tmp_path, 4, context_rel="otherctx")
    assert returned["wip_limit"] == 4
    assert returned["metrics"]["output"] == "other/metrics.json"
    assert load_board(tmp_path, "context")["wip_limit"] == 5
    cfg = load_board(tmp_path, "context")
    assert metrics_path(tmp_path, cfg, "context") == (
        tmp_path / "context" / "board" / "metrics.json"
    ).resolve()
    assert metrics_path(tmp_path, {"metrics": {"output": None}}, "context").name == "metrics.json"
    assert metrics_path(tmp_path, {"metrics": "bad"}, "context") == (
        tmp_path / "context" / "board" / "metrics.json"
    ).resolve()
    for bad_out in ("", "../escape.json"):
        with pytest.raises(ValueError):
            metrics_path(tmp_path, {"metrics": {"output": bad_out}}, "context")
    assert metrics_path(tmp_path, {"metrics": {"output": "custom/out.json"}}, "context") == (
        tmp_path / "context" / "custom" / "out.json"
    ).resolve()
    for bad_ctx in ("", "/abs", "context/../../outside", "../escape"):
        with pytest.raises(ValueError) as ec:
            board_config_path(tmp_path, bad_ctx)
        assert ec.value.args == ("context must be a safe relative path",)
        with pytest.raises(ValueError):
            save_board(tmp_path, default_board_config(), bad_ctx)
        with pytest.raises(ValueError):
            write_metrics(tmp_path, context_rel=bad_ctx, now=NOW)
    # symlink context dir outside repo root
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_root = tmp_path / "outside-root"
    outside_root.mkdir()
    (repo / "context").symlink_to(outside_root)
    with pytest.raises(ValueError) as eroot:
        board_config_path(repo, "context")
    assert eroot.value.args == ("context path escapes repository root",)
    # symlink parent under context must not write outside
    leak_root = tmp_path / "leak"
    leak_root.mkdir()
    (leak_root / "context").mkdir()
    outside = leak_root / "outside"
    outside.mkdir()
    (leak_root / "context" / "board").symlink_to(outside)
    with pytest.raises(ValueError) as esym:
        under_context(leak_root, "context", "board", "metrics.json")
    assert esym.value.args == ("path escapes context directory",)
    with pytest.raises(ValueError):
        write_metrics(leak_root, context_rel="context", now=NOW)
    assert list(outside.iterdir()) == []

def test_progress_parsers():
    text = (
        "- 2026-99-99 99:99 UTC: junk\n"
        "- bad line\n"
        "- 2026-11-10 08:00 UTC: claim by a\n"
        "- 2026-11-11 10:00 UTC: статус → blocked\n"
        "- 2026-11-12 12:00 UTC: status → done\n"
        "- 2026-13-40 25:61 UTC: more junk\n"
        "- 2026-11-13 01:00 UTC: note\n"
    )
    events = parse_progress_events(text)
    assert len(events) == 4
    assert [e[0].day for e in events] == [10, 11, 12, 13]
    assert task_completed_at(events).day == 12
    assert task_blocked_since(events).day == 11
    assert task_completed_at(
        parse_progress_events("- 2026-11-12 12:00 UTC: статус → mystery\n")
    ) is None
    assert board_mod._status_from_progress_msg("status → mystery") is None
    assert board_mod._status_from_progress_msg("статус → done") == "done"
    assert task_completed_at([]) is None and task_blocked_since([]) is None
    only = parse_progress_events("- 2026-11-10 08:00 UTC: claim by a\n")
    assert task_completed_at(only) is None and task_blocked_since(only) is None
    assert hours_between(
        datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc),
    ) == 2.0
    assert hours_between(
        datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc),
    ) == 0.0
    assert task_id_day_utc("T-261116-abcd") == datetime(2026, 11, 16, tzinfo=timezone.utc)
    assert task_id_day_utc("nope") is None
    assert task_id_day_utc("T-999999-abcd") is None
    assert task_created_at("T-261110-aaa", events).day == 10

def test_wip_and_autopilot(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    seeds = [
        ("T-261114-old", "Older", "open", ["2026-11-14 09:00 UTC: opened"]),
        ("T-261115-new", "Newer", "open", ["2026-11-15 09:00 UTC: opened"]),
        ("T-261113-wip", "Active", "in-progress", None),
        ("T-261112-blk", "Blocked", "blocked", None),
        ("T-261111-idea", "Idea", "idea", None),
        ("T-261112-sr", "Self", "self-review", None),
    ]
    for tid, title, st, prog in seeds:
        _write_task(tasks, tid, title, status=st, progress=prog)
    all_tasks = list_tasks(tasks)
    cfg = _cfg()
    assert [t.task_id for t in wip_tasks(all_tasks, cfg)] == ["T-261113-wip"]
    assert {t.task_id for t in wip_tasks(all_tasks, {"autopilot": {}})} == {
        "T-261113-wip",
        "T-261112-sr",
    }
    with pytest.raises(ValueError):
        wip_tasks(all_tasks, {"autopilot": "bad"})
    assert [
        t.task_id
        for t in wip_tasks(
            all_tasks,
            {"autopilot": {"enabled": True, "pick_from": ["open"], "count_as_wip": ["blocked"]}},
        )
    ] == ["T-261112-blk"]
    pick = pick_next_task(all_tasks, cfg, now=NOW)
    assert set(pick) == PICK_KEYS
    assert pick["ok"] is True
    assert pick["task"] == {
        "id": "T-261114-old",
        "title": "Older",
        "status": "open",
        "path": "T-261114-old.md",
    }
    osp=_write_task(tasks,"T-261115-oldstamp","O",status="open",progress=["2026-11-10 09:00 UTC: opened"])
    nsp=_write_task(tasks,"T-261110-newstamp","N",status="open",progress=["2026-11-15 09:00 UTC: opened"])
    assert pick_next_task([
        SimpleNamespace(task_id="T-261110-newstamp",title="N",status="open",path=nsp),
        SimpleNamespace(task_id="T-261115-oldstamp",title="O",status="open",path=osp),
    ], cfg, now=NOW)["task"]["id"]=="T-261115-oldstamp"
    drp=_write_task(tasks,"T-261110-drpick","Dr",status="dropped")
    assert pick_next_task(
        [SimpleNamespace(task_id="T-261110-drpick",title="Dr",status="dropped",path=drp)],
        _cfg(wip_limit=5,autopilot={"enabled":True,"pick_from":["canceled"],"count_as_wip":["in-progress"]}),
        now=NOW,
    )["task"]["status"]=="canceled"
    assert pick["reason"] == "picked oldest open under WIP"
    assert pick_next_task(
        all_tasks,
        {"wip_limit": 2, "autopilot": {"pick_from": ["open"], "count_as_wip": ["in-progress"]}, "metrics": {}},
        now=NOW,
    )["enabled"] is True
    with pytest.raises(ValueError):
        pick_next_task(all_tasks, {"wip_limit": 2, "autopilot": "x", "metrics": {}}, now=NOW)
    cfg_no = {
        "autopilot": {"enabled": True, "pick_from": ["open"], "count_as_wip": ["in-progress"]},
        "metrics": {"throughput_window_days": 5, "output": "board/metrics.json"},
    }
    assert pick_next_task(all_tasks, cfg_no, now=NOW)["wip_limit"] == 3
    with pytest.raises(ValueError) as ep:
        pick_next_task(all_tasks, {**cfg_no, "wip_limit": 0}, now=NOW)
    assert ep.value.args == ("wip_limit must be >= 1",)
    assert (
        pick_next_task(
            all_tasks,
            _cfg(wip_limit=5, autopilot={"enabled": True, "pick_from": ["idea"], "count_as_wip": ["in-progress"]}),
            now=NOW,
        )["task"]["id"]
        == "T-261111-idea"
    )
    full = pick_next_task(all_tasks, _cfg(wip_limit=1), now=NOW)
    assert full["task"] is None and full["under_limit"] is False
    assert "WIP at limit" in full["reason"]
    disabled = pick_next_task(
        all_tasks,
        _cfg(wip_limit=5, autopilot={"enabled": False, "pick_from": ["open"], "count_as_wip": ["in-progress"]}),
        now=NOW,
    )
    assert disabled["reason"] == "autopilot disabled" and disabled["task"] is None
    assert pick_next_task([], cfg, now=NOW)["reason"] == "no pickable tasks"
    nd=_write_task(tasks,"T-999999-noday","NoDay",status="open")
    od=_write_task(tasks,"T-261114-dated","Dated",status="open",progress=["2026-11-14 09:00 UTC: opened"])
    assert pick_next_task([
        SimpleNamespace(task_id="T-999999-noday",title="NoDay",status="open",path=nd),
        SimpleNamespace(task_id="T-261114-dated",title="Dated",status="open",path=od),
    ], cfg, now=NOW)["task"]["id"]=="T-261114-dated"

def test_metrics_oracle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, ctx = tmp_path, tmp_path / "context"
    tasks = ctx / "tasks"
    tasks.mkdir(parents=True)
    ensure_board_config(root, "context")
    save_board(
        root,
        {"wip_limit": 2, "metrics": {"throughput_window_days": 5, "output": "board/metrics.json"}},
        "context",
    )
    with pytest.raises(ValueError) as ecm:
        compute_metrics(
            tasks,
            {"wip_limit": 0, "metrics": {"throughput_window_days": 5, "output": "board/metrics.json"}},
            now=NOW,
        )
    assert ecm.value.args == ("wip_limit must be >= 1",)
    with pytest.raises(ValueError) as ewin:
        compute_metrics(
            tasks,
            {"wip_limit": 2, "metrics": {"throughput_window_days": 0, "output": "board/metrics.json"}},
            now=NOW,
        )
    assert ewin.value.args == ("throughput_window_days must be >= 1",)
    seeds = [
        (
            "T-261110-done",
            "Finished",
            "done",
            ["2026-11-10 08:00 UTC: claim by a", "2026-11-12 08:00 UTC: статус → done"],
        ),
        (
            "T-261113-done2",
            "Finished2",
            "done",
            ["2026-11-13 08:00 UTC: claim by a", "2026-11-13 08:00 UTC: статус → done"],
        ),
        (
            "T-261111-edge",
            "Edge",
            "done",
            ["2026-11-11 08:00 UTC: claim by a", "2026-11-11 12:00 UTC: статус → done"],
        ),
        (
            "T-261101-olddone",
            "Old",
            "done",
            ["2026-11-01 08:00 UTC: claim by a", "2026-11-02 08:00 UTC: статус → done"],
        ),
        ("T-261114-open", "Queued", "open", ["2026-11-14 12:00 UTC: opened"]),
        ("T-261116-qeq", "Qeq", "open", ["2026-11-16 12:00 UTC: opened"]),
        (
            "T-261115-block",
            "Stuck",
            "blocked",
            ["2026-11-15 06:00 UTC: claim by b", "2026-11-15 12:00 UTC: статус → blocked"],
        ),
        ("T-261116-bleq", "Bleq", "blocked", ["2026-11-16 12:00 UTC: статус → blocked"]),
        ("T-261114-blk2", "No stamp", "blocked", ["2026-11-14 08:00 UTC: claim by b"]),
        ("T-261114-fake", "Fake done", "done", ["2026-11-14 08:00 UTC: claim by a"]),
        ("T-261116-dneq", "Dneq", "done", ["2026-11-16 10:00 UTC: claim by a", "2026-11-16 12:00 UTC: статус → done"]),
        ("T-261116-wip", "Working", "in-progress", None),
        ("T-261110-drop", "Weird", "dropped", None),
        ("T-261110-xx", "Other", "mystery", None),
        ("T-261110-yy", "Other2", "weird", None),
        ("T-999999-noday", "NoDay", "open", None),
    ]
    for tid, title, st, prog in seeds:
        _write_task(tasks, tid, title, status=st, progress=prog)
    cfg = load_board(root, "context")
    metrics = compute_metrics(tasks, cfg, now=NOW)
    assert set(metrics) == {
        "version",
        "generated_at",
        "wip",
        "counts",
        "throughput",
        "cycle_time",
        "queue_age",
        "blocked_age",
        "timing_source",
        "next_task",
        "autopilot",
    }
    assert metrics["timing_source"] == "progress_status_arrows"
    assert metrics["version"] == 1
    assert metrics["generated_at"] == "2026-11-16T12:00:00Z"
    assert metrics["counts"]["done"] == 6
    assert metrics["counts"]["blocked"] == 3
    assert metrics["counts"]["in-progress"] == 1
    assert metrics["counts"]["open"] == 3
    assert metrics["counts"]["canceled"] == 1
    assert metrics["counts"]["other"] == 2
    assert metrics["throughput"] == {"window_days": 5, "done_count": 4, "per_day": 0.8}
    m7=compute_metrics(tasks,{**cfg,"metrics":{"throughput_window_days":7,"output":"board/metrics.json"}},now=NOW)
    assert m7["throughput"]["per_day"]==round(m7["throughput"]["done_count"]/7.0,4)
    assert metrics["cycle_time"] == {
        "samples": 5,
        "avg_hours": (48.0 + 0.0 + 4.0 + 24.0 + 2.0) / 5,
        "p50_hours": 4.0,
    }
    assert metrics["queue_age"] == {"samples": 2, "avg_hours": 24.0, "max_hours": 48.0}
    assert metrics["blocked_age"] == {"samples": 2, "avg_hours": 12.0, "max_hours": 24.0}
    assert metrics["wip"] == {
        "limit": 2,
        "current": 1,
        "under_limit": True,
        "task_ids": ["T-261116-wip"],
    }
    assert metrics["next_task"]["id"] == "T-261114-open"
    assert metrics["autopilot"] == {"enabled": True, "reason": "picked oldest open under WIP"}
    # omitted defaults + non-dict sections
    bare = compute_metrics(
        tasks,
        {"autopilot": {}, "metrics": {"output": "board/metrics.json"}},
        now=NOW,
    )
    assert bare["wip"]["limit"] == DEFAULT_WIP_LIMIT
    assert bare["throughput"]["window_days"] == DEFAULT_WINDOW_DAYS
    assert bare["autopilot"]["enabled"] is True
    with pytest.raises(ValueError):
        compute_metrics(
            tasks,
            {"wip_limit": 3, "autopilot": "bad", "metrics": "bad"},
            now=NOW,
        )
    soft_m = compute_metrics(
        tasks,
        {"wip_limit": 3, "autopilot": {}, "metrics": "bad"},
        now=NOW,
    )
    assert soft_m["throughput"]["window_days"] == DEFAULT_WINDOW_DAYS
    assert soft_m["autopilot"]["enabled"] is True
    disabled_m = compute_metrics(
        tasks,
        {
            "wip_limit": 3,
            "autopilot": {
                "enabled": False,
                "pick_from": ["open"],
                "count_as_wip": ["in-progress"],
            },
            "metrics": {"throughput_window_days": 5, "output": "board/metrics.json"},
        },
        now=NOW,
    )
    assert disabled_m["autopilot"] == {"enabled": False, "reason": "autopilot disabled"}
    m_full = compute_metrics(tasks, {**cfg, "wip_limit": 1}, now=NOW)
    assert m_full["wip"]["under_limit"] is False
    assert m_full["autopilot"]["reason"] == "WIP at limit (1/1)"
    # write_metrics pins board.json even when connect does not
    (root / "context" / "board.json").unlink(missing_ok=True)
    written = write_metrics(root, context_rel="context", now=NOW)
    assert (root / "context" / "board.json").is_file()
    assert written["path"] == "context/board/metrics.json"
    assert written["metrics"]["generated_at"] == "2026-11-16T12:00:00Z"
    assert load_metrics_file(root, "context") == written["metrics"]
    # context_rel must reach ensure_board_config (not DEFAULT only)
    fresh = tmp_path / "fresh-root"
    fresh.mkdir()
    (fresh / "solo" / "tasks").mkdir(parents=True)
    pinned = write_metrics(fresh, context_rel="solo", now=NOW)
    assert pinned["path"] == "solo/board/metrics.json"
    assert (fresh / "solo" / "board.json").is_file()
    assert not (fresh / "context" / "board.json").exists()
    (ctx / "board" / "metrics.json").write_text("{bad", encoding="utf-8")
    with pytest.raises((OSError, ValueError, TypeError)):
        load_metrics_file(root, "context")
    (ctx / "board" / "metrics.json").write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_metrics_file(root, "context")
    (ctx / "board" / "metrics.json").unlink()
    assert load_metrics_file(root, "context") is None

    empty = compute_metrics(tmp_path / "missing-tasks", default_board_config(), now=NOW)
    assert empty["counts"] == EMPTY_COUNTS
    assert empty["autopilot"]["reason"] == "no pickable tasks"
    assert empty["generated_at"] == "2026-11-16T12:00:00Z"
    bad_path = tmp_path / "T-261114-bin.md"
    bad_path.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(ValueError) as eutf:
        board_mod._task_events(SimpleNamespace(path=bad_path))
    assert eutf.value.args == ("T-261114-bin.md: not valid UTF-8",)
    assert board_mod._task_events(SimpleNamespace(path=tmp_path / "missing.md")) == []
    _write_task(fresh/"solo"/"tasks","T-261114-solo","Solo",status="open")
    lb_calls: list[str] = []
    real_lb = board_mod.load_board
    def _lb(root_arg, context_rel="context"):
        lb_calls.append(context_rel)
        return real_lb(root_arg, context_rel)
    monkeypatch.setattr(board_mod, "load_board", _lb)
    pinned2 = write_metrics(fresh, context_rel="solo", now=NOW)
    assert lb_calls[-1] == "solo"
    assert pinned2["metrics"]["counts"]["open"] == 1
    lb_calls.clear()
    assert load_metrics_file(fresh, "solo")["counts"]["open"] == 1
    assert lb_calls == ["solo"]
    monkeypatch.setattr(board_mod, "load_board", real_lb)
    fixed = datetime(2026, 11, 17, 8, 30, tzinfo=timezone.utc)
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return fixed
    monkeypatch.setattr(board_mod, "datetime", _FixedDateTime)
    assert write_metrics(root, context_rel="context")["metrics"]["generated_at"] == "2026-11-17T08:30:00Z"
    monkeypatch.setattr(board_mod, "datetime", datetime)
    monkeypatch.setattr(board_mod, "pick_next_task", lambda *a, **k: {"ok": True, "task": None})
    assert compute_metrics(tasks, cfg, now=NOW)["autopilot"]["reason"] == ""
    monkeypatch.setattr(board_mod, "pick_next_task", pick_next_task)
    good_path = tmp_path / "T-261114-ok.md"
    good_path.write_text("- 2026-11-14 09:00 UTC: opened\n", encoding="utf-8")
    seen: dict = {}
    real_read = Path.read_text
    def _cap(self, *a, **k):
        seen.clear(); seen.update(k); return real_read(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", _cap)
    assert board_mod._task_events(SimpleNamespace(path=good_path))[0][1] == "opened"
    assert seen == {"encoding": "utf-8"}
