"""Filesystem helpers for board_html (kept outside mutation include_globs)."""
from __future__ import annotations

from pathlib import Path


def read_task_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_html(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8", newline="\n")
