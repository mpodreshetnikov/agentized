"""Text helpers for spec-approval ."""
from __future__ import annotations

import re

APPROVED_BY_RE = re.compile(r"(?im)^\s*approved-by:\s*(.+?)\s*$")
PLACEHOLDER_BODIES = frozenset(
    {
        "todo",
        "tbd",
        "...",
        "…",
        "todo.",
        "tbd.",
        "…",
        "...",
    }
)


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


def is_placeholder_spec(spec: str) -> bool:
    """TODO / … / _(…) and empty bodies are not real Spec content."""
    s = (spec or "").strip()
    if not s:
        return True
    if s.startswith("_("):
        return True
    first = s.splitlines()[0].strip().lower()
    if first in PLACEHOLDER_BODIES:
        return True
    if first.startswith("todo") and len(first) <= 8:
        return True
    if s in {"...", "…"}:
        return True
    return False


EMAIL_RE = re.compile(r"<([^>]+)>")


def identity_emails(identity: str) -> set[str]:
    """Full email only — no local-part matching."""
    s = (identity or "").strip().lower()
    if not s:
        return set()
    m = EMAIL_RE.search(s)
    if m:
        email = m.group(1).strip().lower()
        return {email} if "@" in email else set()
    if "@" in s and " " not in s and "<" not in s:
        return {s}
    return set()


def participant_email_matches(identity: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return False
    emails = identity_emails(identity)
    if not emails:
        return False
    return any(emails & identity_emails(entry) for entry in allowlist)
