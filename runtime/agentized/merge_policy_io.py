"""Git/CLI I/O for merge policy."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .merge_policy import agent_merge_decision, authorship_check, merge_policy_from_config
from .merge_policy_defaults import (
    KEY_MESSAGE,
    KEY_MODE,
    KEY_OK,
    MODE_DISABLED,
    MODE_OK,
    MODE_REFUSE,
)
from .paths import DEFAULT_CONTEXT, find_repo_root
from .process_control import is_agent_session, load_process_config


class GitCommandError(RuntimeError):
    """Non-zero git exit — fail closed."""


def load_merge_policy(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    return merge_policy_from_config(load_process_config(root, context_rel))


def _git_output(root: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise GitCommandError(exc.stderr.strip()) from exc
    return proc.stdout


def head_sha(root: Path) -> str:
    return _git_output(root, ["rev-parse", "HEAD"]).strip()


def git_user_email(root: Path) -> str:
    try:
        return _git_output(root, ["config", "user.email"]).strip()
    except GitCommandError:
        return ""


def commits_to_push(root: Path, remote_sha: str, local_sha: str) -> list[str]:
    if not local_sha or re.fullmatch(r"0+", local_sha):
        return []
    if re.fullmatch(r"0+", remote_sha) or not remote_sha:
        out = _git_output(root, ["rev-list", local_sha, "--not", "--remotes"])
    else:
        out = _git_output(root, ["rev-list", f"{remote_sha}..{local_sha}"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def is_merge_commit(root: Path, sha: str) -> bool:
    out = _git_output(root, ["rev-list", "--parents", "-n", "1", sha]).strip()
    return len(out.split()) >= 3


def agent_merge_check(
    root: Path,
    *,
    remote_sha: str,
    local_sha: str,
    policy: dict[str, Any] | None = None,
    context_rel: str = DEFAULT_CONTEXT,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if policy is None:
        policy = load_merge_policy(root, context_rel)
    merges = [
        sha for sha in commits_to_push(root, remote_sha, local_sha) if is_merge_commit(root, sha)
    ]
    return agent_merge_decision(
        agent_merge=str(policy["agent_merge"]),
        is_agent=is_agent_session(env),
        merge_shas=merges,
    )


def apply_commit_msg(
    path: Path,
    *,
    author: str | None = None,
    root: Path | None = None,
    context_rel: str = DEFAULT_CONTEXT,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = root or find_repo_root()
    env = dict(os.environ if env is None else env)
    policy = load_merge_policy(root, context_rel)
    message = path.read_text()
    if author is None:
        name = env.get("GIT_AUTHOR_NAME", "").strip()
        email = env.get("GIT_AUTHOR_EMAIL", "").strip()
        if not name and not email:
            email = git_user_email(root)
        author = f"{name} <{email}>" if email else name
    result = authorship_check(author=author, message=message, policy=policy)
    cleaned = result["cleaned_message"]
    if cleaned != message:
        path.write_text(cleaned)
    return result


def authorship_range_check(
    root: Path,
    *,
    base_ref: str,
    head_ref: str = "HEAD",
    policy: dict[str, Any] | None = None,
    context_rel: str = DEFAULT_CONTEXT,
) -> dict[str, Any]:
    if policy is None:
        policy = load_merge_policy(root, context_rel)
    ha = policy.get("human_authorship") or {}
    if not bool(ha.get("enabled")):
        return {
            KEY_OK: True,
            KEY_MODE: MODE_DISABLED,
            KEY_MESSAGE: "",
            "failures": [],
            "checked": 0,
        }
    out = _git_output(root, ["rev-list", f"{base_ref}..{head_ref}"])
    shas = [line.strip() for line in out.splitlines() if line.strip()]
    failures: list[dict[str, Any]] = []
    checked = 0
    for sha in shas:
        if is_merge_commit(root, sha):
            continue
        checked += 1
        author = _git_output(root, ["log", "-1", "--format=%an <%ae>", sha]).strip()
        message = _git_output(root, ["log", "-1", "--format=%B", sha])
        result = authorship_check(author=author, message=message, policy=policy)
        if not result[KEY_OK]:
            failures.append({"sha": sha, "author": author, KEY_MESSAGE: result[KEY_MESSAGE]})
    if failures:
        msg = "; ".join(f"{f['sha'][:12]}: {f[KEY_MESSAGE]}" for f in failures)
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_MESSAGE: msg,
            "failures": failures,
            "checked": checked,
        }
    return {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_MESSAGE: f"merge-policy: authorship OK for {checked} commit(s)",
        "failures": [],
        "checked": checked,
    }
