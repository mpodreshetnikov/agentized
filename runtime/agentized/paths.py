from __future__ import annotations

import json
from pathlib import Path

CONNECT_MARKER_BEGIN = "<!-- AGENTIZED:BEGIN -->"
CONNECT_MARKER_END = "<!-- AGENTIZED:END -->"
STATE_DIRNAME = ".agentized"
STATE_FILENAME = "connect.json"
DEFAULT_CONTEXT = "context"


def find_repo_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists() or (candidate / "AGENTS.md").exists():
            return candidate
    return cur


def context_dir(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    return (root / context_rel).resolve()


def require_safe_rel(raw: object, *, field: str) -> str:
    text = str(raw).strip() if raw is not None else ""
    path = Path(text)
    if text == "" or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a safe relative path")
    return path.as_posix()


def resolve_context_dir(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    """Context dir confined under ``root`` (rejects abs / ``..`` / symlink escape)."""
    root_res = root.resolve()
    rel = require_safe_rel(context_rel, field="context")
    ctx = (root_res / rel).resolve()
    try:
        ctx.relative_to(root_res)
    except ValueError as exc:
        raise ValueError("context path escapes repository root") from exc
    return ctx


def path_under(base: Path, *parts: str) -> Path:
    """Join ``parts`` under ``base``; refuse symlink/path escapes."""
    target = base.joinpath(*parts).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError("path escapes context directory") from exc
    return target


def under_context(root: Path, context_rel: str, *parts: str) -> Path:
    return path_under(resolve_context_dir(root, context_rel), *parts)


def state_path(root: Path) -> Path:
    return root / STATE_DIRNAME / STATE_FILENAME


def load_state(root: Path) -> dict:
    path = state_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(root: Path, data: dict) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
