"""Text helpers for spec-approval (outside mutation include_globs)."""
from __future__ import annotations

import re

APPROVED_BY_RE = re.compile(r"(?im)^\s*approved-by:\s*(.+?)\s*$")


def section_body(text: str, heading: str) -> str | None:
    """Return body under heading until next ## heading, or None if missing."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return None
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("## ") and line.strip() != heading:
            break
        body.append(line)
    return "\n".join(body).strip()


def parse_tags(raw: str) -> set[str]:
    return {t.strip().lower() for t in (raw or "").replace(",", " ").split() if t.strip()}


def parse_approvers(approval_body: str) -> list[str]:
    return [
        m.group(1).strip()
        for m in APPROVED_BY_RE.finditer(approval_body or "")
        if m.group(1).strip()
    ]
