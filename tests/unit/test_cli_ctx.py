"""CLI context / INDEX child-symlink confinement (AGE-30)."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import agentized_cli as cli


def _repo(tmp_path: Path, name: str = "repo"):
    repo = tmp_path / name
    repo.mkdir(); (repo / ".git").mkdir()
    return repo


def test_ctx_index_child_symlinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ValueError) as exc:
        cli._ctx(tmp_path, argparse.Namespace(context="../outside"))
    assert exc.value.args == ("context must be a safe relative path",)
    repo = _repo(tmp_path)
    outside = tmp_path / "outside"
    (outside / "tasks").mkdir(parents=True); (outside / "leases").mkdir(parents=True)
    keep = outside / "tasks" / "KEEP.md"
    keep.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo)
    assert cli.cmd_index(argparse.Namespace(context="../outside", print=False)) == 1
    assert keep.read_text(encoding="utf-8") == "keep" and not (outside / "tasks" / "INDEX.md").exists()
    (repo / "context").symlink_to(outside)
    assert cli.cmd_index(argparse.Namespace(context="context", print=False)) == 1
    repo2 = _repo(tmp_path, "repo2"); ctx = repo2 / "context"; ctx.mkdir()
    out2 = tmp_path / "out2"
    (out2 / "tasks").mkdir(parents=True); (out2 / "leases").mkdir(parents=True)
    (ctx / "tasks").symlink_to(out2 / "tasks"); (ctx / "leases").symlink_to(out2 / "leases")
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo2)
    assert cli.cmd_index(argparse.Namespace(context="context", print=False)) == 1
    assert list((out2 / "tasks").iterdir()) == []
    repo3 = _repo(tmp_path, "repo3")
    (repo3 / "context" / "tasks").mkdir(parents=True)
    (repo3 / "context" / "leases").mkdir(parents=True)
    out3 = tmp_path / "out3"; out3.mkdir()
    target = out3 / "INDEX.md"; target.write_text("sentinel", encoding="utf-8")
    (repo3 / "context" / "tasks" / "INDEX.md").symlink_to(target)
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo3)
    assert cli.cmd_index(argparse.Namespace(context="context", print=False)) == 1
    assert target.read_text(encoding="utf-8") == "sentinel"
