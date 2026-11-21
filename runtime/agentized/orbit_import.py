"""Orbit-tasks → Agentized import (AGE-26)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .task_schema import (
    DEFAULT_VALUE,
    TASK_ID_RE,
    allocate_task_id,
    format_id_list,
    map_orbit_status,
    parse_id_list,
    validate_kind_priority,
)
from .tasks import render_task_file

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
SAFE_TASK_ID_RE = re.compile(r"^T-[0-9A-Za-z-]+$")


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "sources": list(self.sources),
            "would_write": list(self.would_write),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "count": len(self.drafts),
        }


def _skip(report: ImportReport, path: Path, msg: str, *, err: bool = True) -> None:
    report.skipped.append(str(path))
    report.warnings.append(msg)
    if err is not False:
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
    if "status" not in meta:
        status = "idea"
    else:
        raw_status = meta["status"]
        cleaned = "" if raw_status is None else str(raw_status).strip()
        if not cleaned:
            status = "idea"
        else:
            mapped = map_orbit_status(cleaned)
            if mapped is None:
                status = ""
                error = f"unknown Orbit status {cleaned!r}"
            else:
                status = mapped
                if cleaned.lower() == "review":
                    warnings.append(f"{task_id}: Orbit status review → for-review (human)")
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
        superseded_by=_meta_str(meta, "superseded_by"),
        body=body,
        warnings=warnings,
        error=error,
    )


def agentized_markdown(draft: OrbitTaskDraft) -> str:
    acceptance = draft.exit if draft.status == "done" else ""
    header = render_task_file(
        draft.task_id,
        draft.title,
        status=draft.status,
        tags=draft.tags,
        kind=draft.kind,
        priority=draft.priority,
        owner=draft.owner,
        depends_on=draft.depends_on,
        blocked_by=draft.blocked_by,
        blocked_reason=draft.blocked_reason,
        blocked_deadline=draft.blocked_deadline,
        exit=draft.exit,
        acceptance_note=acceptance,
        review_note=draft.review_note,
        pr=draft.pr,
        orbit_id=draft.orbit_id,
        superseded_by=draft.superseded_by,
        goal="Imported from orbit-tasks fixture (see preserved body below).",
        value=DEFAULT_VALUE,
    )
    preserved = draft.body.strip()
    history = (
        "\n## Imported body (preserved ids / history links)\n\n"
        f"_source: `{draft.source.name}`_\n\n"
        f"{preserved}\n"
    )
    return header.rstrip() + "\n" + history


def collect_orbit_task_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(source.rglob("T-*.md"))


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
    for path in collect_orbit_task_files(source):
        report.sources.append(str(path))
        try:
            draft = draft_from_orbit_file(path)
        except (UnicodeDecodeError, OSError) as exc:
            _skip(report, path, f"skip (read error): {path}: {exc}")
            continue
        if not draft or not draft.task_id:
            _skip(report, path, f"skip (no front matter / id): {path}", err=False)
            continue
        if draft.error:
            _skip(report, path, f"skip ({draft.error}): {path}")
            continue
        if not is_safe_task_id(draft.task_id):
            _skip(report, path, f"skip (unsafe id {draft.task_id!r}): {path}")
            continue
        kp = validate_kind_priority(str(draft.kind), str(draft.priority))
        if kp:
            _skip(report, path, f"skip ({'; '.join(kp)}): {path}")
            continue
        if not TASK_ID_RE.match(draft.task_id):
            orbit_id = draft.task_id
            draft.orbit_id = orbit_id
            draft.task_id = allocate_task_id(dest_tasks)
            while draft.task_id in reserved or (dest_tasks / f"{draft.task_id}.md").exists():
                draft.task_id = allocate_task_id(dest_tasks)
            reserved.add(draft.task_id)
            report.warnings.append(f"{orbit_id}: converted → {draft.task_id} (orbit_id preserved)")
        dest = resolve_dest_path(dest_tasks, draft.task_id)
        if dest is None:
            _skip(report, path, f"skip (path escape {draft.task_id!r}): {path}")
            continue
        if draft.task_id in seen_ids:
            _skip(report, path, f"skip (duplicate id {draft.task_id}): {path}")
            continue
        if dest.exists():
            _skip(report, path, f"skip (exists, no overwrite): {dest}")
            continue
        md = agentized_markdown(draft)
        seen_ids.add(draft.task_id)
        report.drafts.append(draft)
        report.warnings.extend(draft.warnings)
        report.would_write.append(str(dest))
        if not dry_run:
            dest_tasks.mkdir(parents=True, exist_ok=True)
            dest.write_text(md, encoding="utf-8")
    return report


def format_report(report: ImportReport) -> str:
    lines = [
        f"orbit-import {'DRY-RUN' if report.dry_run else 'WRITE'}",
        f"  sources: {len(report.sources)}",
        f"  would_write: {len(report.would_write)}",
        f"  skipped: {len(report.skipped)}",
        f"  errors: {len(report.errors)}",
    ]
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
