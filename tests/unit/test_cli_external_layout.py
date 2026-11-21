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


def test_empty_external_connect_index_check_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """P0 e2e: empty external connect → index (write_metrics via tasks bridge) → check."""
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
    for sub in ("tasks", "leases", "decisions", "goals", "digests"):
        assert (ext / sub).is_dir()
        assert (ctx / sub).is_symlink()
        assert (ctx / sub).resolve() == (ext / sub).resolve()
    assert (ctx / "NAV.md").is_symlink()
    assert "context/tasks" in (code / ".gitignore").read_text(encoding="utf-8")

    assert cli.cmd_index(_ns(print=False)) == 0
    idx_out = capsys.readouterr().out
    assert "пересобраны:" in idx_out
    assert (ctx / "board" / "metrics.json").is_file()

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
    # No connect artifacts / no seed when preflight fails
    assert not (code / "AGENTS.md").exists()
    assert not (ext / "NAV.md").exists()


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


def test_connect_rolls_back_bridges_on_connect_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    code, ext, ctx = _empty_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)

    def boom(*a, **k):
        raise RuntimeError("connect failed")

    monkeypatch.setattr(cli, "connect", boom)
    assert cli.cmd_connect(_ns()) == 1
    err = capsys.readouterr().err
    assert "connect error: connect failed" in err
    assert "Traceback" not in err
    assert (ext / "NAV.md").is_file()  # seed kept (manual cleanup)
    assert "context/tasks" in (code / ".gitignore").read_text(encoding="utf-8")
    assert not (ctx / "tasks").exists() or not (ctx / "tasks").is_symlink()
    assert not (ctx / "NAV.md").exists() or not (ctx / "NAV.md").is_symlink()
    assert not (code / "AGENTS.md").exists()

    # ValueError after bridges also rolls back (layout-error path).
    def boom_val(*a, **k):
        raise ValueError("post-bridge layout boom")

    monkeypatch.setattr(cli, "connect", boom_val)
    assert cli.cmd_connect(_ns()) == 1
    err = capsys.readouterr().err
    assert "context layout error: post-bridge layout boom" in err
    assert not (ctx / "tasks").is_symlink() if (ctx / "tasks").exists() else True


def test_env_check_cli_applies_external_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """cmd_env_check runs apply_external_env_check (CLI 156–160)."""
    code, ext, ctx = _empty_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)
    # Hooks may refuse first; stub check OK so CLI reaches apply_external_env_check.
    from agentized import env_check as ec

    monkeypatch.setattr(
        ec,
        "check",
        lambda **kw: {
            "ok": True,
            "refused": False,
            "message": "agent-env-check: hooks OK",
            "audience": "owner",
        },
    )
    # Empty external clone → refuse via apply_external_env_check.
    assert cli.cmd_env_check(_ns()) == 1
    err = capsys.readouterr().err
    assert err == (
        "agent-env-check: REFUSED. External Project Context clone is missing or incomplete "
        f"(external Context missing NAV.md: {ext / 'NAV.md'}; "
        f"external Context missing tasks/: {ext / 'tasks'}). "
        "Code repo and Context repo must both be present. "
        "Clone `external.remote` to `external.path` from context/context.json. "
        "See docs/AGENT_ENVIRONMENT.md.\n"
    )

    # Seed registry so external gate passes.
    (ext / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    (ext / "leases").mkdir()
    assert cli.cmd_env_check(_ns()) == 0
    out = capsys.readouterr().out
    assert "agent-env-check:" in out
    assert "REFUSED" not in out


def test_check_fails_without_nav_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """cmd_check reports missing NAV.md (CLI ~594)."""
    code, ext, ctx = _empty_external(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)
    assert cli.cmd_connect(_ns()) == 0
    capsys.readouterr()
    (ctx / "NAV.md").unlink()
    (ext / "NAV.md").unlink()
    assert cli.cmd_check(_ns()) == 1
    out = capsys.readouterr().out
    assert "check FAIL" in out
    assert "NAV.md" in out


def test_local_to_external_migration_documented_procedure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """docs Local→external: copy → git rm --ignore-unmatch → connect+index; task in external INDEX."""
    import shutil

    from agentized.context_layout import BRIDGE_NAMES
    from agentized.tasks import render_task_file

    code = tmp_path / "code"
    code.mkdir()
    _git_init(code)
    subprocess.run(
        ["git", "config", "user.email", "mig@example.com"],
        cwd=code,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "mig"],
        cwd=code,
        check=True,
        capture_output=True,
    )
    ctx = code / "context"
    ctx.mkdir()
    monkeypatch.setattr(cli, "find_repo_root", lambda: code)
    monkeypatch.chdir(code)

    # Nested/local connected repo + 1 task (tracked so documented git rm deletes disk).
    assert cli.cmd_connect(_ns()) == 0
    capsys.readouterr()
    task_id = "T-261121-mig1"
    (ctx / "tasks" / f"{task_id}.md").write_text(
        render_task_file(task_id, "Migrate me", status="open"),
        encoding="utf-8",
    )
    assert (ctx / "tasks" / f"{task_id}.md").is_file()
    assert not (ctx / "tasks").is_symlink()
    subprocess.run(["git", "add", "context"], cwd=code, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "nested context + task"],
        cwd=code,
        check=True,
        capture_output=True,
    )

    # Documented procedure: copy into clone → set external → git rm → connect.
    ext = tmp_path / "ext"
    ext.mkdir()
    _git_init(ext)
    for name in BRIDGE_NAMES:
        src = ctx / name
        if not src.exists():
            continue
        dest = ext / name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            dest.write_bytes(src.read_bytes())
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
    # Exact documented delete (not shutil) — --ignore-unmatch so missing pathspecs ≠ exit 128.
    rm = subprocess.run(
        [
            "git",
            "rm",
            "-r",
            "--ignore-unmatch",
            "context/tasks",
            "context/leases",
            "context/decisions",
            "context/goals",
            "context/digests",
            "context/NAV.md",
        ],
        cwd=code,
        capture_output=True,
        text=True,
    )
    assert rm.returncode == 0, rm.stderr
    for name in ("tasks", "leases", "NAV.md"):
        assert not (ctx / name).exists()

    assert cli.cmd_connect(_ns()) == 0
    out = capsys.readouterr().out
    assert "connect OK" in out
    assert (ctx / "tasks").is_symlink()
    assert (ctx / "tasks").resolve() == (ext / "tasks").resolve()
    assert (ext / "tasks" / f"{task_id}.md").is_file()

    assert cli.cmd_index(_ns(print=False)) == 0
    capsys.readouterr()
    idx = (ext / "tasks" / "INDEX.md").read_text(encoding="utf-8")
    assert task_id in idx
    assert "Migrate me" in idx
