from __future__ import annotations

from pathlib import Path
import pytest
from agentized.hook_common import context_rel, extract_paths, lease_warn_for_paths, nav_reminder, read_stdin_json, resolve_root
from agentized.leases import find_overlaps, list_leases, parse_lease, path_overlaps, rebuild_lease_index, render_lease_file, warn_message
from agentized.paths import DEFAULT_CONTEXT, context_dir, find_repo_root, load_state, save_state, state_path
from agentized.quality import DEFAULT_COVERAGE_PCT, default_quality_config, load_quality, module_thresholds, quality_path, save_quality, set_coverage_threshold
from agentized.tasks import allocate_task_id, append_progress, list_tasks, parse_task, rebuild_task_index, render_task_file, set_field


def test_paths_and_state(tmp_path: Path, monkeypatch):
    (tmp_path / ".git").mkdir(); nested = tmp_path / "a" / "b"; nested.mkdir(parents=True)
    monkeypatch.chdir(nested); assert find_repo_root() == tmp_path.resolve()
    (tmp_path / "AGENTS.md").write_text("# x\n", encoding="utf-8")
    assert context_dir(tmp_path).name == DEFAULT_CONTEXT and state_path(tmp_path).name == "connect.json"
    assert load_state(tmp_path) == {}; save_state(tmp_path, {"version": "0.1.0"}); assert load_state(tmp_path)["version"] == "0.1.0"


def test_tasks(tmp_path: Path):
    a = allocate_task_id(tmp_path, day="261113"); (tmp_path / f"{a}.md").write_text("x", encoding="utf-8")
    assert allocate_task_id(tmp_path, day="261113") != a
    path = tmp_path / "T-261113-abc.md"
    path.write_text(render_task_file("T-261113-abc", "Demo", status="open", tags="q"), encoding="utf-8")
    meta = parse_task(path); assert meta and meta.status == "open" and "T-261113-abc" in rebuild_task_index(tmp_path)
    path.write_text("no title\nстатус: blocked\n", encoding="utf-8"); assert parse_task(path).status == "blocked"
    (tmp_path / "INDEX.md").write_text("# i\n", encoding="utf-8"); assert parse_task(tmp_path / "INDEX.md") is None
    bad = tmp_path / "notes.md"; bad.write_text("hello\n", encoding="utf-8"); assert parse_task(bad) is None
    base = render_task_file("T-261113-abc", "X")
    assert "in-progress" in set_field(base, "статус", "in-progress")
    assert "did" in append_progress(base, "did") and set_field("", "claim", "x").startswith("claim:")
    assert "## Progress" in append_progress("# T-261113-abc — X\n", "start")


def test_leases(tmp_path: Path):
    assert path_overlaps("runtime", "runtime/x.py") and not path_overlaps("runtime", "docs")
    path = tmp_path / "T-261113-abc.md"
    path.write_text(render_lease_file("T-261113-abc", "alice", ["runtime"]), encoding="utf-8")
    lease = parse_lease(path); assert lease and "runtime" in lease.paths and "T-261113-abc" in rebuild_lease_index(tmp_path)
    (tmp_path / "T-1.md").write_text("task: T-1\nowner: a\nexpires: 2099-01-01T00:00:00Z\nstatus: active\npaths: runtime, docs\n", encoding="utf-8")
    lease2 = parse_lease(tmp_path / "T-1.md"); hits = find_overlaps([lease2], ["runtime/x.py"])
    assert hits and "LEASE WARN" in warn_message(hits) and warn_message([]) == ""
    (tmp_path / "INDEX.md").write_text("# i\n", encoding="utf-8"); assert parse_lease(tmp_path / "INDEX.md") is None
    assert find_overlaps(list_leases(tmp_path), ["runtime"], ignore_task="T-261113-abc") is not None


def test_quality(tmp_path: Path):
    cfg = default_quality_config(); assert cfg["coverage"]["lines"] == DEFAULT_COVERAGE_PCT and cfg["mutation"]["gate"] == "hard"
    assert save_quality(tmp_path, cfg) == quality_path(tmp_path)
    assert set_coverage_threshold(tmp_path, 90)["coverage"]["lines"] == 90.0
    with pytest.raises(ValueError): set_coverage_threshold(tmp_path, 120)
    assert module_thresholds(cfg, {"thresholds": {}})[0] == DEFAULT_COVERAGE_PCT
    assert module_thresholds(cfg, {"thresholds": {"lines": 70, "branches": 65}}) == (70.0, 65.0)
    assert load_quality(tmp_path / "missing")["version"] == 1


def test_hooks(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.stdin", type("S", (), {"read": lambda self: ""})()); assert read_stdin_json() == {}
    monkeypatch.setattr("sys.stdin", type("S", (), {"read": lambda self: "x"})()); assert "_raw" in read_stdin_json()
    (tmp_path / ".git").mkdir(); save_state(tmp_path, {"context": "context"})
    assert resolve_root({"cwd": str(tmp_path)}) == tmp_path.resolve() and context_rel(tmp_path) == "context"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); assert resolve_root({}) == tmp_path.resolve()
    assert "runtime/x.py" in extract_paths({"tool_input": {"file_path": "runtime/x.py", "command": "python3 runtime/agentized_cli.py", "edits": [{"path": "docs/QUALITY.md"}]}})
    ctx = tmp_path / "context"; (ctx / "tasks").mkdir(parents=True); (ctx / "leases").mkdir(parents=True)
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8"); (tmp_path / "AGENTS.md").write_text("see NAV.md\n", encoding="utf-8")
    assert "NAV.md" in nav_reminder(tmp_path)
    (ctx / "leases" / "T-1.md").write_text(render_lease_file("T-1", "a", ["runtime"]), encoding="utf-8")
    assert "LEASE WARN" in lease_warn_for_paths(tmp_path, ["runtime/x.py"]) and lease_warn_for_paths(tmp_path, []) == ""
