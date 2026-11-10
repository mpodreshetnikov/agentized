from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class Lease:
    path: Path
    task_id: str
    owner: str
    paths: list[str]
    expires: str
    status: str


LEASE_FIELD_RE = re.compile(
    r"^(task|owner|expires|status|paths):\s*(.*)$", re.MULTILINE | re.IGNORECASE
)


def _parse_paths_block(text: str) -> list[str]:
    paths: list[str] = []
    in_paths = False
    for line in text.splitlines():
        if re.match(r"^paths:\s*$", line, re.IGNORECASE):
            in_paths = True
            continue
        if in_paths:
            if re.match(r"^[a-zA-Zа-яА-Я_][\w\-]*:", line):
                break
            m = re.match(r"^\s*-\s+(.+)$", line)
            if m:
                paths.append(m.group(1).strip())
            elif line.strip() == "":
                continue
            else:
                break
    # also support inline: paths: a, b
    for key, val in LEASE_FIELD_RE.findall(text):
        if key.lower() == "paths" and val.strip() and not val.strip().startswith("-"):
            paths.extend([p.strip() for p in val.split(",") if p.strip()])
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def parse_lease(path: Path) -> Lease | None:
    if path.name == "INDEX.md" or not path.name.endswith(".md"):
        return None
    text = path.read_text(encoding="utf-8")
    fields = {k.lower(): v.strip() for k, v in LEASE_FIELD_RE.findall(text)}
    task_id = fields.get("task") or path.stem
    owner = fields.get("owner") or ""
    expires = fields.get("expires") or ""
    status = (fields.get("status") or "active").lower()
    return Lease(
        path=path,
        task_id=task_id,
        owner=owner,
        paths=_parse_paths_block(text),
        expires=expires,
        status=status,
    )


def list_leases(leases_dir: Path, *, active_only: bool = True) -> list[Lease]:
    out: list[Lease] = []
    for path in sorted(leases_dir.glob("*.md")):
        lease = parse_lease(path)
        if not lease:
            continue
        if active_only and lease.status != "active":
            continue
        out.append(lease)
    return out


def path_overlaps(a: str, b: str) -> bool:
    a_n = a.rstrip("/")
    b_n = b.rstrip("/")
    if a_n == b_n:
        return True
    return a_n.startswith(b_n + "/") or b_n.startswith(a_n + "/")


def find_overlaps(
    leases: list[Lease], candidate_paths: list[str], *, ignore_task: str | None = None
) -> list[tuple[Lease, str, str]]:
    hits: list[tuple[Lease, str, str]] = []
    for lease in leases:
        if ignore_task and lease.task_id == ignore_task:
            continue
        for held in lease.paths:
            for cand in candidate_paths:
                if path_overlaps(held, cand):
                    hits.append((lease, held, cand))
    return hits


def render_lease_file(
    task_id: str,
    owner: str,
    paths: list[str],
    *,
    expires: str | None = None,
    status: str = "active",
) -> str:
    if not expires:
        expires = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    path_lines = "\n".join(f"- {p}" for p in paths) if paths else "- _(нет)_"
    return (
        f"# Lease {task_id}\n\n"
        f"task: {task_id}\n"
        f"owner: {owner}\n"
        f"expires: {expires}\n"
        f"status: {status}\n"
        f"paths:\n{path_lines}\n"
    )


def rebuild_lease_index(leases_dir: Path) -> str:
    leases = list_leases(leases_dir, active_only=True)
    rows = []
    for lease in leases:
        for p in lease.paths:
            rows.append(f"| `{p}` | {lease.task_id} | {lease.owner} | {lease.expires} |")
    body = (
        "\n".join(rows)
        if rows
        else "| _(пусто)_ | | | |"
    )
    return (
        "# Path leases — индекс\n\n"
        "Кто держит какие пути кода. Генерируемый индекс.\n\n"
        "| путь | задача | владелец | истекает |\n"
        "|------|--------|----------|----------|\n"
        f"{body}\n\n"
        "Политика v1: leases **предупреждают** о пересечении write-paths, запись не блокируют.\n"
    )


def warn_message(overlaps: list[tuple[Lease, str, str]]) -> str:
    if not overlaps:
        return ""
    lines = [
        "AGENTIZED LEASE WARN (warn-only, write not blocked): overlapping write-paths detected."
    ]
    for lease, held, cand in overlaps:
        lines.append(
            f"- candidate `{cand}` overlaps lease `{held}` "
            f"(task {lease.task_id}, owner {lease.owner})"
        )
    lines.append("Continue if merge is expected; do not treat this as a lock.")
    return "\n".join(lines)
