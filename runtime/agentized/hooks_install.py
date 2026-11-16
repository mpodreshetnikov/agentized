"""Minimal harness hooks I/O for dry-run / uninstall refuse (AGE-36).

Full foreign-preserving merge/strip lives in AGE-23 `hooks_merge`. This module
only loads harness JSON and returns refuse plans for broken / non-object files.
Valid files are planned as create/update; uninstall skips them until AGE-23
strip helpers land (rebase then drop duplicates).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


HOOKS_OWNED_FILENAME = "hooks_owned.json"

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
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except OSError as exc:
        raise HooksJsonError(path, f"unreadable ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise HooksJsonError(path, f"broken JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise HooksJsonError(path, f"top-level must be object, got {type(data).__name__}")
    return data


def write_json(path: Path, data: dict) -> bool:
    """Write JSON if content would change. Returns True when a write happened."""
    text = json.dumps(data, indent=2) + "\n"
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def hooks_owned_path(root: Path, context_rel: str = "context") -> Path:
    return root / context_rel / ".agentized" / HOOKS_OWNED_FILENAME


def load_hooks_owned(root: Path, context_rel: str = "context") -> dict[str, list[str]]:
    path = hooks_owned_path(root, context_rel)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, value in data.items():
        if isinstance(value, list):
            out[str(key)] = [str(item) for item in value]
    return out


def save_hooks_owned(
    root: Path,
    owned: dict[str, list[str]],
    context_rel: str = "context",
) -> None:
    path = hooks_owned_path(root, context_rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(owned, indent=2) + "\n", encoding="utf-8")


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
    context_rel: str = "context",
) -> list[dict[str, Any]]:
    """Plan hook file actions. Broken JSON → refuse; missing → create; else update."""
    _ = context_rel  # reserved for AGE-23 ownership-aware merge after rebase
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
    context_rel: str = "context",
) -> list[dict[str, Any]]:
    """Refuse on broken JSON. Skip valid files until AGE-23 strip helpers exist."""
    _ = context_rel
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
