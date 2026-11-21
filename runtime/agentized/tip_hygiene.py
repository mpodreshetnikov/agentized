"""PR tip hygiene: linked tasks must be self-review/done, claim-free; INDEX fresh (AGE-76)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .status_gates import (
    TEXT_ENCODING,
    GateResult,
    extract_status,
    parse_task_fields,
)
from .task_schema import (
    PLACEHOLDER_PARENT,
    append_progress,
    append_status_progress,
    rebuild_task_index,
    set_field,
)

TIP_OK_STATUSES: frozenset[str] = frozenset({"self-review", "done"})
INDEX_NAME = "INDEX.md"
READY_PROGRESS = "ready: claim released"
READY_FROM = "in-progress"
READY_NOOP_STATUS = "self-review"
CLAIM_EMPTY = "_(пусто)_"
# Only empty / _(пусто)_ count as released — template "_(пусто или кто ведёт)_" is held.
CLAIM_RELEASED: frozenset[str] = frozenset({"", CLAIM_EMPTY})
ENV_PR_KEYS: tuple[str, ...] = ("AGENTIZED_PR", "TIP_HYGIENE_PR", "GITHUB_PR_NUMBER")

_PR_NUM_RE = re.compile(r"(?i)(?:https://github\.com/[^/\s]+/[^/\s]+/pull/|#|PR\s*#?)(\d+)\b")
_GITHUB_PULL_REF_RE = re.compile(r"^refs/pull/(\d+)(?:/|$)")

MSG_TIP_STATUS = "{name}: tip hygiene: pr #{pr} task must be self-review or done (got {st})"
MSG_TIP_CLAIM = "{name}: tip hygiene: pr #{pr} task must release claim (got {claim!r})"
MSG_TIP_PARENT = (
    "{name}: tip hygiene: pr #{pr} task must not keep template родитель/parent "
    "(got {parent!r})"
)
MSG_TIP_INDEX = "tip hygiene: INDEX.md out of date — run agentized index and commit"
MSG_TIP_UNREADABLE = "{name}: tip hygiene: unreadable task file: {detail}"
MSG_TIP_NO_LINKED = "tip hygiene: no task with pr: pointing at #{pr}"
MSG_TIP_PR_REQUIRED = (
    "tip hygiene: pull_request requires a resolvable PR number "
    "(GITHUB_REF refs/pull/N/… or matching --pr / AGENTIZED_PR)"
)
MSG_TIP_PR_CONFLICT = (
    "tip hygiene: PR number conflict: github=#{github}, override=#{override} "
    "(env/--pr must agree with GITHUB_REF)"
)
MSG_READY_NOTE = "ready requires non-empty review_note"
MSG_READY_MISSING = "ready: missing task {task_id}"
MSG_READY_STATUS = (
    "ready refuses status {st!r}; only in-progress "
    "(self-review is a no-op; done/idea/blocked/… refused)"
)


@dataclass(frozen=True)
class PrResolution:
    pr_number: int | None
    errors: tuple[str, ...] = ()


def _read_text(path: Path) -> str:
    return path.read_bytes().decode(TEXT_ENCODING)


def _write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode(TEXT_ENCODING))


def _header_field(fields: dict[str, str], key: str) -> str:
    val = fields.get(key)
    if val is None:
        return ""
    return val.strip()


def extract_pr_number(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    m = _PR_NUM_RE.search(raw)
    if not m:
        return None
    return int(m.group(1))


def _parse_positive(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    n = extract_pr_number(str(value))
    if n is None or n <= 0:
        return None
    return n


def github_pr_number(env: Mapping[str, str]) -> int | None:
    ref_raw = env.get("GITHUB_REF")
    if ref_raw is None:
        return None
    ref = ref_raw.strip()
    if not ref:
        return None
    m = _GITHUB_PULL_REF_RE.match(ref)
    if not m:
        return None
    n = int(m.group(1))
    return n if n > 0 else None


def env_override_pr_number(env: Mapping[str, str]) -> int | None:
    for key in ENV_PR_KEYS:
        raw = env.get(key)
        if raw is None:
            continue
        raw = raw.strip()
        if not raw:
            continue
        n = extract_pr_number(raw)
        if n is not None and n > 0:
            return n
    return None


def resolve_pr(
    *,
    explicit: int | str | None = None,
    env: Mapping[str, str] | None = None,
) -> PrResolution:
    """Resolve PR number. In CI, GITHUB_REF wins; env/--pr must agree or error."""
    e = os.environ if env is None else env
    github = github_pr_number(e)
    override = env_override_pr_number(e)
    expl = _parse_positive(explicit)
    errors: list[str] = []

    if github is not None:
        for other in (override, expl):
            if other is not None and other != github:
                errors.append(MSG_TIP_PR_CONFLICT.format(github=github, override=other))
        if errors:
            return PrResolution(None, tuple(dict.fromkeys(errors)))
        return PrResolution(github)

    # No github PR (push/local): explicit then env.
    chosen = expl if expl is not None else override
    event_raw = e.get("GITHUB_EVENT_NAME")
    if event_raw is not None and event_raw.strip() == "pull_request" and chosen is None:
        errors.append(MSG_TIP_PR_REQUIRED)
    return PrResolution(chosen, tuple(errors))


def resolve_pr_number(
    *,
    explicit: int | str | None = None,
    env: Mapping[str, str] | None = None,
) -> int | None:
    """Compatibility helper — PR number only (ignores conflict errors). Prefer resolve_pr."""
    return resolve_pr(explicit=explicit, env=env).pr_number


def claim_is_held(claim: str | None) -> bool:
    if claim is None:
        return False
    return claim.strip() not in CLAIM_RELEASED


def task_points_at_pr(pr_field: str | None, pr_number: int) -> bool:
    n = extract_pr_number(pr_field)
    return n is not None and n == pr_number


def validate_index_freshness(tasks_dir: Path) -> GateResult:
    index_path = tasks_dir / INDEX_NAME
    expected = rebuild_task_index(tasks_dir)
    if not index_path.is_file():
        return GateResult(False, (MSG_TIP_INDEX,))
    try:
        actual = _read_text(index_path)
    except (OSError, UnicodeDecodeError):
        return GateResult(False, (MSG_TIP_INDEX,))
    if actual != expected:
        return GateResult(False, (MSG_TIP_INDEX,))
    return GateResult(True)


def validate_pr_linked_tasks(tasks_dir: Path, pr_number: int) -> GateResult:
    errors: list[str] = []
    linked: list[str] = []
    for path in sorted(tasks_dir.glob("T-*.md")):
        try:
            text = _read_text(path)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(MSG_TIP_UNREADABLE.format(name=path.name, detail=exc))
            continue
        fields = parse_task_fields(text)
        pr_raw = _header_field(fields, "pr")
        if not task_points_at_pr(pr_raw, pr_number):
            continue
        linked.append(path.name)
        st = extract_status(text)
        if st not in TIP_OK_STATUSES:
            errors.append(MSG_TIP_STATUS.format(name=path.name, pr=pr_number, st=st))
        claim = _header_field(fields, "claim")
        if claim_is_held(claim):
            errors.append(MSG_TIP_CLAIM.format(name=path.name, pr=pr_number, claim=claim))
        parent = _header_field(fields, "родитель")
        if parent == PLACEHOLDER_PARENT:
            errors.append(
                MSG_TIP_PARENT.format(name=path.name, pr=pr_number, parent=parent)
            )
    # any() so append(None) / empty-name mutants still trip NO_LINKED.
    if not any(linked):
        errors.append(MSG_TIP_NO_LINKED.format(pr=pr_number))
    return GateResult(ok=not errors, errors=tuple(errors))


def validate_tip_hygiene(
    tasks_dir: Path,
    *,
    pr: int | str | None = None,
    env: Mapping[str, str] | None = None,
    check_index: bool = True,
) -> GateResult:
    errors: list[str] = []
    if check_index:
        idx = validate_index_freshness(tasks_dir)
        if not idx.ok:
            errors.extend(idx.errors)
    resolution = resolve_pr(explicit=pr, env=env)
    if resolution.errors:
        errors.extend(resolution.errors)
    if resolution.pr_number is not None:
        linked = validate_pr_linked_tasks(tasks_dir, resolution.pr_number)
        if not linked.ok:
            errors.extend(linked.errors)
    return GateResult(ok=not errors, errors=tuple(errors))


def apply_ready(
    text: str,
    *,
    review_note: str,
    pr: str | None = None,
) -> str:
    """Flip in-progress → self-review. self-review is a pure no-op (same text)."""
    st = extract_status(text)
    if st == READY_NOOP_STATUS:
        return text
    if st != READY_FROM:
        raise ValueError(MSG_READY_STATUS.format(st=st))
    note = (review_note or "").strip()
    if not note or note.startswith("_"):
        raise ValueError(MSG_READY_NOTE)
    out = set_field(text, "статус", READY_NOOP_STATUS)
    out = set_field(out, "claim", CLAIM_EMPTY)
    out = set_field(out, "review_note", note)
    if pr is not None and str(pr).strip():
        out = set_field(out, "pr", str(pr).strip())
    out = append_status_progress(out, READY_NOOP_STATUS)
    out = append_progress(out, READY_PROGRESS)
    return out


def write_ready(
    tasks_dir: Path,
    task_id: str,
    *,
    review_note: str,
    pr: str | None = None,
) -> tuple[Path, bool]:
    """Apply ready. Returns (path, changed). Idempotent: self-review → no writes."""
    path = tasks_dir / f"{task_id}.md"
    if not path.is_file():
        raise FileNotFoundError(MSG_READY_MISSING.format(task_id=task_id))
    try:
        original = _read_text(path)
    except UnicodeDecodeError as exc:
        raise ValueError(MSG_TIP_UNREADABLE.format(name=path.name, detail=exc)) from exc
    except OSError as exc:
        raise ValueError(MSG_TIP_UNREADABLE.format(name=path.name, detail=exc)) from exc
    updated = apply_ready(original, review_note=review_note, pr=pr)
    if updated == original:
        return path, False
    _write_text(path, updated)
    _write_text(tasks_dir / INDEX_NAME, rebuild_task_index(tasks_dir))
    return path, True
