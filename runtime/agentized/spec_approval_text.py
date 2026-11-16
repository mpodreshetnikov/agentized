"""Text helpers for spec-approval ."""
from __future__ import annotations

import re

APPROVED_BY_RE = re.compile(r"(?im)^\s*approved-by:\s*(.+?)\s*$")
EMAIL_RE = re.compile(r"<([^>]+)>")
PLACEHOLDER_BODIES = frozenset({"todo", "tbd", "...", "…", "todo.", "tbd."})
TODO_PREFIX = "todo"
TODO_MAX_LEN = 8
HEADING_PREFIX = "## "


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
        if line.startswith(HEADING_PREFIX) and line.strip() != heading:
            break
        body.append(line)
    return "\n".join(body).strip()


def parse_tags(raw: str) -> set[str]:
    if raw is None:
        return set()
    return {t.strip().lower() for t in raw.replace(",", " ").split() if t.strip()}


def parse_approvers(approval_body: str) -> list[str]:
    if approval_body is None:
        return []
    return [
        m.group(1).strip()
        for m in APPROVED_BY_RE.finditer(approval_body)
        if m.group(1).strip()
    ]


def is_placeholder_spec(spec: str) -> bool:
    """TODO / … / _(…) and empty bodies are not real Spec content."""
    if spec is None:
        return True
    s = spec.strip()
    if not s:
        return True
    if s.startswith("_("):
        return True
    first = s.splitlines()[0].strip().lower()
    if first in PLACEHOLDER_BODIES:
        return True
    if first.startswith(TODO_PREFIX) and len(first) <= TODO_MAX_LEN:
        return True
    return False


def identity_emails(identity: str) -> set[str]:
    """Full email only — no local-part matching."""
    if identity is None:
        return set()
    s = identity.strip().lower()
    if not s:
        return set()
    m = EMAIL_RE.search(s)
    if m:
        email = m.group(1).strip().lower()
        return {email} if "@" in email else set()
    if "@" in s and s.count(" ") == 0 and s.count("<") == 0:
        return {s}
    return set()


def participant_email_matches(identity: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return False
    emails = identity_emails(identity)
    if not emails:
        return False
    return any(emails & identity_emails(entry) for entry in allowlist)
