"""Git/CLI I/O for merge policy."""

from __future__ import annotations

import json
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
    missing_git_email_message,
)
from .paths import DEFAULT_CONTEXT, find_repo_root
from .process_control import (
    PROCESS_FILENAME,
    default_process_config,
    is_agent_session,
    load_process_config,
)


class GitCommandError(RuntimeError):
    """Non-zero git exit — fail closed."""


def _write_json(path: Path, obj: object) -> None:
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_merge_policy(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    return merge_policy_from_config(load_process_config(root, context_rel))


def plan_process_control_authorship(
    root: Path, context_rel: str = DEFAULT_CONTEXT
) -> dict[str, Any]:
    """Read-only: the process-control.json that connect must hold, or raise.

    Fail closed: with authorship enabled and an empty allowlist, a missing git
    email raises. Nothing is written here.
    """
    path = root / context_rel / PROCESS_FILENAME
    created = not path.exists()
    data = default_process_config()
    if not created:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise TypeError(f"{path}: expected a JSON object")
        data.update(loaded)
    mp = merge_policy_from_config(data)
    data["merge_policy"] = mp
    filled = False
    enabled = bool((mp.get("human_authorship") or {}).get("enabled"))
    if enabled and not mp.get("human_participants"):
        email = git_user_email(root)
        if not email:
            raise RuntimeError(missing_git_email_message())
        mp["human_participants"] = [email]
        filled = True
    return {"path": path, "data": data, "created": created, "filled": filled}


def ensure_process_control_authorship(
    root: Path, context_rel: str = DEFAULT_CONTEXT
) -> dict[str, Any]:
    """Write process-control.json when new or when the allowlist was filled."""
    plan = plan_process_control_authorship(root, context_rel)
    path: Path = plan["path"]
    if plan["filled"] or plan["created"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, plan["data"])
    return {
        "path": str(path.relative_to(root)),
        "created": plan["created"],
        "participants_filled": plan["filled"],
        "human_participants": list(plan["data"]["merge_policy"]["human_participants"]),
    }


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
