"""PR tip hygiene + INDEX freshness hard gates (AGE-76)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .status_gates import GateResult, TEXT_ENCODING, extract_status, parse_task_fields

MSG_TIP_STATUS = (
    "{name}: tip hygiene: pr points at #{num} but статус={st} (need self-review|done)"
)
MSG_TIP_CLAIM = (
    "{name}: tip hygiene: pr points at #{num} but claim is held ({claim!r}); release claim"
)
MSG_INDEX_STALE = "INDEX.md ≠ rebuild_task_index — run agentized index"
MSG_UNREADABLE = "unreadable task file: {detail}"
TIP_HYGIENE_OK_STATUSES: frozenset[str] = frozenset({"self-review", "done"})
PR_NUMBER_RE = re.compile(
    r"(?i)(?:https://github\.com/[^/\s]+/[^/\s]+/pull/|PR\s*#|#|pull/)(\d+)\b"
)
PR_DIGITS_RE = re.compile(r"^\d+$")
GITHUB_PULL_REF_RE = re.compile(r"^refs/pull/(\d+)(?:/|$)")
EMPTY_CLAIM_PLACEHOLDER = "_(пусто)_"


def _nonempty_field(fields: dict[str, str], *keys: str) -> str:
    for key in keys:
        val = (fields.get(key) or "").strip()
        if val and (not val.startswith("_")):
            return val
    return ""


def _read_task_text(path: Path) -> str:
    return path.read_bytes().decode(TEXT_ENCODING)


def parse_pr_number(value: str | int | None) -> int | None:
    """Extract a GitHub PR number from a task ``pr:`` field, env value, or int."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    if PR_DIGITS_RE.match(text):
        num = int(text)
        return num if num > 0 else None
    match = PR_NUMBER_RE.search(text)
    if not match:
        return None
    num = int(match.group(1))
    return num if num > 0 else None


def _pr_from_github_event_path(path: str) -> int | None:
    try:
        raw = Path(path).read_text(encoding=TEXT_ENCODING)
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("pull_request", "issue"):
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        if key == "issue" and "pull_request" not in block:
            continue
        num = parse_pr_number(block.get("number"))
        if num is not None:
            return num
    return parse_pr_number(data.get("number"))


def resolve_validate_pr_number(*, explicit: str | int | None = None) -> int | None:
    """PR under validation: explicit → TASKS_VALIDATE_PR / GITHUB_* → event payload."""
    direct = parse_pr_number(explicit)
    if direct is not None:
        return direct
    for key in ("TASKS_VALIDATE_PR", "GITHUB_PR_NUMBER", "PULL_REQUEST_NUMBER"):
        env = (os.environ.get(key) or "").strip()
        if not env:
            continue
        num = parse_pr_number(env)
        if num is not None:
            return num
    ref = (os.environ.get("GITHUB_REF") or "").strip()
    ref_match = GITHUB_PULL_REF_RE.match(ref)
    if ref_match:
        return int(ref_match.group(1))
    event_path = (os.environ.get("GITHUB_EVENT_PATH") or "").strip()
    if event_path:
        return _pr_from_github_event_path(event_path)
    return None


def claim_is_held(claim: str | None) -> bool:
    """True when claim is a real owner (not empty / ``_(…)`` placeholder)."""
    val = (claim or "").strip()
    return bool(val) and (not val.startswith("_"))


def task_pr_matches(pr_field: str | None, pr_number: int) -> bool:
    num = parse_pr_number(pr_field)
    return num is not None and num == pr_number


def validate_tip_hygiene(
    tasks_dir: Path,
    *,
    pr_number: int | None,
    skip_stems: frozenset[str] | None = None,
) -> GateResult:
    """Fail when a task ``pr:`` points at this PR but tip is not self-review/done or still claimed."""
    if pr_number is None:
        return GateResult(True)
    skip = skip_stems or frozenset()
    errors: list[str] = []
    for path in sorted(tasks_dir.glob("T-*.md")):
        if path.stem in skip:
            continue
        try:
            text = _read_task_text(path)
        except (UnicodeDecodeError, OSError) as exc:
            errors.append(f"{path.name}: {MSG_UNREADABLE.format(detail=exc)}")
            continue
        fields = parse_task_fields(text)
        pr_raw = _nonempty_field(fields, "pr")
        if not pr_raw or not task_pr_matches(pr_raw, pr_number):
            continue
        st = extract_status(text)
        if st not in TIP_HYGIENE_OK_STATUSES:
            errors.append(MSG_TIP_STATUS.format(name=path.name, num=pr_number, st=st or ""))
        claim = (fields.get("claim") or "").strip()
        if claim_is_held(claim):
            errors.append(MSG_TIP_CLAIM.format(name=path.name, num=pr_number, claim=claim))
    return GateResult(ok=not errors, errors=tuple(errors))


def validate_index_freshness(tasks_dir: Path) -> GateResult:
    """Hard-fail when ``INDEX.md`` is not exactly ``rebuild_task_index`` output."""
    from .task_schema import rebuild_task_index

    expected = rebuild_task_index(tasks_dir)
    path = tasks_dir / "INDEX.md"
    try:
        current = path.read_text(encoding=TEXT_ENCODING) if path.exists() else ""
    except (UnicodeDecodeError, OSError) as exc:
        return GateResult(False, (MSG_UNREADABLE.format(detail=exc),))
    if current != expected:
        return GateResult(False, (MSG_INDEX_STALE,))
    return GateResult(True)


def apply_ready(
    text: str,
    *,
    pr: str | None = None,
    review_note: str | None = None,
) -> str:
    """Flip task → self-review, release claim to ``_(пусто)_``, append Progress (AGE-76)."""
    from .task_schema import append_status_progress, set_field

    out = text
    if pr is not None and str(pr).strip():
        out = set_field(out, "pr", str(pr).strip())
    if review_note is not None and str(review_note).strip():
        out = set_field(out, "review_note", str(review_note).strip())
    out = set_field(out, "статус", "self-review")
    out = set_field(out, "claim", EMPTY_CLAIM_PLACEHOLDER)
    return append_status_progress(out, "self-review")


def run_tip_hygiene_gates(
    tasks_dir: Path,
    *,
    pr_number: str | int | None = None,
    check_index: bool = True,
) -> GateResult:
    """Compose tip hygiene + optional INDEX freshness (hard by default)."""
    resolved = resolve_validate_pr_number(explicit=pr_number)
    errors: list[str] = []
    tip = validate_tip_hygiene(tasks_dir, pr_number=resolved)
    if not tip.ok:
        errors.extend(tip.errors)
    if check_index:
        idx = validate_index_freshness(tasks_dir)
        if not idx.ok:
            errors.extend(idx.errors)
    return GateResult(ok=not errors, errors=tuple(errors))
