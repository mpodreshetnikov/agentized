"""Minimal Context skeleton for a clean connect (AGE-68).

INDEX seeds are exactly ``rebuild_task_index`` / ``rebuild_lease_index`` output
so ``agentized index`` is a no-op on a freshly connected empty Context.
"""

from __future__ import annotations

from pathlib import Path

from .leases import rebuild_lease_index
from .paths import DEFAULT_CONTEXT
from .tasks import rebuild_task_index

MINIMAL_NAV_MD = """# NAV — карта Project Context

Один экран. Читай это первым после указателя в корневом `AGENTS.md`. Дальше — только ссылки отсюда.

## Где что

| Раздел | Путь | Назначение |
|--------|------|------------|
| Задачи (живая доска) | [`tasks/INDEX.md`](tasks/INDEX.md) | Активная работа: open / in-progress / blocked |
| Path leases | [`leases/INDEX.md`](leases/INDEX.md) | Кто держит какие пути (warn-only) |
| Skills (pinned) | [`skills/`](skills/) | Skills после connect |
| Hooks (pinned) | [`hooks/`](hooks/) | session-start · process-guard · lease warn |

## Как искать задачи

1. Открой живой индекс [`tasks/INDEX.md`](tasks/INDEX.md) (только open / in-progress / blocked).
2. Дополнительно — **grep** по id, title, tags в файлах задач.
3. **Запрещено** обходить весь каталог `tasks/` листингом как единственный вход.

## Connect и harness

После `agentized connect` skills/hooks попадают в project-пути Cursor / Claude Code / Codex.
Leases только предупреждают, запись не блокируют.
"""


def ensure_context_skeleton(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict:
    """Create minimal Context (NAV.md, tasks/, leases/) if missing.

    If Context already has NAV.md, leave it alone — never overwrite user NAV
    or existing index files. INDEX seeds are exactly rebuild_task_index /
    rebuild_lease_index output so ``agentized index`` is a no-op on a fresh empty Context.
    """
    ctx = root / context_rel
    nav = ctx / "NAV.md"
    if nav.exists():
        return {
            "created": False,
            "path": context_rel,
            "files": [],
        }

    created_files: list[str] = []
    ctx.mkdir(parents=True, exist_ok=True)
    tasks_dir = ctx / "tasks"
    leases_dir = ctx / "leases"
    tasks_dir.mkdir(exist_ok=True)
    leases_dir.mkdir(exist_ok=True)

    targets = (
        (nav, MINIMAL_NAV_MD),
        (tasks_dir / "INDEX.md", rebuild_task_index(tasks_dir)),
        (leases_dir / "INDEX.md", rebuild_lease_index(leases_dir)),
    )
    for path, body in targets:
        if path.exists():
            continue
        path.write_text(body.rstrip() + "\n", encoding="utf-8")
        created_files.append(str(path.relative_to(root)))

    return {
        "created": bool(created_files),
        "path": context_rel,
        "files": created_files,
    }
