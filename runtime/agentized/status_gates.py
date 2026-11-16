"""Hard status-transition gates for context/tasks/*.md (AGE-22).

Invalid transitions / missing fields → blocking failure.

Canonical status owner for Agentized (board AGE-37/#30, autopilot, INDEX).
Import ``CANONICAL_STATUSES``, ``STATUS_ALIASES``, ``COLUMN_FOR_STATUS``,
``normalize_status`` from here — #30 stub must match; rebase keeps them identical.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

TEXT_ENCODING = "utf-8"

# Canonical statuses — owned by AGE-22; board/CLI/INDEX consume these.
CANONICAL_STATUSES: tuple[str, ...] = (
    "idea",
    "open",
    "queue",
    "in-progress",
    "self-review",
    "for-review",
    "blocked",
    "done",
    "canceled",
)

# Legacy aliases accepted in files / CLI.
STATUS_ALIASES: dict[str, str] = {
    "dropped": "canceled",
    "queued": "queue",
}

ALL_STATUSES: tuple[str, ...] = CANONICAL_STATUSES + ("dropped", "queued")

# INDEX / claim active lanes (not board columns).
INDEX_ACTIVE_STATUSES: tuple[str, ...] = (
    "open",
    "queue",
    "in-progress",
    "self-review",
    "for-review",
    "blocked",
)

# Board columns (AGE-37): self-review sits in Queue (Maxim); idea/open → Open.
COLUMN_FOR_STATUS: dict[str, str] = {
    "idea": "open",
    "open": "open",
    "queue": "queue",
    "self-review": "queue",
    "in-progress": "in-progress",
    "for-review": "for-review",
    "blocked": "blocked",
    "done": "done",
    "canceled": "canceled",
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

VALUE_LINE_RE = re.compile(r"(?im)^\s*Ценность:\s*\S+")
FIELD_LINE_RE = re.compile(
    r"^(статус|теги|родитель|claim|blocked_reason|blocked_deadline|"
    r"review_note|acceptance_note|pr):[ \t]*(.*)$",
    re.MULTILINE,
)
DEADLINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Real PR ref only — not arbitrary URLs or the word "merged".
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


@dataclass(frozen=True)
class GateResult:
    ok: bool
    errors: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if self.ok:
            return ""
        return "; ".join(self.errors)


def normalize_status(raw: str | None) -> str:
    """Normalize a status token. Empty input stays empty (gates refuse it)."""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    return STATUS_ALIASES.get(s, s)


def is_known_status(raw: str | None) -> bool:
    st = normalize_status(raw)
    return bool(st) and st in CANONICAL_STATUSES


def parse_task_fields(text: str | None) -> dict[str, str]:
    if text is None:
        return {}
    return {k: v.strip() for k, v in FIELD_LINE_RE.findall(text)}


def extract_status(text: str | None) -> str:
    """Return normalized status, or ``\"\"`` when missing/empty (caller must refuse)."""
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
    m = VALUE_LINE_RE.search(text)
    if not m:
        return False
    val = m.group(0).split(":", 1)[-1].strip()
    return bool(val) and not val.startswith("_")


def _nonempty_field(fields: dict[str, str], *keys: str) -> str:
    for key in keys:
        val = (fields.get(key) or "").strip()
        if val and not val.startswith("_"):
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


def _has_acceptance_evidence(fields: dict[str, str]) -> bool:
    return bool(_nonempty_field(fields, "acceptance_note"))


def validate_status_requirements(text: str, *, status: str | None = None) -> GateResult:
    """Validate required fields for the *current* status in ``text``."""
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
    if pr_raw and not is_real_pr_ref(pr_raw):
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

    if st == "done":
        if not _has_acceptance_evidence(fields):
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
    require_value: bool = True,
    check_transition: bool = True,
) -> GateResult:
    """Full gate: known status + optional transition + status requirements + value line."""
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

    if require_value and not has_value_line(text):
        errors.append(MSG_MISSING_VALUE)

    return GateResult(ok=not errors, errors=tuple(errors))


def validate_task_file(
    path: Path,
    *,
    old_text: str | None = None,
    require_value: bool = True,
) -> GateResult:
    if not path.exists():
        return GateResult(False, (MSG_MISSING_FILE.format(path=path),))
    text = path.read_bytes().decode(TEXT_ENCODING)
    if old_text is None:
        # old_status defaults to None → transition check skipped
        return validate_task_text(text, require_value=require_value)
    return validate_task_text(
        text,
        old_status=extract_status(old_text),
        require_value=require_value,
    )


def default_repo_root_for_tasks(tasks_dir: Path) -> Path:
    """``…/context/tasks`` → repo root; shallow paths stay as resolved dir."""
    resolved = tasks_dir.resolve()
    parents = resolved.parents
    if len(parents) < 2:
        return resolved
    return parents[1]


def _git_missing_path(stderr: str) -> bool:
    """True when the path is absent at ref (omit), not for other git failures."""
    low = stderr.lower()
    return (
        "does not exist" in low
        or "exists on disk, but not in" in low
        or "path not in" in low
    )


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
    """Map ``T-*.md`` basename → blob text at ``ref``.

    Missing paths at ``ref`` are omitted (new files). Any other git/OS failure
    raises ``RuntimeError`` (fail-closed).
    """
    root = default_repo_root_for_tasks(tasks_dir) if repo_root is None else repo_root
    base = resolve_validate_base_ref(root, explicit=ref)
    out: dict[str, str] = {}
    for path in sorted(tasks_dir.glob("T-*.md")):
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise _git_err(path.name, base, str(exc)) from exc
        try:
            proc = _run_git(root, ["show", f"{base}:{rel}"])
        except OSError as exc:
            raise _git_err(rel, base, str(exc)) from exc
        if proc.returncode != 0:
            err = proc.stderr or proc.stdout or f"exit {proc.returncode}"
            if _git_missing_path(err):
                continue
            raise _git_err(rel, base, err.strip())
        out[path.name] = proc.stdout
    return out


def resolve_validate_base_ref(repo_root: Path, *, explicit: str | None = None) -> str:
    """PR-base ref for transition checks — never the PR branch HEAD alone.

    Order: explicit arg → MUTATION_BASE → TASKS_VALIDATE_BASE →
    ``git merge-base origin/main HEAD`` → ``origin/main``.
    """
    if explicit:
        return explicit
    env = (os.environ.get("MUTATION_BASE") or os.environ.get("TASKS_VALIDATE_BASE") or "").strip()
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


def rebuild_task_index_active(tasks_dir: Path) -> str:
    """INDEX with AGE-22 active lanes (queue / self-review / for-review)."""
    from .tasks import list_tasks

    tasks = list_tasks(tasks_dir)
    buckets: dict[str, list[str]] = {s: [] for s in INDEX_ACTIVE_STATUSES}
    for t in tasks:
        st = normalize_status(t.status)
        if st not in buckets:
            continue
        parent = (
            f" (родитель: {t.parent})"
            if t.parent and not t.parent.startswith("_")
            else ""
        )
        claim = (
            f" · claim: {t.claim}"
            if t.claim and not t.claim.startswith("_")
            else ""
        )
        buckets[st].append(
            f"- [{t.task_id}]({t.path.name}) — {t.title}{parent}{claim}"
        )

    def section(name: str) -> str:
        rows = buckets[name]
        body = "\n".join(rows) if rows else "_(пусто)_"
        return f"## {name}\n\n{body}\n"

    sections = "\n".join(section(name) for name in INDEX_ACTIVE_STATUSES)
    status_list = " · ".join(f"`{s}`" for s in INDEX_ACTIVE_STATUSES)
    return (
        "# Задачи — живой индекс\n\n"
        "Генерируемый список **активной** работы. Не полный архив истории.\n\n"
        f"Статусы в индексе: {status_list}.\n\n"
        "Поиск: этот индекс + grep по id / title / tags. Не обходи весь каталог `tasks/`.\n\n"
        f"{sections}\n"
        "Новые задачи — по [`TEMPLATE.md`](TEMPLATE.md). Файлы задач лежат рядом с этим индексом; "
        "при смене статуса файл **не перемещается**.\n"
    )


def validate_tasks_dir(
    tasks_dir: Path,
    *,
    require_value: bool = True,
    skip_stems: frozenset[str] | None = None,
    previous_by_name: dict[str, str] | None = None,
) -> GateResult:
    """Validate every T-*.md under tasks_dir.

    When ``previous_by_name`` is provided (basename → prior text), transitions are
    checked against that prior status. Omit the map for a pure snapshot check
    (fields/Ценность only). CLI / CI / pre-commit pass git PR-base blobs.
    """
    skip = skip_stems or frozenset()
    errors: list[str] = []
    for path in sorted(tasks_dir.glob("T-*.md")):
        if path.stem in skip:
            continue
        text = path.read_bytes().decode(TEXT_ENCODING)
        old_status = None
        if previous_by_name is not None:
            if path.name in previous_by_name:
                old_status = extract_status(previous_by_name[path.name])
                if not old_status:
                    errors.append(f"{path.name}: {MSG_MISSING_STATUS} (previous)")
                    continue
            else:
                st = extract_status(text)
                # Block forging done/review on a brand-new path (claim→in-progress OK).
                if st in {"done", "canceled", "self-review", "for-review"}:
                    errors.append(
                        f"{path.name}: new task cannot start as {st}"
                    )
                    continue
        result = validate_task_text(
            text,
            old_status=old_status,
            require_value=require_value,
        )
        if not result.ok:
            for err in result.errors:
                errors.append(f"{path.name}: {err}")
    return GateResult(ok=not errors, errors=tuple(errors))
