"""Dry-run I/O helpers outside mutation include_globs (AGE-36)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .connect import QUALITY_MARKER
from .paths import CONNECT_MARKER_BEGIN, CONNECT_MARKER_END


def plan_marker_action(path: Path, body: str, *, create: bool) -> str:
    if not path.exists():
        return "create" if create else "skip"
    existing = path.read_text(encoding="utf-8")
    if CONNECT_MARKER_BEGIN in existing and CONNECT_MARKER_END in existing:
        pre = existing.split(CONNECT_MARKER_BEGIN, 1)[0]
        post = existing.split(CONNECT_MARKER_END, 1)[1]
        new_text = pre.rstrip() + "\n\n" + body.rstrip() + "\n" + post.lstrip("\n")
        if not new_text.endswith("\n"):
            new_text += "\n"
        return "skip" if new_text == existing else "update"
    return "merge"


def plan_template_action(src: Path, dst: Path) -> str:
    if not src.exists():
        return "skip"
    if not dst.exists():
        return "create"
    existing = dst.read_text(encoding="utf-8")
    if QUALITY_MARKER not in existing:
        return "skip"
    body = src.read_text(encoding="utf-8")
    return "skip" if existing == body else "update"


def plan_hooks_path_action(root: Path) -> str:
    if not ((root / ".git").exists() or (root / ".git").is_file()):
        return "skip"
    proc = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    current = (proc.stdout or "").strip() if proc.returncode == 0 else ""
    wanted = ".githooks"
    if not current:
        return "create"
    norm = current.replace("\\", "/").rstrip("/")
    if norm in {wanted, str((root / wanted).resolve()).replace("\\", "/")}:
        return "skip"
    return "skip"


def plan_json_document_action(path: Path, desired: dict[str, Any]) -> str:
    text = json.dumps(desired, indent=2) + "\n"
    if not path.exists():
        return "create"
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        return "update"
    return "skip" if existing == text else "update"
