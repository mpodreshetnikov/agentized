"""Orbit-tasks → Agentized import (AGE-46 / #26b)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .task_schema import (
    PLACEHOLDER_EMPTY,
    PLACEHOLDER_TAGS,
    TASK_ID_RE,
    format_id_list,
    list_tasks,
    map_orbit_status,
    parse_id_list,
    rebuild_task_index,
    validate_kind_priority,
)
from .tasks import render_task_file

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
SAFE_TASK_ID_RE = re.compile(r"^T-[0-9A-Za-z-]+$")
MSG_NO_STATUS = "missing or empty Orbit status (refusing silent idea)"
MSG_NO_FM = "no front matter / id"
MSG_NO_VALUE = "missing Orbit value/Ценность (refusing placeholder)"
MSG_EXISTS_ORBIT = "exists, no overwrite (orbit_id {oid})"
MSG_UNRESOLVED = (
    "unresolved id {raw!r} (depends_on/superseded_by; not imported, e.g. closed in Orbit)"
)
# Orbit states Agentized cannot start a new task in: imported as open, original kept in body.
ORBIT_AS_OPEN = frozenset({"review", "in-review", "blocked"})
ORBIT_CLOSED = frozenset({"done", "canceled"})
MSG_BAD_ID = "id {raw!r} must be T-* (convert Orbit T-NNNN) or Agentized T-YYMMDD-xxxx"


@dataclass
class OrbitTaskDraft:
    source: Path
    task_id: str
    title: str
    status: str
    kind: str = ""
    priority: str = ""
    owner: str = ""
    tags: str = ""
    depends_on: list[str] = field(default_factory=list)
    blocked_by: str = ""
    blocked_reason: str = ""
    blocked_deadline: str = ""
    exit: str = ""
    review_note: str = ""
    pr: str = ""
    orbit_id: str = ""
    superseded_by: str = ""
    orbit_status: str = ""
    value: str = ""
    body: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class ImportReport:
    dry_run: bool
    sources: list[str]
    would_write: list[str]
    skipped: list[str]
    warnings: list[str]
    errors: list[str]
    drafts: list[OrbitTaskDraft] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "sources": list(self.sources),
            "would_write": list(self.would_write),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "count": len(self.drafts),
            "closed_in_orbit": len(self.closed),
        }


def _skip(report: ImportReport, path: Path, msg: str) -> None:
    report.skipped.append(str(path))
    report.warnings.append(msg)


def _fail(report: ImportReport, path: Path, msg: str) -> None:
    _skip(report, path, msg)
    report.errors.append(msg)


def _strip_quotes(value: str) -> str:
    if len(value) < 2:
        return value
    opener = value[0]
    if opener in "'\"" and value[-1] == opener:
        return value[1:-1]
    return value


def _parse_scalar(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(part.strip()) for part in inner.split(",")]
    if text[0] in "'\"" and text[-1] == text[0]:
        return text[1:-1]
    return text


def parse_yaml_front_matter(text: str) -> tuple[dict[str, Any], str] | None:
    match = FM_RE.match(text)
    if not match:
        return None
    meta: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        km = KEY_RE.match(line)
        if not km:
            continue
        meta[km.group(1)] = _parse_scalar(km.group(2))
    return meta, match.group(2)


_SHORT_ID = re.compile(r"^(T-\d{4})(?:-|$)")
_LONG_ID = re.compile(r"^(T-\d{6}-[a-z0-9]+)(?:-|$)")


def _id_from_filename(stem: str) -> str:
    """T-0023-slug → T-0023; T-260829-304-slug → T-260829-304."""
    short = _SHORT_ID.match(stem)
    if short:
        return short.group(1)
    long = _LONG_ID.match(stem)
    if long:
        return long.group(1)
    return stem


def _meta_str(meta: dict[str, Any], key: str) -> str:
    return str(meta.get(key) or "")


def is_safe_task_id(task_id: str) -> bool:
    return bool(task_id) and bool(SAFE_TASK_ID_RE.match(task_id))


def resolve_dest_path(dest_tasks: Path, task_id: str) -> Path | None:
    if not is_safe_task_id(task_id):
        return None
    base = dest_tasks.resolve()
    dest = (dest_tasks / f"{task_id}.md").resolve()
    try:
        dest.relative_to(base)
    except ValueError:
        return None
    return dest


def existing_orbit_id_map(dest_tasks: Path) -> dict[str, str]:
    """Map orbit_id → Agentized task_id for tasks already on disk."""
    out: dict[str, str] = {}
    if not dest_tasks.is_dir():
        return out
    for meta in list_tasks(dest_tasks):
        oid = (meta.orbit_id or "").strip()
        if oid and not oid.startswith("_"):
            out[oid] = meta.task_id
    return out


def find_dest_by_orbit_id(dest_tasks: Path, orbit_id: str) -> Path | None:
    tid = existing_orbit_id_map(dest_tasks).get(orbit_id)
    if not tid:
        return None
    path = dest_tasks / f"{tid}.md"
    return path if path.exists() else None


def draft_from_orbit_file(path: Path) -> OrbitTaskDraft | None:
    text = path.read_text(encoding="utf-8")
    parsed = parse_yaml_front_matter(text)
    if not parsed:
        return None
    meta, body = parsed
    raw_id = meta.get("id")
    task_id = "" if raw_id is None else str(raw_id).strip()
    if not task_id and path.stem.startswith("T-"):
        task_id = _id_from_filename(path.stem)
    raw_title = meta.get("title")
    title = task_id if raw_title is None else (str(raw_title).strip() or task_id)
    warnings: list[str] = []
    error = ""
    orbit_status = ""
    if "status" not in meta:
        status = ""
        error = MSG_NO_STATUS
    else:
        raw_status = meta["status"]
        cleaned = "" if raw_status is None else str(raw_status).strip()
        if not cleaned:
            status = ""
            error = MSG_NO_STATUS
        else:
            key = cleaned.lower()
            mapped = "open" if key in ORBIT_AS_OPEN else map_orbit_status(cleaned)
            if mapped in ORBIT_CLOSED and key not in ORBIT_CLOSED:
                mapped = None
            if mapped is None:
                status = ""
                error = f"unknown Orbit status {cleaned!r}"
            else:
                status = mapped
                if key in ORBIT_AS_OPEN:
                    orbit_status = cleaned
                    warnings.append(f"{task_id}: Orbit status {cleaned} → open (kept in body)")
    tags_val = meta.get("tags") or []
    if isinstance(tags_val, list):
        tags = ", ".join(str(t) for t in tags_val)
    else:
        tags = str(tags_val)
    deps = meta.get("depends_on") or []
    if isinstance(deps, str):
        deps = parse_id_list(deps)
    if not isinstance(deps, list):
        deps = []
    deps = [str(d) for d in deps]
    blocked_by = _meta_str(meta, "blocked_by")
    value = _meta_str(meta, "value") or _meta_str(meta, "Ценность")
    return OrbitTaskDraft(
        source=path,
        task_id=task_id,
        title=title,
        status=status,
        kind=_meta_str(meta, "kind"),
        priority=_meta_str(meta, "priority"),
        owner=_meta_str(meta, "owner"),
        tags=tags,
        depends_on=deps,
        blocked_by=blocked_by,
        blocked_reason=_meta_str(meta, "blocked_reason") or blocked_by,
        blocked_deadline=_meta_str(meta, "blocked_deadline"),
        exit=_meta_str(meta, "exit"),
        review_note=_meta_str(meta, "review_note"),
        pr=_meta_str(meta, "pr"),
        orbit_id=_meta_str(meta, "orbit_id"),
        superseded_by=_meta_str(meta, "superseded_by"),
        orbit_status=orbit_status,
        value=value,
        body=body,
        warnings=warnings,
        error=error,
    )


def _stable_task_id(dest_tasks: Path, orbit_id: str, reserved: set[str]) -> str:
    """Deterministic Agentized id from orbit_id so dry-run ids == write ids."""
    from .task_schema import utc_now_stamp

    day_s = utc_now_stamp()
    digest = hashlib.sha256(orbit_id.encode()).hexdigest()
    for i in range(16):
        suffix = digest[i * 4 : i * 4 + 4]
        candidate = f"T-{day_s}-{suffix}"
        if candidate in reserved or (dest_tasks / f"{candidate}.md").exists():
            continue
        return candidate
    raise RuntimeError(f"no free stable id for orbit_id {orbit_id!r}")


def agentized_markdown(draft: OrbitTaskDraft) -> str:
    header = render_task_file(
        draft.task_id,
        draft.title,
        status=draft.status,
        tags=draft.tags or PLACEHOLDER_TAGS,
        parent=PLACEHOLDER_EMPTY,
        claim=PLACEHOLDER_EMPTY,
        kind=draft.kind,
        priority=draft.priority,
        owner=draft.owner,
        depends_on=draft.depends_on,
        blocked_by=draft.blocked_by,
        blocked_reason=draft.blocked_reason,
        blocked_deadline=draft.blocked_deadline,
        exit=draft.exit,
        review_note=draft.review_note,
        pr=draft.pr,
        orbit_id=draft.orbit_id,
        superseded_by=draft.superseded_by,
        goal="Imported from orbit-tasks fixture (see preserved body below).",
        value=draft.value,
    )
    preserved = draft.body.strip()
    kept = f"Orbit status: {draft.orbit_status}\n\n" if draft.orbit_status else ""
    history = (
        "\n## Imported body (preserved ids / history links)\n\n"
        f"_source: `{draft.source.name}`_\n\n"
        f"{kept}{preserved}\n"
    )
    return header.rstrip() + "\n" + history


def collect_orbit_task_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(source.rglob("T-*.md"))


def list_non_orbit_markdown(source: Path) -> list[Path]:
    """``.md`` files under a directory source that are not matched as ``T-*.md``."""
    if not source.is_dir():
        return []
    orbit = set(collect_orbit_task_files(source))
    return sorted(path for path in source.rglob("*.md") if path not in orbit)


def _remap_id(raw: str, id_map: dict[str, str]) -> str | None:
    if raw in id_map:
        return id_map[raw]
    if TASK_ID_RE.match(raw) and raw in id_map.values():
        return raw
    return None


def _remap_draft_refs(draft: OrbitTaskDraft, id_map: dict[str, str]) -> list[str]:
    errs: list[str] = []
    new_deps: list[str] = []
    for dep in draft.depends_on:
        mapped = _remap_id(dep, id_map)
        if mapped is None:
            errs.append(MSG_UNRESOLVED.format(raw=dep))
        else:
            new_deps.append(mapped)
    draft.depends_on = new_deps
    if draft.superseded_by:
        mapped = _remap_id(draft.superseded_by, id_map)
        if mapped is None:
            errs.append(MSG_UNRESOLVED.format(raw=draft.superseded_by))
        else:
            draft.superseded_by = mapped
    return errs


def import_orbit_tasks(
    source: Path,
    dest_tasks: Path,
    *,
    dry_run: bool = True,
) -> ImportReport:
    report = ImportReport(
        dry_run=dry_run,
        sources=[],
        would_write=[],
        skipped=[],
        warnings=[],
        errors=[],
    )
    seen_ids: set[str] = set()
    reserved: set[str] = set()
    pending: list[tuple[OrbitTaskDraft, Path]] = []
    this_run_map: dict[str, str] = {}  # orbit/source id → agentized id

    for path in list_non_orbit_markdown(source):
        report.warnings.append(f"skip non-Orbit markdown (not T-*.md): {path}")

    for path in collect_orbit_task_files(source):
        report.sources.append(str(path))
        try:
            draft = draft_from_orbit_file(path)
        except (UnicodeDecodeError, OSError) as exc:
            _fail(report, path, f"skip (read error): {path}: {exc}")
            continue
        if not draft or not draft.task_id:
            _fail(report, path, f"skip ({MSG_NO_FM}): {path}")
            continue
        if draft.error:
            _fail(report, path, f"skip ({draft.error}): {path}")
            continue
        if draft.status in ORBIT_CLOSED:
            report.closed.append(draft.task_id)
            continue
        if not draft.task_id.startswith("T-"):
            _fail(report, path, f"skip ({MSG_BAD_ID.format(raw=draft.task_id)}): {path}")
            continue
        if not is_safe_task_id(draft.task_id):
            _fail(report, path, f"skip (unsafe id {draft.task_id!r}): {path}")
            continue
        kp = validate_kind_priority(str(draft.kind), str(draft.priority))
        if kp:
            _fail(report, path, f"skip ({'; '.join(kp)}): {path}")
            continue

        source_id = draft.task_id
        if not TASK_ID_RE.match(draft.task_id):
            # Orbit-style T-NNNN… → convert to Agentized id (deterministic).
            orbit_id = draft.task_id
            draft.orbit_id = orbit_id
            existing = find_dest_by_orbit_id(dest_tasks, orbit_id)
            if existing is not None:
                _skip(
                    report,
                    path,
                    f"skip ({MSG_EXISTS_ORBIT.format(oid=orbit_id)}): {existing}",
                )
                continue
            draft.task_id = _stable_task_id(dest_tasks, orbit_id, reserved)
            reserved.add(draft.task_id)
            report.warnings.append(f"{orbit_id}: converted → {draft.task_id} (orbit_id preserved)")
            this_run_map[orbit_id] = draft.task_id
        else:
            this_run_map[source_id] = draft.task_id
            if draft.orbit_id:
                this_run_map[draft.orbit_id] = draft.task_id

        if not draft.value:
            _fail(report, path, f"skip ({MSG_NO_VALUE}): {path}")
            continue

        dest = resolve_dest_path(dest_tasks, draft.task_id)
        if dest is None:
            _fail(report, path, f"skip (path escape {draft.task_id!r}): {path}")
            continue
        if draft.task_id in seen_ids:
            _fail(report, path, f"skip (duplicate id {draft.task_id}): {path}")
            continue
        if dest.exists():
            _skip(report, path, f"skip (exists, no overwrite): {dest}")
            continue
        seen_ids.add(draft.task_id)
        pending.append((draft, dest))
        report.drafts.append(draft)
        report.warnings.extend(draft.warnings)
        report.would_write.append(str(dest))

    if not report.sources:
        report.errors.append("no Orbit task files (T-*.md) found under source")
        return report

    # Remap depends_on / superseded_by using this-run + existing orbit_id map.
    id_map = {**existing_orbit_id_map(dest_tasks), **this_run_map}
    for tid in this_run_map.values():
        id_map[tid] = tid
    for draft, _dest in pending:
        for msg in _remap_draft_refs(draft, id_map):
            report.errors.append(f"{draft.task_id}: {msg}")
            report.warnings.append(f"{draft.task_id}: {msg}")

    if report.errors:
        # Validate-all / write-nothing: clear would_write for honesty on failed runs.
        report.would_write = []
        report.drafts = []
        return report

    if dry_run or not pending:
        return report

    dest_tasks.mkdir(parents=True, exist_ok=True)
    for draft, dest in pending:
        dest.write_text(agentized_markdown(draft), encoding="utf-8")
    (dest_tasks / "INDEX.md").write_text(rebuild_task_index(dest_tasks), encoding="utf-8")
    return report


def format_report(report: ImportReport) -> str:
    lines = [
        f"orbit-import {'DRY-RUN' if report.dry_run else 'WRITE'}",
        f"  sources: {len(report.sources)}",
        f"  would_write: {len(report.would_write)}",
        f"  skipped: {len(report.skipped)}",
        f"  errors: {len(report.errors)}",
    ]
    if report.closed:
        lines.append(f"  skipped: closed in Orbit ({len(report.closed)})")
    for path in report.would_write:
        lines.append(f"  + {path}")
    for w in report.warnings:
        lines.append(f"  WARN: {w}")
    for e in report.errors:
        lines.append(f"  ERR: {e}")
    for s in report.skipped:
        lines.append(f"  skip: {s}")
    for d in report.drafts:
        if d.depends_on:
            lines.append(f"  depends_on {d.task_id}: {format_id_list(d.depends_on)}")
    return "\n".join(lines) + "\n"
