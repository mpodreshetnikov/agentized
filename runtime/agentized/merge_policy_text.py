"""String helpers for merge/authorship."""

from __future__ import annotations

import re
from typing import Any

from .merge_policy_defaults import DEFAULT_AGENT_TRAILER_PREFIXES

EMAIL_RE = re.compile(r"<([^>]+)>")
BARE_EMAIL_RE = re.compile(r"^[^<\s]+@[^<\s]+$")
COAUTHOR_RE = re.compile(r"(?im)^\s*co-authored-by:\s*(.+?)\s*$")


def trailer_prefixes(ha: dict[str, Any] | None) -> list[str]:
    ha = ha or {}
    raw = ha.get("agent_trailer_prefixes")
    if isinstance(raw, list) and raw:
        return [str(p) for p in raw if str(p).strip()]
    return list(DEFAULT_AGENT_TRAILER_PREFIXES)


def identity_emails(identity: str) -> set[str]:
    """Full email addresses only — no local-part or bare-name matching."""
    if not identity:
        return set()
    s = identity.strip().lower()
    if not s:
        return set()
    emails: set[str] = set()
    m = EMAIL_RE.search(s)
    if m:
        email = m.group(1).strip().lower()
        if "@" in email:
            emails.add(email)
        return emails
    if BARE_EMAIL_RE.fullmatch(s):
        emails.add(s)
    return emails


def participant_matches(identity: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return False
    id_emails = identity_emails(identity)
    if not id_emails:
        return False
    return any(id_emails & identity_emails(entry) for entry in allowlist)


def parse_coauthors(message: str) -> list[str]:
    return [m.group(1).strip() for m in COAUTHOR_RE.finditer(message) if m.group(1).strip()]


def is_agent_trailer_line(line: str, prefixes: list[str] | tuple[str, ...]) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    for prefix in prefixes:
        p = prefix.strip()
        if p and lower.startswith(p.lower()):
            return True
    return False


def strip_agent_trailers(message: str, prefixes: list[str] | tuple[str, ...] | None = None) -> str:
    prefixes = list(prefixes) if prefixes is not None else list(DEFAULT_AGENT_TRAILER_PREFIXES)
    lines = message.splitlines()
    kept = [ln for ln in lines if not is_agent_trailer_line(ln, prefixes)]
    while kept and kept[-1].strip() == "":
        kept.pop()
    if not kept:
        return ""
    text = "\n".join(kept)
    if message.endswith("\n"):
        text += "\n"
    return text


def count_stripped_lines(original: str, cleaned: str) -> int:
    if cleaned == original:
        return 0
    before = len([ln for ln in original.splitlines() if ln.strip()])
    after = len([ln for ln in cleaned.splitlines() if ln.strip()])
    return max(0, before - after)
