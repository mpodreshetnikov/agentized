"""Fail-closed agent environment check (Orbit agent-env-check mechanism).

Human local shells without agent markers pass. Agent/cloud sessions must have
project hooks wired; Cursor Cloud also needs the agent-hooks → `.githooks` chain.

Rollout: `context/env-check.json` → `cloud_git_hooks` is `warn` until the owner
pastes the Dashboard Install & Start line, then flip to `refuse`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .cursor_agent_git_hooks import git_hooks_problem
from .paths import DEFAULT_CONTEXT, find_repo_root

DOC = "docs/AGENT_ENVIRONMENT.md"
INSTALL_LINE = (
    "bash /agent/repos/agentized/scripts/cloud/configure-cursor-agent-hooks.sh"
)
CURSOR_REQUIRED_EVENTS = ("sessionStart", "preToolUse")
ENV_CHECK_FILENAME = "env-check.json"


def default_env_check_config() -> dict[str, Any]:
    return {
        "version": 1,
        # warn until Maxim pastes Dashboard Install & Start; then refuse.
        "cloud_git_hooks": "warn",
        "unknown_agent": "refuse",
    }


def load_env_check_config(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    path = root / context_rel / ENV_CHECK_FILENAME
    cfg = default_env_check_config()
    if not path.exists():
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return cfg
    if isinstance(data, dict):
        cfg.update({k: data[k] for k in data})
    return cfg


def _env(env: dict[str, str] | None) -> dict[str, str]:
    return dict(os.environ if env is None else env)


def is_cursor_cloud(env: dict[str, str] | None = None) -> bool:
    env = _env(env)
    return env.get("CURSOR_AGENT") == "1" or env.get("CURSOR_CODE_REMOTE") == "true"


def is_claude_cloud(env: dict[str, str] | None = None) -> bool:
    env = _env(env)
    return env.get("CLAUDE_CODE_REMOTE") == "true"


def is_codex_agent(env: dict[str, str] | None = None) -> bool:
    env = _env(env)
    return bool(
        env.get("CODEX_THREAD_ID")
        or env.get("CODEX_SESSION_ID")
        or env.get("CODEX_CI") == "1"
        or (isinstance(env.get("CODEX_SANDBOX"), str) and env.get("CODEX_SANDBOX"))
    )


def unknown_agent_label(env: dict[str, str] | None = None) -> str | None:
    env = _env(env)
    if is_claude_cloud(env) or is_cursor_cloud(env) or is_codex_agent(env):
        return None
    if env.get("OPENCODE") == "1" or env.get("AI_AGENT") == "opencode":
        return "OpenCode"
    if env.get("PI_CODING_AGENT") == "true" or env.get("AI_AGENT") == "pi":
        return "pi"
    ai = env.get("AI_AGENT") or ""
    if ai and not ai.startswith("claude-code_"):
        return ai
    if env.get("AGENT") == "1":
        return "AGENT"
    return None


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _hook_command_exists(cmd: str, repo_root: Path) -> bool:
    """True only when the command names a script path that exists on disk."""
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    # Prefer an explicit path token (relative or absolute); ignore bare substrings.
    for token in cmd.replace(";", " ").replace("&&", " ").split():
        token = token.strip().strip("\"'")
        if not token or token in {"python3", "python", "node", "bash", "sh", "exec"}:
            continue
        if "/" not in token and not token.endswith(".py"):
            continue
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = repo_root / token
        if candidate.exists():
            return True
    return False


def missing_cursor_events(cursor_settings: dict | None, repo_root: Path) -> list[str]:
    hooks = (cursor_settings or {}).get("hooks") or {}
    missing = []
    for event in CURSOR_REQUIRED_EVENTS:
        entries = hooks.get(event)
        if not isinstance(entries, list) or not entries:
            missing.append(event)
            continue
        ok = False
        for entry in entries:
            cmd = entry.get("command") if isinstance(entry, dict) else None
            if isinstance(cmd, str) and _hook_command_exists(cmd, repo_root):
                ok = True
                break
        if not ok:
            missing.append(event)
    return missing


def _has_session_start(hooks: dict | None) -> bool:
    return isinstance(hooks, dict) and "SessionStart" in hooks


def _project_hooks_ok(
    repo_root: Path,
    harness: str,
    *,
    home: Path | None = None,
) -> tuple[bool, str]:
    if harness == "cursor":
        settings = _read_json(repo_root / ".cursor" / "hooks.json")
        missing = missing_cursor_events(settings, repo_root)
        if missing:
            return False, (
                f".cursor/hooks.json missing required events or scripts: {', '.join(missing)} "
                f"(run `./bin/agentized connect`). See {DOC}."
            )
        return True, "Cursor project hooks present."
    if harness == "claude":
        settings = _read_json(repo_root / ".claude" / "settings.json")
        hooks = (settings or {}).get("hooks") or {}
        if not _has_session_start(hooks):
            return False, (
                f".claude/settings.json missing SessionStart hooks "
                f"(run connect). See {DOC}."
            )
        return True, "Claude project hooks present."
    if harness == "codex":
        settings = _read_json(repo_root / ".codex" / "hooks.json")
        hooks = (settings or {}).get("hooks") or {}
        if _has_session_start(hooks):
            return True, "Codex project hooks present."
        # Documented alternative: user-level ~/.codex/hooks.json
        if home is not None:
            user = _read_json(home / ".codex" / "hooks.json")
            user_hooks = (user or {}).get("hooks") or {}
            if _has_session_start(user_hooks):
                return True, "Codex user-level hooks present (~/.codex/hooks.json)."
        return False, (
            ".codex/hooks.json missing SessionStart "
            "(run connect, trust project hooks, or paste user ~/.codex/hooks.json). See "
            f"{DOC}."
        )
    return False, f"unknown harness {harness}"

def check(
    *,
    env: dict[str, str] | None = None,
    home: Path | None = None,
    repo_root: Path | None = None,
    context_rel: str = DEFAULT_CONTEXT,
) -> dict[str, Any]:
    env = _env(env)
    home = home or Path(os.path.expanduser("~"))
    repo_root = (repo_root or find_repo_root()).resolve()
    cfg = load_env_check_config(repo_root, context_rel)
    cloud_git_mode = str(cfg.get("cloud_git_hooks") or "warn").lower()
    unknown_mode = str(cfg.get("unknown_agent") or "refuse").lower()

    # Local human / unmarked session
    if not (is_cursor_cloud(env) or is_claude_cloud(env) or is_codex_agent(env)):
        label = unknown_agent_label(env)
        if label:
            msg = (
                f"agent-env-check: REFUSED. Unsupported / unknown agent harness ({label}). "
                f"Only Claude, Cursor, or Codex recipes in {DOC} are supported. Stop."
            )
            if unknown_mode == "refuse":
                return {"ok": False, "refused": True, "message": msg, "severity": "unknown"}
            return {"ok": True, "refused": False, "message": "WARN: " + msg, "severity": "unknown-warn"}
        return {
            "ok": True,
            "refused": False,
            "message": (
                "agent-env-check: not a cloud/agent session; project hooks load from "
                ".cursor/hooks.json / .claude/settings.json / .codex/hooks.json after connect."
            ),
            "severity": "local",
        }

    if is_cursor_cloud(env):
        ok_hooks, hooks_msg = _project_hooks_ok(repo_root, "cursor")
        git_problem = git_hooks_problem(repo_root, home=home)
        parts = []
        if not ok_hooks:
            parts.append(hooks_msg)
        git_warn = None
        if git_problem:
            rem = (
                f"Add this exact line to the Cursor Cloud environment Install AND Start scripts "
                f"(Cursor Dashboard → Cloud Agents → this environment → Install / Start), "
                f"after Cursor has created ~/.cursor/agent-hooks/<id>/:\n  {INSTALL_LINE}\n"
                f"Then start a new session. Full steps: {DOC}."
            )
            if cloud_git_mode == "refuse":
                parts.append(f"{git_problem}. {rem}")
            else:
                git_warn = (
                    f"agent-env-check: WARN (cloud_git_hooks=warn). {git_problem}. "
                    f"Owner must paste before enabling refuse:\n  {INSTALL_LINE}\n"
                    f"See {DOC}. Flip context/env-check.json cloud_git_hooks → refuse after that."
                )
        if parts:
            return {
                "ok": False,
                "refused": True,
                "message": (
                    "agent-env-check: REFUSED. This Cursor cloud session is missing Agentized "
                    f"safety wiring: {'; '.join(parts)}. Stop. Do not rewrite "
                    "~/.cursor/agent-hooks by hand — the environment scripts must call "
                    "configure-cursor-agent-hooks.sh."
                ),
                "severity": "cursor",
                "git_warn": git_warn,
            }
        msg = "agent-env-check: Cursor project hooks reach this session."
        if git_warn:
            return {
                "ok": True,
                "refused": False,
                "message": msg + "\n" + git_warn,
                "severity": "cursor",
                "git_warn": git_warn,
            }
        return {
            "ok": True,
            "refused": False,
            "message": msg + " Agent-hooks git chain OK.",
            "severity": "cursor",
        }

    if is_claude_cloud(env):
        ok_hooks, hooks_msg = _project_hooks_ok(repo_root, "claude", home=home)
        # Cloud Claude often starts above the clone — also accept user bridge markers.
        user = _read_json(home / ".claude" / "settings.json")
        user_hooks = (user or {}).get("hooks") or {}
        if not ok_hooks and not _has_session_start(user_hooks):
            return {
                "ok": False,
                "refused": True,
                "message": (
                    "agent-env-check: REFUSED. Claude cloud session has no Agentized hooks "
                    f"({hooks_msg}). Ask the owner to add the Claude block in {DOC}, then "
                    "start a new session."
                ),
                "severity": "claude",
            }
        return {
            "ok": True,
            "refused": False,
            "message": "agent-env-check: Claude hooks reachable for this session.",
            "severity": "claude",
        }

    # Codex — project .codex/hooks.json or documented user ~/.codex/hooks.json
    ok_hooks, hooks_msg = _project_hooks_ok(repo_root, "codex", home=home)
    if not ok_hooks:
        return {
            "ok": False,
            "refused": True,
            "message": (
                f"agent-env-check: REFUSED. Codex session missing hooks ({hooks_msg}). "
                f"See {DOC}."
            ),
            "severity": "codex",
        }
    return {
        "ok": True,
        "refused": False,
        "message": f"agent-env-check: {hooks_msg}",
        "severity": "codex",
    }


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    root = find_repo_root()
    result = check(repo_root=root, context_rel=context)
    stream = sys.stdout if result["ok"] else sys.stderr
    stream.write(result["message"] + "\n")
    if result.get("git_warn") and result["ok"]:
        # already included in message
        pass
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
