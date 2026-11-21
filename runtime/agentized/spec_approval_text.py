"""Text helpers for spec-approval ."""
from __future__ import annotations

import re

APPROVED_BY_RE = re.compile(r"(?im)^\s*approved-by:\s*(.+?)\s*$")
EMAIL_RE = re.compile(r"<([^>]+)>")
PLACEHOLDER_BODIES = frozenset({"todo", "tbd", "...", "…", "todo.", "tbd."})
TODO_PREFIX = "todo"
TBD_PREFIX = "tbd"
ITALIC_PLACEHOLDER_MARK = "_("
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
    """TODO / TBD / … / _(…) lines and empty bodies are not real Spec content."""
    if spec is None:
        return True
    s = spec.strip()
    if not s:
        return True
    for line in s.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if low in PLACEHOLDER_BODIES:
            return True
        if low.startswith(TODO_PREFIX) or low.startswith(TBD_PREFIX):
            return True
        if low.startswith("...") or stripped.startswith("…"):
            return True
        if ITALIC_PLACEHOLDER_MARK in stripped:
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


def _email_local_part(email: str) -> str:
    return email.partition("@")[0]


def _email_local_matches_claim(email: str, claim_locals: set[str]) -> bool:
    if not claim_locals:
        return False
    if "@" not in email:
        return False
    local = _email_local_part(email)
    if local in claim_locals:
        return True
    for lp in claim_locals:
        if local.endswith("+" + lp):
            return True
    return False


def is_claim_owner_identity(identity: str, claim: str) -> bool:
    """True when identity is the claim owner (exact, full-email, or claim local-part)."""
    if identity is None or claim is None:
        return False
    claim_s = claim.strip().lower()
    ident = identity.strip()
    if not claim_s:
        return False
    if not ident:
        return False
    if ident.lower() == claim_s:
        return True
    id_emails = identity_emails(ident)
    claim_emails = identity_emails(claim)
    if claim_emails:
        if id_emails & claim_emails:
            return True
        locals_ = {_email_local_part(e) for e in claim_emails}
        return any(_email_local_matches_claim(e, locals_) for e in id_emails)
    if not id_emails:
        return False
    return any(_email_local_matches_claim(e, {claim_s}) for e in id_emails)


def participant_email_matches(identity: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return False
    emails = identity_emails(identity)
    if not emails:
        return False
    return any(emails & identity_emails(entry) for entry in allowlist)
