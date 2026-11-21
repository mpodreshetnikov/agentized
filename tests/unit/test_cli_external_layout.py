"""CLI external layout branches (outside mutmut module selection — needs agentized_cli)."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("agentized_cli")

import agentized_cli as cli


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


def _ns(**kw):
    base = dict(context="context", harness=["cursor"], coverage=None, json=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _fresh_external(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Code repo + external Context clone (ready); code has context.json only."""
    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(code)
    _git_init(ext)
    (ext / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    (ext / "leases").mkdir()
    (ext / "tasks" / "INDEX.md").write_text("# tasks\n", encoding="utf-8")
    (ext / "leases" / "INDEX.md").write_text("# leases\n", encoding="utf-8")
    ctx = code / "context"
    ctx.mkdir()
    (ctx / "context.json").write_text(
        json.dumps(
            {
                "placement": "external",
                "external": {"path": str(ext), "remote": "git@example/context.git"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return code, ext, ctx


def test_layout_ctx_exits_on_bad_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    ctx = repo / "context"
    ctx.mkdir()
    (ctx / "context.json").write_text('{"placement": "nope"}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli._layout(repo, _ns())
    assert exc.value.code == 1
    assert "context layout error:" in capsys.readouterr().err

    (ctx / "context.json").write_text(
        json.dumps(
            {
                "placement": "external",
                "external": {"path": str(tmp_path / "missing"), "remote": "r"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc2:
        cli._ctx(repo, _ns(), require_ready=True)
    assert exc2.value.code == 1
    assert "context layout error:" in capsys.readouterr().err


def test_fresh_external_connect_bridges_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    code, ext, ctx = _fresh_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)

    assert not (ctx / "tasks").exists()
    assert cli.cmd_connect(_ns()) == 0
    out = capsys.readouterr().out
    assert "connect OK" in out
    assert (ctx / "tasks").is_symlink()
    assert (ctx / "tasks").resolve() == (ext / "tasks").resolve()
    assert (ctx / "leases").is_symlink()
    assert (ctx / "NAV.md").is_symlink()
    gi = (code / ".gitignore").read_text(encoding="utf-8")
    assert "context/tasks" in gi

    # idempotent re-run
    assert cli.cmd_connect(_ns()) == 0
    assert (ctx / "tasks").is_symlink()
    assert (ctx / "tasks").resolve() == (ext / "tasks").resolve()


def test_bridges_error_prints_layout_error_no_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    code, ext, ctx = _fresh_external(tmp_path)
    # Pre-seed conflicting local tasks dir (non-empty) + external tasks exist → conflict
    (ctx / "tasks").mkdir()
    (ctx / "tasks" / "stale.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)
    rc = cli.cmd_connect(_ns())
    err = capsys.readouterr().err
    assert rc == 1
    assert "context layout error:" in err
    assert "Traceback" not in err


def test_check_process_control_and_external_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    code, ext, ctx = _fresh_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)
    assert cli.cmd_connect(_ns()) == 0
    capsys.readouterr()

    # Missing process-control.json is a hard error
    pc = ctx / "process-control.json"
    assert pc.exists()
    pc.unlink()
    assert cli.cmd_check(_ns()) == 1
    err_out = capsys.readouterr().out + capsys.readouterr().err
    assert "process-control.json" in err_out
    assert "check FAIL" in err_out

    # Restore via reconnect pins
    assert cli.cmd_connect(_ns()) == 0
    capsys.readouterr()
    assert cli.cmd_check(_ns()) == 0
    ok = capsys.readouterr().out
    assert "check OK" in ok
    assert "placement: external" in ok

    # Broken external clone → check fail
    import shutil

    shutil.rmtree(ext / "tasks")
    assert cli.cmd_check(_ns()) == 1


def test_lease_and_sync_status_use_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    code, ext, ctx = _fresh_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)
    assert cli.cmd_connect(_ns()) == 0
    capsys.readouterr()

    assert (
        cli.cmd_lease(
            _ns(
                lease_cmd="acquire",
                task_id="T-261121-lease",
                owner="age25",
                paths=["runtime/agentized_cli.py"],
            )
        )
        == 0
    )
    # lease file lives in external registry
    assert (ext / "leases" / "T-261121-lease.md").exists()
    assert cli.cmd_lease(_ns(lease_cmd="list")) == 0
    listed = capsys.readouterr().out
    assert "T-261121-lease" in listed

    assert cli.cmd_sync_status(_ns()) == 0
    sync = capsys.readouterr().out
    assert "placement: external" in sync
    assert "active leases: 1" in sync


def test_connect_bridges_after_connect_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bridges must run only after connect() succeeds (no orphan bridges on failure)."""
    code, ext, ctx = _fresh_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)

    calls: list[str] = []
    real_connect = cli.connect

    def boom(*a, **k):
        calls.append("connect")
        raise RuntimeError("connect failed")

    monkeypatch.setattr(cli, "connect", boom)
    with pytest.raises(RuntimeError, match="connect failed"):
        cli.cmd_connect(_ns())
    assert calls == ["connect"]
    assert not (ctx / "tasks").exists()

    monkeypatch.setattr(cli, "connect", real_connect)
    order: list[str] = []

    def wrap_connect(*a, **k):
        order.append("connect")
        return real_connect(*a, **k)

    from agentized import context_layout as cl

    real_bridges = cl.ensure_code_context_bridges

    def wrap_bridges(layout):
        order.append("bridges")
        return real_bridges(layout)

    monkeypatch.setattr(cli, "connect", wrap_connect)
    monkeypatch.setattr(cl, "ensure_code_context_bridges", wrap_bridges)
    # cmd_connect imports ensure_code_context_bridges locally — patch where used
    import agentized.context_layout as layout_mod

    monkeypatch.setattr(layout_mod, "ensure_code_context_bridges", wrap_bridges)
    assert cli.cmd_connect(_ns()) == 0
    assert order == ["connect", "bridges"]
