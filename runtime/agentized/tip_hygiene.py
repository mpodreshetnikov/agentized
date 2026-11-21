"""PR tip hygiene: linked tasks must be self-review/done, claim-free; INDEX fresh (AGE-76)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from .status_gates import (
    GateResult,
    extract_status,
    normalize_status,
    parse_task_fields,
)
from .task_schema import (
    PLACEHOLDER_CLAIM,
    append_progress,
    append_status_progress,
    rebuild_task_index,
    set_field,
)

TIP_OK_STATUSES: frozenset[str] = frozenset({"self-review", "done"})
INDEX_NAME = "INDEX.md"

# Captures #N / PR #N / github.com/owner/repo/pull/N
_PR_NUM_RE = re.compile(r"(?i)(?:https://github\.com/[^/\s]+/[^/\s]+/pull/|#|PR\s*#?)(\d+)\b")
_GITHUB_PULL_REF_RE = re.compile(r"^refs/pull/(\d+)(?:/|$)")

MSG_TIP_STATUS = "{name}: tip hygiene: pr #{pr} task must be self-review or done (got {st})"
MSG_TIP_CLAIM = "{name}: tip hygiene: pr #{pr} task must release claim (got {claim!r})"
MSG_TIP_INDEX = "tip hygiene: INDEX.md out of date — run agentized index and commit"
MSG_TIP_UNREADABLE = "{name}: tip hygiene: unreadable task file: {detail}"
MSG_READY_NOTE = "ready requires non-empty review_note"
MSG_READY_MISSING = "ready: missing task {task_id}"


def extract_pr_number(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    m = _PR_NUM_RE.search(raw)
    if not m:
        return None
    return int(m.group(1))


def resolve_pr_number(
    *,
    explicit: int | str | None = None,
    env: Mapping[str, str] | None = None,
) -> int | None:
    if explicit is not None:
        if isinstance(explicit, int):
            return explicit if explicit > 0 else None
        n = extract_pr_number(str(explicit))
        if n is None:
            digits = str(explicit).strip()
            if digits.isdigit():
                n = int(digits)
        return n if n and n > 0 else None
    e = os.environ if env is None else env
    for key in ("AGENTIZED_PR", "TIP_HYGIENE_PR", "GITHUB_PR_NUMBER"):
        raw = (e.get(key) or "").strip()
        if not raw:
            continue
        n = extract_pr_number(raw if not raw.isdigit() else f"#{raw}")
        if n is not None and n > 0:
            return n
    ref = (e.get("GITHUB_REF") or "").strip()
    m = _GITHUB_PULL_REF_RE.match(ref)
    if m:
        n = int(m.group(1))
        return n if n > 0 else None
    return None


def claim_is_held(claim: str | None) -> bool:
    if claim is None:
        return False
    val = claim.strip()
    return bool(val) and (not val.startswith("_"))


def task_points_at_pr(pr_field: str | None, pr_number: int) -> bool:
    n = extract_pr_number(pr_field)
    return n is not None and n == pr_number


def validate_index_freshness(tasks_dir: Path) -> GateResult:
    index_path = tasks_dir / INDEX_NAME
    expected = rebuild_task_index(tasks_dir)
    if not index_path.is_file():
        return GateResult(False, (MSG_TIP_INDEX,))
    try:
        actual = index_path.read_text(encoding="utf-8")
    except OSError:
        return GateResult(False, (MSG_TIP_INDEX,))
    if actual != expected:
        return GateResult(False, (MSG_TIP_INDEX,))
    return GateResult(True)


def validate_pr_linked_tasks(tasks_dir: Path, pr_number: int) -> GateResult:
    errors: list[str] = []
    for path in sorted(tasks_dir.glob("T-*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(MSG_TIP_UNREADABLE.format(name=path.name, detail=exc))
            continue
        fields = parse_task_fields(text)
        pr_raw = (fields.get("pr") or "").strip()
        if not task_points_at_pr(pr_raw, pr_number):
            continue
        st = extract_status(text) or normalize_status(fields.get("статус"))
        if st not in TIP_OK_STATUSES:
            errors.append(MSG_TIP_STATUS.format(name=path.name, pr=pr_number, st=st or ""))
        claim = (fields.get("claim") or "").strip()
        if claim_is_held(claim):
            errors.append(MSG_TIP_CLAIM.format(name=path.name, pr=pr_number, claim=claim))
    return GateResult(ok=not errors, errors=tuple(errors))


def validate_tip_hygiene(
    tasks_dir: Path,
    *,
    pr_number: int | None = None,
    check_index: bool = True,
) -> GateResult:
    errors: list[str] = []
    if check_index:
        idx = validate_index_freshness(tasks_dir)
        if not idx.ok:
            errors.extend(idx.errors)
    if pr_number is not None and pr_number > 0:
        linked = validate_pr_linked_tasks(tasks_dir, pr_number)
        if not linked.ok:
            errors.extend(linked.errors)
    return GateResult(ok=not errors, errors=tuple(errors))


def apply_ready(
    text: str,
    *,
    review_note: str,
    pr: str | None = None,
) -> str:
    note = (review_note or "").strip()
    if not note or note.startswith("_"):
        raise ValueError(MSG_READY_NOTE)
    out = set_field(text, "статус", "self-review")
    out = set_field(out, "claim", PLACEHOLDER_CLAIM)
    out = set_field(out, "review_note", note)
    if pr is not None and str(pr).strip():
        out = set_field(out, "pr", str(pr).strip())
    out = append_status_progress(out, "self-review")
    out = append_progress(out, "ready: claim released")
    return out


def write_ready(
    tasks_dir: Path,
    task_id: str,
    *,
    review_note: str,
    pr: str | None = None,
) -> Path:
    path = tasks_dir / f"{task_id}.md"
    if not path.is_file():
        raise FileNotFoundError(MSG_READY_MISSING.format(task_id=task_id))
    text = apply_ready(path.read_text(encoding="utf-8"), review_note=review_note, pr=pr)
    path.write_text(text, encoding="utf-8")
    (tasks_dir / INDEX_NAME).write_text(rebuild_task_index(tasks_dir), encoding="utf-8")
    return path
