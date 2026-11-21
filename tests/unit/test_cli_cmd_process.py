"""CLI cmd_process streaming (kept out of mutmut module selection — needs agentized_cli)."""

from __future__ import annotations

import argparse
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
