"""Text helpers for spec-approval."""

from __future__ import annotations

import re

# [ \t] only — \s would swallow newlines and merge following lines into the value.
APPROVED_BY_RE = re.compile(r"(?im)^[ \t]*approved-by:[ \t]*(.+?)[ \t]*$")
EMAIL_RE = re.compile(r"<([^>]+)>")
PLACEHOLDER_BODIES = frozenset(
    {
        "todo",
        "tbd",
        "...",
        "…",
        "todo.",
        "tbd.",
        "x",
        ".",
        "ok",
        "n/a",
        "na",
        "none",
        "wip",
        "see chat",
    }
)
TODO_PREFIX = "todo"
TBD_PREFIX = "tbd"
ITALIC_PLACEHOLDER_MARK = "_("
HEADING_PREFIX = "## "
FILL_MARKERS = ("<fill>", "fill-me", "fillme")
UNCHECKED_BOX = "[ ]"
MIN_REAL_SPEC_WORDS = 3
FENCE_MARK = "```"

# Agent / bot commit locals treated as the claim owner for blame (not human approvers).
AGENT_COMMIT_LOCALS = frozenset(
    {
        "cursoragent",
        "github-actions",
        "dependabot",
        "renovate",
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
        if line.startswith(HEADING_PREFIX) and line.strip() != heading:
            break
        body.append(line)
    return "\n".join(body).strip()


def parse_tags(raw: str) -> set[str]:
    if raw is None:
        return set()
    return {t.strip().lower() for t in raw.replace(",", " ").split() if t.strip()}


def _approval_body_without_fences(approval_body: str) -> str:
    """Drop fenced code blocks so example approved-by lines do not count."""
    # Split on fence markers: even chunks are outside fences.
    chunks = approval_body.split(FENCE_MARK)
    return "".join(chunks[i] for i in range(0, len(chunks), 2))


def parse_approvers(approval_body: str) -> list[str]:
    if approval_body is None:
        return []
    text = _approval_body_without_fences(approval_body)
    found: list[str] = []
    for m in APPROVED_BY_RE.finditer(text):
        value = m.group(1).strip()
        if not value:
            continue
        if value.startswith(ITALIC_PLACEHOLDER_MARK):
            continue
        found.append(value)
    return found


def is_placeholder_spec(spec: str) -> bool:
    """TODO / TBD / … / _(…) / trivial / fill markers are not real Spec content."""
    if spec is None:
        return True
    s = spec.strip()
    if not s:
        return True
    if not any(ch.isalnum() for ch in s):
        return True
    low_full = s.lower()
    if low_full in PLACEHOLDER_BODIES:
        return True
    for marker in FILL_MARKERS:
        if marker in low_full:
            return True
    if UNCHECKED_BOX in s:
        return True
    first = s.splitlines()[0].strip().lower()
    if first.endswith(TBD_PREFIX) or first.endswith(TODO_PREFIX):
        return True
    words = [w for w in re.split(r"\s+", s) if w]
    if len(words) < MIN_REAL_SPEC_WORDS:
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


def is_agent_commit_identity(identity: str) -> bool:
    """True for known agent/bot commit addresses (e.g. cursoragent@…)."""
    if identity is None:
        return False
    ident = identity.strip()
    if not ident:
        return False
    low = ident.lower()
    if low in AGENT_COMMIT_LOCALS:
        return True
    emails = identity_emails(ident)
    for email in emails:
        if _email_local_part(email) in AGENT_COMMIT_LOCALS:
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


def is_owner_or_agent_identity(identity: str, claim: str) -> bool:
    """Claim owner or agent commit identity — neither counts as a human non-owner."""
    return is_agent_commit_identity(identity) or is_claim_owner_identity(identity, claim)


def participant_email_matches(identity: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return False
    emails = identity_emails(identity)
    if not emails:
        return False
    return any(emails & identity_emails(entry) for entry in allowlist)


def human_committer_emails(committers: set[str] | list[str] | None) -> set[str]:
    """Normalize committer identities to emails; drop agent/bot addresses."""
    if committers is None:
        return set()
    out: set[str] = set()
    for raw in committers:
        if is_agent_commit_identity(raw):
            continue
        out |= identity_emails(raw)
    return out
