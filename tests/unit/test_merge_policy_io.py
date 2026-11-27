"""I/O tests for AGE-27 merge policy (mutation-covered)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from agentized.merge_policy import authorship_check as authorship_check_fn
from agentized.merge_policy_io import (
    GitCommandError,
    _git_output,
    agent_merge_check,
    apply_commit_msg,
    authorship_range_check,
    commits_to_push,
    git_user_email,
    head_sha,
    is_merge_commit,
    load_merge_policy,
)

_PC = (
    '{"merge_policy": {"human_participants": ["Alice <alice@example.com>"], '
    '"human_authorship": {"enabled": true, "strip_agent_trailers": true}}}\n'
)
_PC_EMAIL = (
    '{"merge_policy": {"human_participants": ["alice@example.com"], '
    '"human_authorship": {"enabled": true}}}\n'
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        env.pop(k, None)
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, env=env
    )


def _init_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "alice@example.com")
    _git(tmp_path, "config", "user.name", "Alice")
    (tmp_path / "f.txt").write_text("a\n", encoding="utf-8")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


def _write_pc(root: Path, body: str, rel: str = "context") -> Path:
    ctx = root / rel
    ctx.mkdir(parents=True, exist_ok=True)
    path = ctx / "process-control.json"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_merge_policy_deep_merge(tmp_path: Path):
    _write_pc(tmp_path, '{"merge_policy": {"agent_merge": "forbidden"}}\n')
    policy = load_merge_policy(tmp_path)
    assert policy["agent_merge"] == "forbidden"
    assert policy["human_authorship"]["enabled"] is True
    assert policy["human_authorship"]["strip_agent_trailers"] is True
    _write_pc(
        tmp_path,
        '{"merge_policy": {"agent_merge": "allowed", "human_participants": ["bob@x"]}}\n',
        "other",
    )
    other = load_merge_policy(tmp_path, context_rel="other")
    assert (other["agent_merge"], other["human_participants"]) == ("allowed", ["bob@x"])
    assert load_merge_policy(tmp_path)["agent_merge"] == "forbidden"


def test_head_sha_resolves_and_fails_closed(tmp_path: Path):
    _git(tmp_path, "init")
    with pytest.raises(GitCommandError):
        head_sha(tmp_path)
    _init_repo(tmp_path)
    assert head_sha(tmp_path) == _git(tmp_path, "rev-parse", "HEAD").stdout.strip()


def test_git_output_fail_closed(tmp_path: Path, monkeypatch):
    _init_repo(tmp_path)
    with pytest.raises(GitCommandError) as ei:
        _git_output(tmp_path, ["rev-parse", "does-not-exist"])
    assert "does-not-exist" in str(ei.value)
    assert git_user_email(tmp_path) == "alice@example.com"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    bare = tmp_path / "noemail"
    bare.mkdir()
    _git(bare, "init")
    assert git_user_email(bare) == ""
    calls: list[list[str]] = []

    def fake_git(_root, args):
        calls.append(list(args))
        return "x@y\n"

    monkeypatch.setattr("agentized.merge_policy_io._git_output", fake_git)
    assert git_user_email(tmp_path) == "x@y"
    assert calls == [["config", "user.email"]]
    monkeypatch.setattr("agentized.merge_policy_io._git_output", lambda _r, _a: "")
    assert is_merge_commit(tmp_path, "deadbeef") is False


def test_apply_commit_msg_rewrites_file(tmp_path: Path, monkeypatch):
    root = _init_repo(tmp_path)
    _write_pc(root, _PC)
    msg = root / "COMMIT_EDITMSG"
    msg.write_text("feat: x\n\nCo-authored-by: Cursor <cursoragent@cursor.com>\n", encoding="utf-8")
    result = apply_commit_msg(msg, author="Alice <alice@example.com>", root=root)
    text = msg.read_text(encoding="utf-8")
    assert (result["mode"], result["ok"], text.strip(), "Cursor" in text) == (
        "ok",
        True,
        "feat: x",
        False,
    )
    msg.write_text("feat: y\n", encoding="utf-8")
    via_env = apply_commit_msg(
        msg,
        author=None,
        root=root,
        env={"GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.com"},
    )
    assert via_env["ok"] is True and via_env["mode"] == "ok"
    msg.write_text("feat: z\n", encoding="utf-8")
    assert apply_commit_msg(msg, author=None, root=root, env={})["ok"] is True
    msg.write_text("feat: n\n", encoding="utf-8")
    name_only = apply_commit_msg(
        msg, author=None, root=root, env={"GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": ""}
    )
    assert name_only["ok"] is False and "Alice" in name_only["message"]
    captured: list[str] = []

    def _capture(*, author, message, policy):
        captured.append(author)
        return authorship_check_fn(author=author, message=message, policy=policy)

    monkeypatch.setattr("agentized.merge_policy_io.authorship_check", _capture)
    msg.write_text("feat: bare\n", encoding="utf-8")
    apply_commit_msg(
        msg, author=None, root=root, env={"GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": ""}
    )
    assert captured[-1] == "Alice"
    monkeypatch.setattr("agentized.merge_policy_io.authorship_check", authorship_check_fn)
    _write_pc(
        root,
        '{"merge_policy": {"human_participants": ["bob@x"], '
        '"human_authorship": {"enabled": true}}}\n',
    )
    _write_pc(root, _PC, "altctx")
    msg.write_text("feat: alt\n", encoding="utf-8")
    assert apply_commit_msg(
        msg, author="Alice <alice@example.com>", root=root, context_rel="altctx"
    )["ok"]
    assert apply_commit_msg(msg, author="Alice <alice@example.com>", root=root)["ok"] is False
    msg.write_text("feat: empty\n", encoding="utf-8")
    assert apply_commit_msg(msg, author="", root=root, context_rel="altctx")["ok"] is False
    msg.write_text("feat: clean\n", encoding="utf-8")
    assert apply_commit_msg(
        msg, author="Alice <alice@example.com>", root=root, context_rel="altctx"
    )["ok"]
    assert msg.read_text(encoding="utf-8") == "feat: clean\n"


def test_agent_merge_and_commits_to_push(tmp_path: Path, monkeypatch):
    root = _init_repo(tmp_path)
    _write_pc(root, '{"merge_policy": {"agent_merge": "allowed"}}\n')
    _write_pc(root, '{"merge_policy": {"agent_merge": "forbidden"}}\n', "forbidctx")
    base0 = _git(root, "rev-parse", "HEAD").stdout.strip()
    _git(root, "checkout", "-b", "side")
    (root / "f.txt").write_text("b\n", encoding="utf-8")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-m", "side")
    _git(root, "checkout", "-")
    _git(root, "merge", "--no-ff", "side", "-m", "merge side")
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    assert is_merge_commit(root, head) is True
    monkeypatch.delenv("CURSOR_AGENT", raising=False)
    human = agent_merge_check(
        root, remote_sha="0" * 40, local_sha=head, env={}, context_rel="forbidctx"
    )
    assert human["mode"] == "human" and human["ok"] is True
    agent = agent_merge_check(
        root,
        remote_sha="0" * 40,
        local_sha=head,
        env={"CURSOR_AGENT": "1"},
        context_rel="forbidctx",
    )
    assert (agent["ok"], agent["mode"]) == (False, "refuse") and head in agent["merges"]
    assert agent_merge_check(root, remote_sha="0" * 40, local_sha=head, env={"CURSOR_AGENT": "1"})[
        "ok"
    ]
    allowed = agent_merge_check(
        root,
        remote_sha="0" * 40,
        local_sha=head,
        env={"CURSOR_AGENT": "1"},
        policy={"agent_merge": "allowed"},
    )
    assert allowed["ok"] is True and allowed["mode"] == "allowed"
    base = _git(root, "rev-parse", "HEAD~1").stdout.strip()
    ranged = agent_merge_check(
        root, remote_sha=base, local_sha=head, env={"CURSOR_AGENT": "1"}, context_rel="forbidctx"
    )
    assert ranged["ok"] is False and head in ranged["merges"]
    assert commits_to_push(root, "0" * 40, "0" * 40) == []
    assert commits_to_push(root, "0" * 40, "") == []
    zeros = commits_to_push(root, "0" * 40, head)
    assert head in zeros and base0 in zeros
    argv: list[list[str]] = []
    real_go = _git_output
    monkeypatch.setattr(
        "agentized.merge_policy_io._git_output",
        lambda r, a: argv.append(list(a)) or real_go(r, a),
    )
    assert head in commits_to_push(root, base, head)
    assert argv[-1] == ["rev-list", f"{base}..{head}"]
    commits_to_push(root, "", head)
    assert argv[-1] == ["rev-list", head, "--not", "--remotes"]
    _write_pc(root, _PC_EMAIL)
    assert authorship_range_check(root, base_ref=base0, head_ref="HEAD") == {
        "ok": True,
        "mode": "ok",
        "message": "merge-policy: authorship OK for 1 commit(s)",
        "failures": [],
        "checked": 1,
    }


def test_authorship_range_check(tmp_path: Path, monkeypatch):
    root = _init_repo(tmp_path)
    _write_pc(root, _PC_EMAIL)
    calls: list[list[str]] = []
    real = _git_output
    monkeypatch.setattr(
        "agentized.merge_policy_io._git_output", lambda r, a: calls.append(list(a)) or real(r, a)
    )
    (root / "f.txt").write_text("b\n", encoding="utf-8")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-m", "second")
    base = _git(root, "rev-parse", "HEAD~1").stdout.strip()
    assert authorship_range_check(root, base_ref=base, head_ref="HEAD")["checked"] == 1
    assert any("--format=%B" in c for c in calls)
    off = {"ok": True, "mode": "disabled", "message": "", "failures": [], "checked": 0}
    _write_pc(root, '{"merge_policy": {"human_authorship": {"enabled": false}}}\n')
    assert authorship_range_check(root, base_ref=base) == off
    _write_pc(root, _PC_EMAIL)
    assert authorship_range_check(root, base_ref=base)["ok"] is True
    _write_pc(root, '{"merge_policy": {"human_authorship": {"enabled": false}}}\n', "altctx")
    assert authorship_range_check(root, base_ref=base, context_rel="altctx") == off
    assert authorship_range_check(
        root,
        base_ref=base,
        policy={"human_participants": ["alice@example.com"], "human_authorship": {"enabled": True}},
    )["ok"]
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Eve",
            "GIT_AUTHOR_EMAIL": "eve@evil.test",
            "GIT_COMMITTER_NAME": "Eve",
            "GIT_COMMITTER_EMAIL": "eve@evil.test",
        }
    )
    for name in ("evil", "evil2"):
        (root / "f.txt").write_text(f"{name}\n", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=root, check=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", name], cwd=root, check=True, capture_output=True, env=env
        )
    bad = authorship_range_check(root, base_ref=base, head_ref="HEAD")
    assert (bad["ok"], bad["mode"], bad["checked"], len(bad["failures"])) == (False, "refuse", 3, 2)
    fail = bad["failures"][-1]
    assert fail["author"] == "Eve <eve@evil.test>" and fail["sha"]
    assert all(len(p.split(":", 1)[0]) == 12 for p in bad["message"].split("; "))
