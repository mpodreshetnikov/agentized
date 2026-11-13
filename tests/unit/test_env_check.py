from __future__ import annotations

import base64
import json
from pathlib import Path

from agentized import cursor_agent_git_hooks as cagh
from agentized import env_check as ec


def test_local_human_passes(tmp_path: Path):
    result = ec.check(env={}, repo_root=tmp_path, home=tmp_path / "home")
    assert result["ok"] is True
    assert result["severity"] == "local"


def test_unknown_agent_refused(tmp_path: Path):
    result = ec.check(env={"AGENT": "1"}, repo_root=tmp_path, home=tmp_path / "home")
    assert result["ok"] is False
    assert "REFUSED" in result["message"]


def test_cursor_missing_hooks_refused(tmp_path: Path):
    (tmp_path / ".cursor").mkdir()
    result = ec.check(
        env={"CURSOR_AGENT": "1"},
        repo_root=tmp_path,
        home=tmp_path / "home",
    )
    assert result["ok"] is False
    assert "REFUSED" in result["message"]


def test_cursor_hooks_ok_git_warn(tmp_path: Path):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "env-check.json").write_text(
        json.dumps({"cloud_git_hooks": "warn"}), encoding="utf-8"
    )
    hooks = tmp_path / ".cursor"
    hooks.mkdir()
    (hooks / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "sessionStart": [{"command": ".cursor/hooks/session_start.py"}],
                    "preToolUse": [{"command": ".cursor/hooks/lease_warn.py"}],
                }
            }
        ),
        encoding="utf-8",
    )
    (hooks / "hooks").mkdir()
    (hooks / "hooks" / "session_start.py").write_text("x", encoding="utf-8")
    (hooks / "hooks" / "lease_warn.py").write_text("x", encoding="utf-8")
    (tmp_path / ".githooks").mkdir()
    (tmp_path / ".githooks" / "pre-push").write_text("#!/bin/sh\n", encoding="utf-8")
    home = tmp_path / "home"
    # No agent-hooks dir → warn path
    result = ec.check(env={"CURSOR_AGENT": "1"}, repo_root=tmp_path, home=home)
    assert result["ok"] is True
    assert "WARN" in result["message"]
    assert "configure-cursor-agent-hooks.sh" in result["message"]


def test_cursor_git_refuse(tmp_path: Path):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "env-check.json").write_text(
        json.dumps({"cloud_git_hooks": "refuse"}), encoding="utf-8"
    )
    hooks = tmp_path / ".cursor"
    hooks.mkdir()
    (hooks / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "sessionStart": [{"command": ".cursor/hooks/session_start.py"}],
                    "preToolUse": [{"command": ".cursor/hooks/lease_warn.py"}],
                }
            }
        ),
        encoding="utf-8",
    )
    (hooks / "hooks").mkdir()
    (hooks / "hooks" / "session_start.py").write_text("x", encoding="utf-8")
    (tmp_path / ".githooks").mkdir()
    (tmp_path / ".githooks" / "pre-push").write_text("#!/bin/sh\n", encoding="utf-8")
    result = ec.check(
        env={"CURSOR_AGENT": "1"},
        repo_root=tmp_path,
        home=tmp_path / "home",
    )
    assert result["ok"] is False
    assert "REFUSED" in result["message"]


def test_install_and_problem_present(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    githooks = repo / ".githooks"
    githooks.mkdir()
    (githooks / "pre-push").write_text("#!/bin/sh\n", encoding="utf-8")
    home = tmp_path / "home"
    hooks_dir = cagh.agent_hooks_dir(repo, home)
    hooks_dir.mkdir(parents=True)
    (hooks_dir / ".dispatcher").write_text("#!/bin/sh\n", encoding="utf-8")
    assert cagh.git_hooks_problem(repo, home=home) is not None
    result = cagh.install(repo, home=home)
    assert result["ok"] is True
    assert (hooks_dir / "pre-push").is_symlink()
    assert cagh.git_hooks_problem(repo, home=home) is None


def test_agent_hooks_id_stable(tmp_path: Path):
    root = tmp_path / "r"
    root.mkdir()
    expected = base64.b64encode(str(root.resolve()).encode()).decode().rstrip("=")
    assert cagh.agent_hooks_id(root) == expected


def test_claude_and_codex_paths(tmp_path: Path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "x"}]}]}}),
        encoding="utf-8",
    )
    assert ec.check(env={"CLAUDE_CODE_REMOTE": "true"}, repo_root=tmp_path, home=tmp_path / "h")[
        "ok"
    ]
    bad = ec.check(env={"CLAUDE_CODE_REMOTE": "true"}, repo_root=tmp_path / "empty", home=tmp_path / "h")
    (tmp_path / "empty").mkdir()
    bad = ec.check(env={"CLAUDE_CODE_REMOTE": "true"}, repo_root=tmp_path / "empty", home=tmp_path / "h")
    assert bad["ok"] is False

    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "hooks.json").write_text(
        json.dumps({"hooks": {"SessionStart": []}}),
        encoding="utf-8",
    )
    assert ec.check(env={"CODEX_THREAD_ID": "t1"}, repo_root=tmp_path, home=tmp_path / "h")["ok"]
    empty = tmp_path / "empty2"
    empty.mkdir()
    assert ec.check(env={"CODEX_CI": "1"}, repo_root=empty, home=tmp_path / "h")["ok"] is False


def test_install_missing_dispatcher(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".githooks").mkdir()
    (repo / ".githooks" / "pre-push").write_text("x", encoding="utf-8")
    home = tmp_path / "home"
    hooks = cagh.agent_hooks_dir(repo, home)
    hooks.mkdir(parents=True)
    # no .dispatcher
    result = cagh.install(repo, home=home)
    assert result["ok"] is False
    assert "dispatcher" in result["message"]


def test_unknown_labels():
    assert ec.unknown_agent_label({"OPENCODE": "1"}) == "OpenCode"
    assert ec.unknown_agent_label({"PI_CODING_AGENT": "true"}) == "pi"
    assert ec.unknown_agent_label({"AI_AGENT": "foo"}) == "foo"
    assert ec.unknown_agent_label({"AI_AGENT": "claude-code_x"}) is None
    assert ec.unknown_agent_label({}) is None


def test_cursor_chain_ok_no_warn(tmp_path: Path):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "env-check.json").write_text(
        json.dumps({"cloud_git_hooks": "warn"}), encoding="utf-8"
    )
    hooks = tmp_path / ".cursor"
    hooks.mkdir()
    (hooks / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "sessionStart": [{"command": ".cursor/hooks/session_start.py"}],
                    "preToolUse": [{"command": ".cursor/hooks/lease_warn.py"}],
                }
            }
        ),
        encoding="utf-8",
    )
    (hooks / "hooks").mkdir()
    (hooks / "hooks" / "session_start.py").write_text("x", encoding="utf-8")
    (tmp_path / ".githooks").mkdir()
    (tmp_path / ".githooks" / "pre-push").write_text("#!/bin/sh\n", encoding="utf-8")
    home = tmp_path / "home"
    hooks_dir = cagh.agent_hooks_dir(tmp_path, home)
    hooks_dir.mkdir(parents=True)
    (hooks_dir / ".dispatcher").write_text("#!/bin/sh\n", encoding="utf-8")
    assert cagh.install(tmp_path, home=home)["ok"] is True
    result = ec.check(env={"CURSOR_AGENT": "1"}, repo_root=tmp_path, home=home)
    assert result["ok"] is True
    assert "WARN" not in result["message"]
    assert "git chain OK" in result["message"]
