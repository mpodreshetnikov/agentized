"""CLI cmd_process streaming (kept out of mutmut module selection — needs agentized_cli)."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("agentized_cli")


def test_cmd_process_streams_by_ok(tmp_path: Path, monkeypatch, capsys):
    """agentized_cli cmd_process: stream stderr on any not-ok (incl. error level)."""
    from agentized_cli import cmd_process

    monkeypatch.setattr("agentized_cli.find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        "agentized_cli.load_state",
        lambda root: {"context": "context"},  # noqa: ARG005
    )
    (tmp_path / "context").mkdir(exist_ok=True)

    def fake_size(*a, **k):  # noqa: ARG001
        return {
            "ok": False,
            "level": "error",
            "insertions": 0,
            "limit": 0,
            "warn_at": 0,
            "base": "origin/main",
            "message": "process-control: invalid JSON boom",
        }

    monkeypatch.setattr("agentized.process_size.size_check", fake_size)
    args = argparse.Namespace(process_cmd="size", context="context", base=None, json=False)
    assert cmd_process(args) == 1
    captured = capsys.readouterr()
    assert "invalid JSON boom" in captured.err
    assert captured.out == ""


def test_cmd_process_bad_json_non_object_git(tmp_path: Path, monkeypatch, capsys):
    """Real cmd_process path: bad JSON / non-object → exit 1 + stderr, no traceback."""
    from agentized_cli import cmd_process

    monkeypatch.setattr("agentized_cli.find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        "agentized_cli.load_state",
        lambda root: {"context": "context"},  # noqa: ARG005
    )
    monkeypatch.setattr("agentized.process_size.validate_process_base", lambda *a, **k: None)
    (tmp_path / "context").mkdir(exist_ok=True)
    (tmp_path / "context" / "process-control.json").write_text("{bad", encoding="utf-8")
    args = argparse.Namespace(process_cmd="size", context="context", base=None, json=False)
    assert cmd_process(args) == 1
    err = capsys.readouterr().err
    assert "invalid JSON" in err
    assert "Traceback" not in err

    (tmp_path / "context" / "process-control.json").write_text("[]\n", encoding="utf-8")
    assert cmd_process(args) == 1
    assert "JSON object" in capsys.readouterr().err


def test_cmd_process_format_disables_streams(tmp_path: Path, monkeypatch, capsys):
    """format-disables: stderr on fail, stdout on ok; exit matches ok."""
    from agentized_cli import cmd_process

    monkeypatch.setattr("agentized_cli.find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        "agentized_cli.load_state",
        lambda root: {"context": "context"},
    )

    def fake_fail(*_a, **_k):
        return {
            "ok": False,
            "level": "fail",
            "base": "origin/main",
            "findings": [{"path": "x.py", "line": 1, "text": "bad"}],
            "message": "format-disable-gate: PR adds 1",
        }

    monkeypatch.setattr("agentized.format_disable_gate.format_disable_check", fake_fail)
    args = argparse.Namespace(process_cmd="format-disables", base=None, json=False)
    assert cmd_process(args) == 1
    captured = capsys.readouterr()
    assert "format-disable-gate: PR adds 1" in captured.err
    assert captured.out == ""

    def fake_ok(*_a, **_k):
        return {
            "ok": True,
            "level": "ok",
            "base": "origin/main",
            "findings": [],
            "message": "format-disable-gate: no new",
        }

    monkeypatch.setattr("agentized.format_disable_gate.format_disable_check", fake_ok)
    assert cmd_process(args) == 0
    captured = capsys.readouterr()
    assert "no new" in captured.out
    assert captured.err == ""


def _agent_merge_repo(tmp_path: Path, monkeypatch) -> argparse.Namespace:
    monkeypatch.setattr("agentized_cli.find_repo_root", lambda: tmp_path)
    monkeypatch.setattr("agentized_cli.load_state", lambda root: {"context": "context"})
    monkeypatch.setenv("CURSOR_AGENT", "1")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text(
        '{"merge_policy": {"agent_merge": "forbidden"}}\n', encoding="utf-8"
    )
    return argparse.Namespace(process_cmd="agent-merge", remote=None, local=None, json=False)


def test_cmd_process_agent_merge_unresolvable_head_refuses(tmp_path: Path, monkeypatch, capsys):
    """No commits -> HEAD unresolvable: refuse (exit 1), never an empty-push ok."""
    from agentized_cli import cmd_process

    args = _agent_merge_repo(tmp_path, monkeypatch)
    assert cmd_process(args) == 1
    captured = capsys.readouterr()
    assert "agent-merge: REFUSED. git failed" in captured.err
    assert captured.out == ""


def test_cmd_process_agent_merge_unknown_remote_refuses(tmp_path: Path, monkeypatch, capsys):
    """Explicit --local with a remote sha git cannot resolve: refuse, no traceback."""
    from agentized_cli import cmd_process

    args = _agent_merge_repo(tmp_path, monkeypatch)
    args.local, args.remote = "f" * 40, "e" * 40
    assert cmd_process(args) == 1
    err = capsys.readouterr().err
    assert "agent-merge: REFUSED. git failed" in err
    assert "Traceback" not in err
