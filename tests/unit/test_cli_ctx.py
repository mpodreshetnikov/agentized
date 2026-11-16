"""CLI --context confinement for index (AGE-30 Self-Review P2)."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import agentized_cli as cli


def _repo_with_outside(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    outside = tmp_path / "outside"
    (outside / "tasks").mkdir(parents=True)
    (outside / "leases").mkdir(parents=True)
    return repo, outside


def test_ctx_and_index_confine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ValueError) as exc:
        cli._ctx(tmp_path, argparse.Namespace(context="../outside"))
    assert exc.value.args == ("context must be a safe relative path",)

    repo, outside = _repo_with_outside(tmp_path)
    keep = outside / "tasks" / "KEEP.md"
    keep.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo)
    assert cli.cmd_index(argparse.Namespace(context="../outside", print=False)) == 1
    assert keep.read_text(encoding="utf-8") == "keep"
    assert not (outside / "tasks" / "INDEX.md").exists()

    (repo / "context").symlink_to(outside)
    assert cli.cmd_index(argparse.Namespace(context="context", print=False)) == 1
    assert not (outside / "tasks" / "INDEX.md").exists()
    assert {p.name for p in outside.iterdir()} == {"tasks", "leases"}
