"""Public context-path confinement helpers (AGE-30).

CLI/autopilot import from here — kept out of ``paths.py`` so incremental
mutation does not re-tax the whole connect-state module.
"""

from __future__ import annotations

from pathlib import Path

from .paths import DEFAULT_CONTEXT


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
