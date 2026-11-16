"""Minimal harness hooks refuse planning (AGE-36) — mutation include_globs.

Broken / non-object harness JSON → action=refuse. Full merge/strip is AGE-23.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .hooks_install_io import HooksJsonError, read_json_object

# Re-export for callers/tests.
__all__ = [
    "HARNESS_HOOK_PATHS",
    "HooksJsonError",
    "read_json_object",
    "refuse_plan",
    "plan_harness_hooks",
    "uninstall_harness_hooks",
]

HARNESS_HOOK_PATHS: dict[str, str] = {
    "cursor": ".cursor/hooks.json",
    "claude": ".claude/settings.json",
    "codex": ".codex/hooks.json",
}


def refuse_plan(path: Path, harness: str, exc: HooksJsonError) -> dict[str, Any]:
    return {
        "path": str(path),
        "harness": harness,
        "action": "refuse",
        "changed": False,
        "wrote": False,
        "error": str(exc),
        "reason": exc.reason,
    }


def _require_context_rel(context_rel: str) -> None:
    if not isinstance(context_rel, str) or context_rel == "":
        raise ValueError("context_rel required")


def plan_harness_hooks(
    root: Path,
    harnesses: list[str],
    *,
    context_rel: str,
) -> list[dict[str, Any]]:
    """Plan hook file actions. Broken JSON → refuse; missing → create; else update."""
    _require_context_rel(context_rel)
    plans: list[dict[str, Any]] = []
    for harness in HARNESS_HOOK_PATHS:
        if harness not in harnesses:
            continue
        path = root / HARNESS_HOOK_PATHS[harness]
        try:
            read_json_object(path)
        except HooksJsonError as exc:
            plans.append(refuse_plan(path, harness, exc))
            continue
        exists = path.exists()
        plans.append(
            {
                "path": str(path),
                "harness": harness,
                "action": "update" if exists else "create",
                "changed": True,
            }
        )
    return plans


def uninstall_harness_hooks(
    root: Path,
    harnesses: list[str],
    *,
    context_rel: str,
) -> list[dict[str, Any]]:
    """Refuse on broken JSON. Skip valid files until AGE-23 strip helpers exist."""
    _require_context_rel(context_rel)
    results: list[dict[str, Any]] = []
    for harness in HARNESS_HOOK_PATHS:
        if harness not in harnesses:
            continue
        path = root / HARNESS_HOOK_PATHS[harness]
        if not path.exists():
            continue
        try:
            read_json_object(path)
        except HooksJsonError as exc:
            results.append(refuse_plan(path, harness, exc))
            continue
        results.append(
            {
                "path": str(path),
                "harness": harness,
                "action": "skip",
                "changed": False,
                "wrote": False,
                "reason": "hooks_merge_unavailable",
            }
        )
    return results
