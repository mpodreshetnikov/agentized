"""Filesystem helpers for board_html (AGE-37)."""
from __future__ import annotations

from pathlib import Path

ENCODING = "utf-8"


def read_task_text(path: Path) -> str:
    return path.read_bytes().decode(ENCODING)


def write_html(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(html_text.encode(ENCODING))
