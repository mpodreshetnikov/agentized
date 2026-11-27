"""AGE-95 e2e: only `agentized connect` installs the commit-msg authorship gate."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# mutmut copies tests under mutants/ without bin/ — resolve the real source tree.
_TEST_ROOT = Path(__file__).resolve().parents[2]
AGENTIZED_ROOT = _TEST_ROOT.parent if _TEST_ROOT.name == "mutants" else _TEST_ROOT
BIN = AGENTIZED_ROOT / "bin" / "agentized"


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_AUTHOR", "GIT_COMMITTER"))}
    env["PATH"] = f"{BIN.parent}{os.pathsep}{env.get('PATH', '')}"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env.pop("GIT_CONFIG_COUNT", None)
    return env


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=_env(), capture_output=True, text=True, check=False)


def _git_repo(path: Path, email: str | None) -> Path:
    path.mkdir()
    _run(path, "git", "init", "-b", "main")
    if email:
        _run(path, "git", "config", "user.email", email)
        _run(path, "git", "config", "user.name", "Alice")
    return path


def _commit(cwd: Path, author_email: str, message: str) -> subprocess.CompletedProcess[str]:
    return _run(
        cwd,
        "git",
        "-c",
        f"user.email={author_email}",
        "-c",
        "user.name=Someone",
        "commit",
        "-m",
        message,
    )


def test_connect_installs_commit_msg_gate_that_refuses_strangers(tmp_path: Path):
    repo = _git_repo(tmp_path / "consumer", "alice@example.com")
    connected = _run(repo, str(BIN), "connect", "--harness", "cursor")
    assert connected.returncode == 0, connected.stdout + connected.stderr

    hook = repo / ".githooks" / "commit-msg"
    assert hook.stat().st_mode & 0o111 == 0o111
    assert (repo / ".githooks" / "pre-push").stat().st_mode & 0o111 == 0o111
    hooks_path = _run(repo, "git", "config", "--local", "core.hooksPath")
    assert hooks_path.stdout.strip() == ".githooks"
    assert "alice@example.com" in (repo / "context" / "process-control.json").read_text(
        encoding="utf-8"
    )

    (repo / "stranger.txt").write_text("x\n", encoding="utf-8")
    _run(repo, "git", "add", "-A")
    refused = _commit(repo, "eve@evil.test", "feat: stranger")
    assert refused.returncode != 0
    assert "REFUSED" in refused.stderr + refused.stdout
    assert "not on human_participants allowlist" in refused.stderr + refused.stdout
    assert _run(repo, "git", "rev-parse", "--verify", "HEAD").returncode != 0

    allowed = _commit(
        repo,
        "alice@example.com",
        "feat: connect\n\nCo-authored-by: Cursor <cursoragent@cursor.com>",
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    body = _run(repo, "git", "log", "-1", "--format=%B").stdout
    assert "feat: connect" in body
    assert "Co-authored-by: Cursor" not in body


def test_connect_without_git_email_refuses_and_writes_nothing(tmp_path: Path):
    repo = _git_repo(tmp_path / "consumer", None)
    refused = _run(repo, str(BIN), "connect", "--harness", "cursor")
    assert refused.returncode == 1
    assert "connect error: REFUSED. merge-policy:" in refused.stderr
    assert sorted(p.name for p in repo.iterdir()) == [".git"]
