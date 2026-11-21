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


def _empty_external(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Code repo + EMPTY external git clone (no NAV/tasks seed); context.json only."""
    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(code)
    _git_init(ext)
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


def test_empty_external_connect_check_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    code, ext, ctx = _empty_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)

    assert not (ext / "NAV.md").exists()
    assert not (ctx / "tasks").exists()
    assert cli.cmd_connect(_ns()) == 0
    out = capsys.readouterr().out
    assert "connect OK" in out
    assert (ext / "NAV.md").is_file()
    assert (ext / "tasks" / "INDEX.md").is_file()
    assert (ext / "leases" / "INDEX.md").is_file()
    assert (ctx / "tasks").is_symlink()
    assert (ctx / "tasks").resolve() == (ext / "tasks").resolve()
    assert (ctx / "NAV.md").is_symlink()
    assert "context/tasks" in (code / ".gitignore").read_text(encoding="utf-8")

    assert cli.cmd_check(_ns()) == 0
    assert "check OK" in capsys.readouterr().out

    assert cli.cmd_connect(_ns()) == 0
    assert (ctx / "tasks").is_symlink()
    assert (ctx / "tasks").resolve() == (ext / "tasks").resolve()


def test_bridges_error_prints_layout_error_no_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    code, ext, ctx = _empty_external(tmp_path)
    # Pre-seed conflicting local tasks dir (non-empty) — preflight before connect writes
    (ctx / "tasks").mkdir()
    (ctx / "tasks" / "stale.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)
    rc = cli.cmd_connect(_ns())
    err = capsys.readouterr().err
    assert rc == 1
    assert "context layout error:" in err
    assert "Traceback" not in err
    # No connect artifacts when preflight fails
    assert not (code / "AGENTS.md").exists()


def test_check_process_control_and_external_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    code, ext, ctx = _empty_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)
    assert cli.cmd_connect(_ns()) == 0
    capsys.readouterr()

    pc = ctx / "process-control.json"
    assert pc.exists()
    pc.unlink()
    assert cli.cmd_check(_ns()) == 1
    fail_out = capsys.readouterr().out
    assert "process-control.json" in fail_out
    assert "check FAIL" in fail_out

    assert cli.cmd_connect(_ns()) == 0
    capsys.readouterr()
    assert cli.cmd_check(_ns()) == 0
    ok = capsys.readouterr().out
    assert "check OK" in ok
    assert "placement: external" in ok

    import shutil

    shutil.rmtree(ext / "tasks")
    assert cli.cmd_check(_ns()) == 1


def test_lease_and_sync_status_use_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    code, ext, ctx = _empty_external(tmp_path)
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
    assert (ext / "leases" / "T-261121-lease.md").exists()
    assert cli.cmd_lease(_ns(lease_cmd="list")) == 0
    assert "T-261121-lease" in capsys.readouterr().out

    assert cli.cmd_sync_status(_ns()) == 0
    sync = capsys.readouterr().out
    assert "placement: external" in sync
    assert "active leases: 1" in sync


def test_connect_bridges_before_connect_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bridges before connect so skeleton no-ops on NAV symlink (AGE-68 A-final pending)."""
    code, ext, ctx = _empty_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)

    order: list[str] = []
    real_connect = cli.connect
    import agentized.context_layout as layout_mod

    real_bridges = layout_mod.ensure_code_context_bridges

    def wrap_bridges(layout):
        order.append("bridges")
        return real_bridges(layout)

    def wrap_connect(*a, **k):
        order.append("connect")
        assert (ctx / "NAV.md").is_symlink()
        return real_connect(*a, **k)

    monkeypatch.setattr(layout_mod, "ensure_code_context_bridges", wrap_bridges)
    monkeypatch.setattr(cli, "connect", wrap_connect)
    assert cli.cmd_connect(_ns()) == 0
    assert order == ["bridges", "connect"]
    assert (ctx / "tasks").is_symlink()
