"""Collaboration / process-control checks (claim before edits, reviewable PR size)."""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .env_check import is_claude_cloud, is_codex_agent, is_cursor_cloud, unknown_agent_label
from .paths import DEFAULT_CONTEXT, find_repo_root
from .tasks import ACTIVE_STATUSES, list_tasks

PROCESS_FILENAME = "process-control.json"
DOC = "docs/process-control.md"


def default_process_config() -> dict[str, Any]:
    return {
        "version": 1,
        "reviewable_lines": 1500,
        "warn_at_pct": 75,
        "claim_required": True,
        "claim_mode_agent": "refuse",
        "claim_mode_local": "warn",
        "edit_path_globs": [
            "runtime/**",
            "scripts/**",
            "packages/**",
            "templates/**",
            "tests/**",
            ".githooks/**",
            ".github/**",
            "bin/**",
        ],
        "edit_path_excludes": [
            "context/tasks/**",
            "context/leases/**",
            "context/digests/**",
            "**/__pycache__/**",
            ".artifacts/**",
        ],
    }


def process_path(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    return root / context_rel / PROCESS_FILENAME


def load_process_config(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    path = process_path(root, context_rel)
    cfg = default_process_config()
    if not path.exists():
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return cfg
    if isinstance(data, dict):
        cfg.update({k: data[k] for k in data})
    return cfg


def is_agent_session(env: dict[str, str] | None = None) -> bool:
    env = dict(os.environ if env is None else env)
    if is_cursor_cloud(env) or is_claude_cloud(env) or is_codex_agent(env):
        return True
    return unknown_agent_label(env) is not None


def _match(path: str, patterns: list[str]) -> bool:
    path = path.replace("\\", "/")
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def path_needs_claim(path: str, cfg: dict[str, Any]) -> bool:
    path = path.replace("\\", "/").lstrip("./")
    excludes = list(cfg.get("edit_path_excludes") or [])
    if _match(path, excludes):
        return False
    globs = list(cfg.get("edit_path_globs") or [])
    if not globs:
        return True
    return _match(path, globs)


def active_claims(root: Path, context_rel: str = DEFAULT_CONTEXT) -> list[str]:
    tasks_dir = root / context_rel / "tasks"
    if not tasks_dir.is_dir():
        return []
    out = []
    for task in list_tasks(tasks_dir):
        if task.status not in ACTIVE_STATUSES:
            continue
        claim = (task.claim or "").strip()
        if not claim or claim.startswith("_"):
            continue
        if task.status == "in-progress" or claim:
            out.append(f"{task.task_id} ({claim}, {task.status})")
    # Prefer in-progress with non-empty claim
    preferred = [
        t
        for t in list_tasks(tasks_dir)
        if t.status == "in-progress" and (t.claim or "").strip() and not (t.claim or "").startswith("_")
    ]
    return [f"{t.task_id} ({t.claim}, {t.status})" for t in preferred] or out


def claim_check(
    root: Path,
    paths: list[str],
    *,
    context_rel: str = DEFAULT_CONTEXT,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    cfg = load_process_config(root, context_rel)
    if not cfg.get("claim_required", True):
        return {"ok": True, "mode": "disabled", "message": ""}
    watched = [p for p in paths if path_needs_claim(p, cfg)]
    if not watched:
        return {"ok": True, "mode": "skip", "message": ""}
    claims = active_claims(root, context_rel)
    if claims:
        return {
            "ok": True,
            "mode": "ok",
            "message": f"process-control: claim OK — {', '.join(claims)}",
            "claims": claims,
        }
    agent = is_agent_session(env)
    mode = str(
        cfg.get("claim_mode_agent" if agent else "claim_mode_local") or "warn"
    ).lower()
    msg = (
        "process-control: no in-progress task claim before code edits. "
        f"Claim first: `./bin/agentized claim <TASK_ID> --owner <you>`. See {DOC}."
    )
    if mode == "refuse":
        return {"ok": False, "mode": "refuse", "message": "REFUSED. " + msg, "paths": watched}
    return {"ok": True, "mode": "warn", "message": "WARN. " + msg, "paths": watched}


def _diff_insertions(root: Path, base_ref: str) -> int:
    proc = subprocess.run(
        ["git", "diff", "--numstat", f"{base_ref}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "diff", "--numstat", base_ref],
            cwd=root,
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        return 0
    total = 0
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        if parts[0] == "-":
            continue
        try:
            total += int(parts[0])
        except ValueError:
            continue
    return total


def size_check(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    base_ref: str | None = None,
) -> dict[str, Any]:
    cfg = load_process_config(root, context_rel)
    limit = int(cfg.get("reviewable_lines") or 1500)
    warn_pct = float(cfg.get("warn_at_pct") or 75)
    base = base_ref or os.environ.get("PROCESS_BASE") or "origin/main"
    insertions = _diff_insertions(root, base)
    warn_at = int(limit * warn_pct / 100.0)
    level = "ok"
    if insertions >= limit:
        level = "over"
    elif insertions >= warn_at:
        level = "warn"
    return {
        "ok": level != "over",
        "level": level,
        "insertions": insertions,
        "limit": limit,
        "warn_at": warn_at,
        "base": base,
        "message": (
            f"process-control: PR size {insertions} insertions vs {base} "
            f"(warn ≥{warn_at} = {warn_pct}% of {limit}; over ≥{limit}). See {DOC}."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    root = find_repo_root()
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    if args and args[0] == "size":
        result = size_check(root, context_rel=context)
        stream = sys.stdout if result["level"] != "over" else sys.stderr
        stream.write(result["message"] + "\n")
        return 0 if result["ok"] else 1
    if args and args[0] == "claim":
        paths = []
        if "--paths" in args:
            i = args.index("--paths")
            paths = args[i + 1 :]
        result = claim_check(root, paths or ["runtime/agentized/x.py"], context_rel=context)
        stream = sys.stdout if result["ok"] else sys.stderr
        if result.get("message"):
            stream.write(result["message"] + "\n")
        return 0 if result["ok"] else 1
    print("usage: process_control.py size|claim [--context CTX] [--paths ...]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
