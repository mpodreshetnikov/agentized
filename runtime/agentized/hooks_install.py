"""Minimal harness hooks refuse I/O (AGE-36) — mutation include_globs.

Broken / non-object harness JSON → action=refuse. Full merge/strip is AGE-23.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


HARNESS_HOOK_PATHS: dict[str, str] = {
    "cursor": ".cursor/hooks.json",
    "claude": ".claude/settings.json",
    "codex": ".codex/hooks.json",
}


class HooksJsonError(ValueError):
    """Broken or non-object harness JSON; file must stay byte-identical."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"invalid harness JSON at {path}: {reason}")


def read_json_object(path: Path) -> dict:
    """Load a JSON object. Missing file → {}. Broken / non-object → HooksJsonError."""
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes().decode("utf-8")
        data = json.loads(raw)
    except OSError as exc:
        raise HooksJsonError(path, f"unreadable ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise HooksJsonError(path, f"not utf-8 ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise HooksJsonError(path, f"broken JSON ({exc.msg})") from exc
    if type(data) is not dict:
        raise HooksJsonError(path, f"top-level must be object, got {type(data).__name__}")
    return data


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


def plan_harness_hooks(
    root: Path,
    harnesses: list[str],
    *,
    context_rel: str,
) -> list[dict[str, Any]]:
    """Plan hook file actions. Broken JSON → refuse; missing → create; else update."""
    if not isinstance(context_rel, str) or not context_rel:
        raise ValueError("context_rel required")
    plans: list[dict[str, Any]] = []
    for harness in ("cursor", "claude", "codex"):
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
    if not isinstance(context_rel, str) or not context_rel:
        raise ValueError("context_rel required")
    results: list[dict[str, Any]] = []
    for harness in ("cursor", "claude", "codex"):
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
