"""CLI context confinement + autopilot commands (AGE-61 / #19B)."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

import agentized_cli as cli


def _repo(tmp_path: Path, name: str = "repo"):
    repo = tmp_path / name
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def _ctx_ns(context: str = "context", **kw):
    return argparse.Namespace(context=context, **kw)


def test_ctx_index_child_symlinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ValueError) as exc:
        cli._ctx(tmp_path, _ctx_ns("../outside"))
    assert exc.value.args == ("context must be a safe relative path",)
    repo = _repo(tmp_path)
    outside = tmp_path / "outside"
    (outside / "tasks").mkdir(parents=True)
    (outside / "leases").mkdir(parents=True)
    keep = outside / "tasks" / "KEEP.md"
    keep.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo)
    assert cli.cmd_index(_ctx_ns("../outside", print=False)) == 1
    assert keep.read_text(encoding="utf-8") == "keep"
    (repo / "context").symlink_to(outside)
    assert cli.cmd_index(_ctx_ns("context", print=False)) == 1
    repo3 = _repo(tmp_path, "repo3")
    (repo3 / "context" / "tasks").mkdir(parents=True)
    (repo3 / "context" / "leases").mkdir(parents=True)
    out3 = tmp_path / "out3"
    out3.mkdir()
    target = out3 / "INDEX.md"
    target.write_text("sentinel", encoding="utf-8")
    (repo3 / "context" / "tasks" / "INDEX.md").symlink_to(target)
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo3)
    assert cli.cmd_index(_ctx_ns("context", print=False)) == 1
    assert target.read_text(encoding="utf-8") == "sentinel"


def test_autopilot_cli_reads_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    repo = _repo(tmp_path)
    ctx = repo / "context"
    (ctx / "tasks").mkdir(parents=True)
    (ctx / "leases").mkdir(parents=True)
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo)

    # show / next / metrics: no board.json create
    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="show")) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["wip_limit"] == 3
    assert not (ctx / "board.json").exists()
    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="next", json=False)) == 0
    assert "next: none" in capsys.readouterr().out
    assert not (ctx / "board.json").exists()
    assert {p.name for p in ctx.iterdir()} == {"tasks", "leases"}
    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="next", json=True)) == 0
    pick = json.loads(capsys.readouterr().out)
    assert pick["ok"] is True and pick.get("task") is None
    assert pick.get("reason") == "no pickable tasks"
    assert not (ctx / "board.json").exists()
    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="metrics", refresh=False)) == 0
    assert json.loads(capsys.readouterr().out) is None
    assert not (ctx / "board.json").exists()
    assert not (ctx / "board").exists()

    # set-wip creates board.json; ± round-trip
    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="set-wip", limit=2)) == 0
    assert "wip_limit → 2" in capsys.readouterr().out
    assert (ctx / "board.json").is_file()
    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="set-wip", limit=5)) == 0
    assert "wip_limit → 5" in capsys.readouterr().out
    assert json.loads((ctx / "board.json").read_text(encoding="utf-8"))["wip_limit"] == 5

    # refresh --json writes metrics; metrics --refresh refreshes
    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="refresh", json=True)) == 0
    out = capsys.readouterr().out
    assert "metrics → context/board/metrics.json" in out
    assert (ctx / "board" / "metrics.json").is_file()
    body = out.split("\n", 1)[1]
    assert json.loads(body)["wip"]["limit"] == 5
    (ctx / "board" / "metrics.json").unlink()
    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="metrics", refresh=True)) == 0
    assert (ctx / "board" / "metrics.json").is_file()
    assert json.loads(capsys.readouterr().out)["wip"]["limit"] == 5

    # index prints metrics path + writes metrics.json
    (ctx / "board" / "metrics.json").unlink()
    assert cli.cmd_index(_ctx_ns(print=False)) == 0
    idx_out = capsys.readouterr().out
    assert "context/board/metrics.json" in idx_out
    assert (ctx / "board" / "metrics.json").is_file()

    # ValueError → exit 1 + stderr
    err = io.StringIO()
    monkeypatch.setattr("sys.stderr", err)
    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="set-wip", limit=0)) == 1
    assert "wip_limit must be an integer >= 1" in err.getvalue()


def test_autopilot_next_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from agentized.tasks import render_task_file

    repo = _repo(tmp_path, "next-happy")
    ctx = repo / "context"
    tasks = ctx / "tasks"
    tasks.mkdir(parents=True)
    (ctx / "leases").mkdir(parents=True)
    tid, title = "T-261121-next", "Pick Me"
    (tasks / f"{tid}.md").write_text(render_task_file(tid, title, status="queue"), encoding="utf-8")
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo)

    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="next", json=False)) == 0
    text = capsys.readouterr().out
    assert text.strip() == f"next: {tid} — {title} (WIP 0/3)"
    assert not (ctx / "board.json").exists()

    assert cli.cmd_autopilot(_ctx_ns(autopilot_cmd="next", json=True)) == 0
    pick = json.loads(capsys.readouterr().out)
    assert pick["ok"] is True
    assert pick["task"]["id"] == tid
    assert pick["task"]["title"] == title
    assert pick["wip_current"] == 0 and pick["wip_limit"] == 3
    assert not (ctx / "board.json").exists()
