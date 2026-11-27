"""AGE-95: connect authorship preflight + commit-msg pin (library + CLI wiring)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import agentized.connect as connect_mod
import pytest
from agentized.connect import connect, pin_quality_templates

pytest.importorskip("agentized_cli")

import agentized_cli as cli


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _no_global_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)


def _repo(root: Path, email: str | None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    if email:
        _git(root, "config", "user.email", email)
    return root


def _names(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


def test_connect_missing_email_refuses_and_writes_nothing(tmp_path, monkeypatch):
    _no_global_git(monkeypatch)
    root = _repo(tmp_path / "r", None)
    with pytest.raises(RuntimeError, match="REFUSED. merge-policy: .*user.email"):
        connect(root, harnesses=["cursor"])
    assert _names(root) == [".git"]


def test_connect_preflight_runs_before_every_other_write(tmp_path, monkeypatch):
    _no_global_git(monkeypatch)
    root = _repo(tmp_path / "r", "alice@example.com")
    seen: list[bool] = []
    real = connect_mod.ensure_context_skeleton

    def spy(r: Path, context_rel: str = "context"):
        seen.append((r / context_rel / "process-control.json").is_file())
        return real(r, context_rel)

    monkeypatch.setattr(connect_mod, "ensure_context_skeleton", spy)
    connect(root, harnesses=[])
    assert seen == [True]


def test_connect_fills_allowlist_from_git_email(tmp_path, monkeypatch):
    _no_global_git(monkeypatch)
    root = _repo(tmp_path / "r", "alice@example.com")
    result = connect(root, harnesses=[])
    assert result["process_control"] == {
        "path": "context/process-control.json",
        "created": True,
        "participants_filled": True,
        "human_participants": ["alice@example.com"],
    }
    data = json.loads((root / "context" / "process-control.json").read_text(encoding="utf-8"))
    assert data["merge_policy"]["human_participants"] == ["alice@example.com"]
    again = connect(root, harnesses=[])
    assert again["process_control"]["created"] is False
    assert again["process_control"]["participants_filled"] is False


def test_connect_keeps_allowlist_without_git_email(tmp_path, monkeypatch):
    _no_global_git(monkeypatch)
    root = _repo(tmp_path / "r", None)
    (root / "context").mkdir()
    body = '{"merge_policy": {"human_participants": ["bob@x.test"]}}\n'
    (root / "context" / "process-control.json").write_text(body, encoding="utf-8")
    result = connect(root, harnesses=[])
    assert result["process_control"]["human_participants"] == ["bob@x.test"]
    assert (root / "context" / "process-control.json").read_text(encoding="utf-8") == body


def test_connect_pins_executable_commit_msg_with_pre_push(tmp_path, monkeypatch):
    _no_global_git(monkeypatch)
    root = _repo(tmp_path / "r", "alice@example.com")
    result = connect(root, harnesses=[])
    assert result["quality_templates"]["commit_msg"] == "created"
    hook = root / ".githooks" / "commit-msg"
    assert "process commit-msg" in hook.read_text(encoding="utf-8")
    assert hook.stat().st_mode & 0o111 == 0o111
    assert (root / ".githooks" / "pre-push").stat().st_mode & 0o111 == 0o111
    assert connect(root, harnesses=[])["quality_templates"]["commit_msg"] == "unchanged"


def test_pin_commit_msg_never_clobbers_user_hook(tmp_path):
    hook = tmp_path / ".githooks" / "commit-msg"
    hook.parent.mkdir()
    hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    assert pin_quality_templates(tmp_path)["commit_msg"] == "skipped-user-file"
    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\necho mine\n"


def _ns() -> argparse.Namespace:
    return argparse.Namespace(context="context", harness=["cursor"], coverage=None, json=False)


def test_cmd_connect_missing_email_refuses_before_any_write(tmp_path, monkeypatch, capsys):
    _no_global_git(monkeypatch)
    root = _repo(tmp_path / "r", None)
    monkeypatch.setattr(cli, "find_repo_root", lambda: root)
    monkeypatch.chdir(root)
    assert cli.cmd_connect(_ns()) == 1
    err = capsys.readouterr().err
    assert err.startswith("connect error: REFUSED. merge-policy:")
    assert "user.email" in err
    assert _names(root) == [".git"]


def test_cmd_connect_refuses_unreadable_process_control(tmp_path, monkeypatch, capsys):
    _no_global_git(monkeypatch)
    root = _repo(tmp_path / "r", "alice@example.com")
    (root / "context").mkdir()
    (root / "context" / "process-control.json").write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(cli, "find_repo_root", lambda: root)
    assert cli.cmd_connect(_ns()) == 1
    assert capsys.readouterr().err.startswith("connect error: ")
    assert _names(root / "context") == ["process-control.json"]
