from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .leases import find_overlaps, list_leases, warn_message
from .paths import DEFAULT_CONTEXT, find_repo_root, load_state


def read_stdin_json() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def resolve_root(payload: dict | None = None) -> Path:
    payload = payload or {}
    for key in ("workspace_roots", "workspaceRoots"):
        roots = payload.get(key)
        if isinstance(roots, list) and roots:
            return Path(roots[0]).resolve()
    for key in ("cwd", "working_directory", "workingDirectory"):
        if payload.get(key):
            return find_repo_root(Path(payload[key]))
    env_root = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CURSOR_PROJECT_DIR")
    if env_root:
        return Path(env_root).resolve()
    return find_repo_root()


def context_rel(root: Path) -> str:
    state = load_state(root)
    return state.get("context") or DEFAULT_CONTEXT


def nav_reminder(root: Path) -> str:
    rel = context_rel(root)
    nav = root / rel / "NAV.md"
    agents = root / "AGENTS.md"
    lines = [
        "Agentized session check:",
        f"- Project Context: {rel}/",
        f"- Read {rel}/NAV.md first; follow only its links.",
        f"- Live board: {rel}/tasks/INDEX.md (no full tasks/ listing).",
        f"- Leases warn-only: {rel}/leases/INDEX.md",
    ]
    if not agents.exists():
        lines.append("WARN: AGENTS.md missing.")
    elif "NAV.md" not in agents.read_text(encoding="utf-8"):
        lines.append("WARN: AGENTS.md has no NAV.md pointer — run agentized connect.")
    if not nav.exists():
        lines.append(f"WARN: {rel}/NAV.md missing.")
    else:
        lines.append(f"OK: {rel}/NAV.md present.")
    return "\n".join(lines)


def extract_paths(payload: dict) -> list[str]:
    paths: list[str] = []
    for key in ("file_path", "filePath", "path", "file"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            paths.append(val.strip())
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if isinstance(tool_input, dict):
        for key in ("file_path", "filePath", "path", "file", "target_file"):
            val = tool_input.get(key)
            if isinstance(val, str) and val.strip():
                paths.append(val.strip())
        # apply_patch / edits lists
        for key in ("edits", "files"):
            items = tool_input.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str):
                        paths.append(item)
                    elif isinstance(item, dict):
                        for k in ("path", "file_path", "filePath"):
                            if item.get(k):
                                paths.append(str(item[k]))
    # shell command heuristics
    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    command = command or str(payload.get("command") or "")
    if command:
        for m in re.finditer(r"(?:^|\s)([\w./-]+\.[A-Za-z0-9]+)(?:\s|$)", command):
            paths.append(m.group(1))
        for m in re.finditer(r"(?:^|\s)((?:src|runtime|context|packages|docs)/[\w./-]+)", command):
            paths.append(m.group(1))
    # nested cursor-style
    for key in ("edits", "files"):
        items = payload.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("path"):
                    paths.append(str(item["path"]))
                elif isinstance(item, str):
                    paths.append(item)
    # unique
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        p = p.lstrip("./")
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def lease_warn_for_paths(root: Path, paths: list[str], *, ignore_task: str | None = None) -> str:
    if not paths:
        return ""
    rel = context_rel(root)
    leases_dir = root / rel / "leases"
    if not leases_dir.exists():
        return ""
    overlaps = find_overlaps(list_leases(leases_dir), paths, ignore_task=ignore_task)
    return warn_message(overlaps)
