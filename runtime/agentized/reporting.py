"""Acceptance / handoff reporting level (short vs technical)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT

REPORTING_FILENAME = "reporting.json"
LEVELS = ("short", "technical")
DOC = "packages/shared/skills/acceptance-artifacts/SKILL.md"


def default_reporting_config() -> dict[str, Any]:
    return {
        "version": 1,
        "level": "short",
        "_comment": (
            "level=short|technical. short is default: business-readable, compressed, "
            "no code/SHAs. See acceptance-artifacts skill."
        ),
    }


def reporting_path(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    return root / context_rel / REPORTING_FILENAME


def load_reporting(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    path = reporting_path(root, context_rel)
    cfg = default_reporting_config()
    if not path.exists():
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return cfg
    if isinstance(data, dict):
        cfg.update({k: data[k] for k in data})
    level = str(cfg.get("level") or "short").lower()
    if level not in LEVELS:
        level = "short"
    cfg["level"] = level
    return cfg


def save_reporting(
    root: Path, data: dict[str, Any], context_rel: str = DEFAULT_CONTEXT
) -> Path:
    path = reporting_path(root, context_rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    level = str(data.get("level") or "short").lower()
    if level not in LEVELS:
        raise ValueError(f"reporting level must be one of {LEVELS}")
    out = default_reporting_config()
    out.update(data)
    out["level"] = level
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def set_reporting_level(
    root: Path, level: str, *, context_rel: str = DEFAULT_CONTEXT
) -> dict[str, Any]:
    level = level.lower().strip()
    if level not in LEVELS:
        raise ValueError(f"reporting level must be one of {LEVELS}")
    data = load_reporting(root, context_rel)
    data["level"] = level
    save_reporting(root, data, context_rel)
    return data


def ensure_reporting_config(root: Path, context_rel: str) -> dict[str, Any]:
    """Pin default reporting.json without clobbering user edits."""
    path = reporting_path(root, context_rel)
    created = not path.exists()
    if created:
        save_reporting(root, default_reporting_config(), context_rel)
    return {"path": str(path.relative_to(root)), "created": created}
