"""Public context-path confinement helpers (AGE-30).

CLI/autopilot import from here — kept out of ``paths.py`` so incremental
mutation does not re-tax the whole connect-state module.
"""

from __future__ import annotations

from pathlib import Path

from .paths import DEFAULT_CONTEXT

# External Context bridges may resolve outside the code-repo ``context/`` tree.
# Only these first-path names may escape via symlink; other escapes stay refused.
BRIDGE_ESCAPE_NAMES = frozenset({"tasks", "leases", "decisions", "goals", "digests", "NAV.md"})


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
    """Join ``parts`` under ``base``; refuse symlink/path escapes.

    Exception: first component in ``BRIDGE_ESCAPE_NAMES`` that is a symlink may
    resolve outside ``base`` (external Context bridges). Target must stay under
    that bridge's resolved root.
    """
    if not parts:
        return base.resolve()
    base_res = base.resolve()
    target = base.joinpath(*parts).resolve()
    try:
        target.relative_to(base_res)
        return target
    except ValueError as exc:
        first = parts[0]
        if first in BRIDGE_ESCAPE_NAMES:
            bridge = base / first
            if bridge.is_symlink():
                try:
                    target.relative_to(bridge.resolve())
                    return target
                except ValueError:
                    pass
        raise ValueError("path escapes context directory") from exc


def under_context(root: Path, context_rel: str, *parts: str) -> Path:
    return path_under(resolve_context_dir(root, context_rel), *parts)
