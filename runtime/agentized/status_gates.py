"""Hard status-transition gates for context/tasks (AGE-22 / AGE-49)."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .tasks import (
    ALL_STATUSES,
    CANONICAL_STATUSES,
    FIELD_RE,
    STATUS_ALIASES,
)

TEXT_ENCODING = "utf-8"
INDEX_ACTIVE_STATUSES: tuple[str, ...] = (
    "open", "queue", "in-progress", "self-review", "for-review", "blocked",
)
COLUMN_FOR_STATUS: dict[str, str] = {
    "idea": "open", "open": "open", "queue": "queue", "self-review": "queue",
    "in-progress": "in-progress", "for-review": "for-review", "blocked": "blocked",
    "done": "done", "canceled": "canceled",
}
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "idea": frozenset({"open", "queue", "canceled"}),
    "open": frozenset({"queue", "in-progress", "blocked", "canceled"}),
    "queue": frozenset({"open", "in-progress", "blocked", "canceled"}),
    "in-progress": frozenset(
        {"self-review", "for-review", "blocked", "done", "open", "queue", "canceled"}
    ),
    "self-review": frozenset({"for-review", "in-progress", "done", "blocked", "canceled"}),
    "for-review": frozenset({"done", "in-progress", "self-review", "blocked", "canceled"}),
    "blocked": frozenset({"in-progress", "open", "queue", "canceled"}),
    "done": frozenset({"open", "queue", "in-progress"}),
    "canceled": frozenset({"open", "queue"}),
}
VALUE_LINE_RE = re.compile(r"^\s*Ценность:\s*(\S.*)$")
VALUE_KEY_RE = re.compile(r"^\s*Ценность:\s*")
NEW_PATH_ALLOWED_STATUSES: frozenset[str] = frozenset(
    {"idea", "open", "queue", "in-progress"}
)
DEADLINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PR_REF_RE = re.compile(
    r"(?i)^(?:PR\s*#\d+|#\d+|https://github\.com/[^/\s]+/[^/\s]+/pull/\d+(?:[/?#]\S*)?)$"
)
MSG_UNKNOWN_STATUS = "unknown status {st!r}"
MSG_UNKNOWN_OLD = "unknown old status {old!r}"
MSG_UNKNOWN_NEW = "unknown new status {new!r}"
MSG_MISSING_STATUS = "missing or empty статус"
MSG_BLOCKED_REASON = "blocked requires blocked_reason"
MSG_BLOCKED_DEADLINE = "blocked requires blocked_deadline (YYYY-MM-DD)"
MSG_BLOCKED_DEADLINE_FMT = "blocked_deadline must be YYYY-MM-DD, got {deadline!r}"
MSG_BLOCKED_DEADLINE_INVALID = "blocked_deadline is not a valid date: {deadline!r}"
MSG_REVIEW_EVIDENCE = "{st} requires review_note or pr (real PR ref)"
MSG_DONE_EVIDENCE = "done requires acceptance_note"
MSG_BAD_PR = "pr must be a real PR ref (#N, PR #N, or github.com/.../pull/N), got {pr!r}"
MSG_MISSING_VALUE = 'missing value line "Ценность: …"'
MSG_MISSING_FILE = "missing task file {path}"
MSG_ILLEGAL = "illegal transition {old} → {new}; allowed: {allowed}"
MSG_GIT_ERROR = "git error reading {rel} at {ref}: {detail}"
MSG_UNREADABLE = "unreadable task file: {detail}"
MSG_DUPLICATE_FIELD = "duplicate field {key!r}"
MSG_TASK_DELETED = "task deleted; set статус: canceled"
MSG_NEW_PATH = "new task cannot start as {st}"


@dataclass(frozen=True)
class GateResult:
    ok: bool
    errors: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        return "" if self.ok else "; ".join(self.errors)


def normalize_status(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    return STATUS_ALIASES.get(s, s)


def is_known_status(raw: str | None) -> bool:
    if raw is None:
        return False
    s = raw.strip().lower()
    return s in ALL_STATUSES


def header_block(text: str) -> str:
    if text.startswith("##"):
        return ""
    idx = text.find("\n##")
    if idx == -1:
        return text
    return text[:idx]


def duplicate_field_errors(text: str | None) -> tuple[str, ...]:
    if not text:
        return ()
    seen: set[str] = set()
    errors: list[str] = []
    value_hits = 0
    for line in header_block(text).splitlines():
        m = FIELD_RE.match(line)
        if m:
            key = m.group(1)
            if key in seen:
                errors.append(MSG_DUPLICATE_FIELD.format(key=key))
            else:
                seen.add(key)
        if VALUE_KEY_RE.match(line):
            value_hits += 1
    if value_hits > 1:
        errors.append(MSG_DUPLICATE_FIELD.format(key="Ценность"))
    return tuple(errors)


def parse_task_fields(text: str | None) -> dict[str, str]:
    """Parse known keys from the header block only (last key wins within header)."""
    if text is None:
        return {}
    out: dict[str, str] = {}
    for line in header_block(text).splitlines():
        m = FIELD_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def extract_status(text: str | None) -> str:
    fields = parse_task_fields(text)
    raw = fields.get("статус")
    if raw is None:
        return ""
    stripped = str(raw).strip()
    if not stripped:
        return ""
    return normalize_status(stripped)


def has_value_line(text: str | None) -> bool:
    if text is None:
        return False
    for line in header_block(text).splitlines():
        m = VALUE_LINE_RE.match(line)
        if not m:
            continue
        val = m.group(1).strip()
        return bool(val) and (not val.startswith("_"))
    return False


def _nonempty_field(fields: dict[str, str], *keys: str) -> str:
    for key in keys:
        val = (fields.get(key) or "").strip()
        if val and (not val.startswith("_")):
            return val
    return ""


def is_real_pr_ref(value: str | None) -> bool:
    if value is None:
        return False
    return PR_REF_RE.match(value.strip()) is not None


def _has_review_evidence(fields: dict[str, str]) -> bool:
    if _nonempty_field(fields, "review_note"):
        return True
    pr = _nonempty_field(fields, "pr")
    return bool(pr) and is_real_pr_ref(pr)


def _new_path_status_ok(text: str, st: str) -> bool:
    if st in NEW_PATH_ALLOWED_STATUSES:
        return True
    if st != "self-review":
        return False
    fields = parse_task_fields(text)
    pr, note = _nonempty_field(fields, "pr"), _nonempty_field(fields, "review_note")
    return bool(note) and bool(pr) and is_real_pr_ref(pr)


def validate_status_requirements(text: str, *, status: str | None = None) -> GateResult:
    dups = duplicate_field_errors(text)
    if dups:
        return GateResult(False, dups)
    fields = parse_task_fields(text)
    if status is not None:
        st = normalize_status(status)
    else:
        st = extract_status(text)
    errors: list[str] = []
    if not st:
        return GateResult(False, (MSG_MISSING_STATUS,))
    if st not in CANONICAL_STATUSES:
        errors.append(MSG_UNKNOWN_STATUS.format(st=st))
        return GateResult(False, tuple(errors))
    pr_raw = _nonempty_field(fields, "pr")
    if pr_raw and (not is_real_pr_ref(pr_raw)):
        errors.append(MSG_BAD_PR.format(pr=pr_raw))
    if st == "blocked":
        reason = _nonempty_field(fields, "blocked_reason")
        deadline = _nonempty_field(fields, "blocked_deadline")
        if not reason:
            errors.append(MSG_BLOCKED_REASON)
        if not deadline:
            errors.append(MSG_BLOCKED_DEADLINE)
        elif not DEADLINE_RE.match(deadline):
            errors.append(MSG_BLOCKED_DEADLINE_FMT.format(deadline=deadline))
        else:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                errors.append(MSG_BLOCKED_DEADLINE_INVALID.format(deadline=deadline))
    if st in {"self-review", "for-review"}:
        if not _has_review_evidence(fields):
            errors.append(MSG_REVIEW_EVIDENCE.format(st=st))
    if st == "done" and not _nonempty_field(fields, "acceptance_note"):
        errors.append(MSG_DONE_EVIDENCE)
    return GateResult(ok=not errors, errors=tuple(errors))


def validate_transition(old_status: str | None, new_status: str | None) -> GateResult:
    old = normalize_status(old_status)
    new = normalize_status(new_status)
    if not old:
        return GateResult(False, (MSG_MISSING_STATUS,))
    if not new:
        return GateResult(False, (MSG_MISSING_STATUS,))
    if old not in CANONICAL_STATUSES:
        return GateResult(False, (MSG_UNKNOWN_OLD.format(old=old),))
    if new not in CANONICAL_STATUSES:
        return GateResult(False, (MSG_UNKNOWN_NEW.format(new=new),))
    if old == new:
        return GateResult(True)
    allowed = ALLOWED_TRANSITIONS[old]
    if new not in allowed:
        return GateResult(
            False,
            (MSG_ILLEGAL.format(old=old, new=new, allowed=sorted(allowed)),),
        )
    return GateResult(True)


def validate_task_text(
    text: str,
    *,
    old_status: str | None = None,
    check_transition: bool = True,
) -> GateResult:
    errors: list[str] = []
    new_status = extract_status(text)
    if not new_status:
        return GateResult(False, (MSG_MISSING_STATUS,))
    if new_status not in CANONICAL_STATUSES:
        return GateResult(False, (MSG_UNKNOWN_STATUS.format(st=new_status),))
    if check_transition and old_status is not None:
        tr = validate_transition(old_status, new_status)
        if not tr.ok:
            errors.extend(tr.errors)
    req = validate_status_requirements(text)
    if not req.ok:
        errors.extend(req.errors)
    if not has_value_line(text):
        errors.append(MSG_MISSING_VALUE)
    return GateResult(ok=not errors, errors=tuple(errors))


def _read_task_text(path: Path) -> str:
    return path.read_bytes().decode(TEXT_ENCODING)


def validate_task_file(path: Path, *, old_text: str | None = None) -> GateResult:
    if not path.exists():
        return GateResult(False, (MSG_MISSING_FILE.format(path=path),))
    try:
        text = _read_task_text(path)
    except (UnicodeDecodeError, OSError) as exc:
        return GateResult(False, (MSG_UNREADABLE.format(detail=exc),))
    if old_text is None:
        return validate_task_text(text)
    return validate_task_text(text, old_status=extract_status(old_text))


def default_repo_root_for_tasks(tasks_dir: Path) -> Path:
    resolved = tasks_dir.resolve()
    parents = resolved.parents
    if len(parents) < 2:
        return resolved
    return parents[1]


def _git_missing_path(stderr: str) -> bool:
    low = stderr.lower()
    return (
        "does not exist" in low
        or "exists on disk, but not in" in low
        or "path not in" in low
    )


def _cmd_detail(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()


def _git_err(rel: str, ref: str, detail: str) -> RuntimeError:
    return RuntimeError(MSG_GIT_ERROR.format(rel=rel, ref=ref, detail=detail))


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def previous_task_texts_from_git(
    tasks_dir: Path,
    *,
    repo_root: Path | None = None,
    ref: str | None = None,
) -> dict[str, str]:
    root = default_repo_root_for_tasks(tasks_dir) if repo_root is None else repo_root
    base = resolve_validate_base_ref(root, explicit=ref)
    try:
        rel_dir = tasks_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise _git_err(tasks_dir.name, base, str(exc)) from exc
    try:
        listing = _run_git(root, ["ls-tree", "--name-only", f"{base}:{rel_dir}"])
    except OSError as exc:
        raise _git_err(rel_dir, base, str(exc)) from exc
    if listing.returncode != 0:
        err = _cmd_detail(listing)
        if _git_missing_path(err):
            return {}
        raise _git_err(rel_dir, base, err)
    names = [
        n
        for n in listing.stdout.splitlines()
        if n.startswith("T-") and n.endswith(".md")
    ]
    out: dict[str, str] = {}
    for name in names:
        rel = f"{rel_dir}/{name}"
        try:
            proc = _run_git(root, ["show", f"{base}:{rel}"])
        except OSError as exc:
            raise _git_err(rel, base, str(exc)) from exc
        if proc.returncode != 0:
            err = _cmd_detail(proc)
            if _git_missing_path(err):
                continue
            raise _git_err(rel, base, err)
        out[name] = proc.stdout
    return out


def resolve_validate_base_ref(repo_root: Path, *, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = (
        os.environ.get("MUTATION_BASE") or os.environ.get("TASKS_VALIDATE_BASE") or ""
    ).strip()
    if env:
        return env
    try:
        proc = _run_git(repo_root, ["merge-base", "origin/main", "HEAD"])
    except OSError as exc:
        raise RuntimeError(f"git merge-base failed: {exc}") from exc
    if proc.returncode == 0:
        sha = (proc.stdout or "").strip()
        if sha:
            return sha
    return "origin/main"


def validate_tasks_dir(
    tasks_dir: Path,
    *,
    skip_stems: frozenset[str] | None = None,
    previous_by_name: dict[str, str] | None = None,
) -> GateResult:
    skip = skip_stems or frozenset()
    errors: list[str] = []
    paths = sorted(tasks_dir.glob("T-*.md"))
    current = {p.name for p in paths}
    if previous_by_name is not None:
        for name in sorted(previous_by_name):
            if name in current or Path(name).stem in skip:
                continue
            errors.append(f"{name}: {MSG_TASK_DELETED}")
    for path in paths:
        if path.stem in skip:
            continue
        try:
            text = _read_task_text(path)
        except (UnicodeDecodeError, OSError) as exc:
            errors.append(f"{path.name}: {MSG_UNREADABLE.format(detail=exc)}")
            continue
        old_status = None
        if previous_by_name is not None:
            if path.name in previous_by_name:
                old_status = extract_status(previous_by_name[path.name])
                if not old_status:
                    errors.append(f"{path.name}: {MSG_MISSING_STATUS} (previous)")
                    continue
            else:
                st = extract_status(text)
                if st and not _new_path_status_ok(text, st):
                    errors.append(f"{path.name}: {MSG_NEW_PATH.format(st=st)}")
                    continue
        result = validate_task_text(text, old_status=old_status)
        if not result.ok:
            for err in result.errors:
                errors.append(f"{path.name}: {err}")
    return GateResult(ok=not errors, errors=tuple(errors))


def run_tasks_validate(
    tasks_dir: Path, *, repo_root: Path, base_ref: str | None = None
) -> tuple[str, GateResult]:
    ref = resolve_validate_base_ref(repo_root, explicit=base_ref)
    previous = previous_task_texts_from_git(tasks_dir, repo_root=repo_root, ref=ref)
    return (ref, validate_tasks_dir(tasks_dir, previous_by_name=previous))
