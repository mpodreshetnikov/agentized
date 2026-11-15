"""Versioned quality config (coverage thresholds, modules, mutation gate)."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT
from .quality_defaults import (
    DEFAULT_COVERAGE_PCT,
    SCHEMA_VERSION,
    default_quality_config,
)
from .quality_io import read_json_object, write_json_object

QUALITY_FILENAME = "quality.json"

# Re-export for existing importers / tests.
__all__ = [
    "QUALITY_FILENAME",
    "DEFAULT_COVERAGE_PCT",
    "SCHEMA_VERSION",
    "default_quality_config",
    "quality_path",
    "load_quality",
    "save_quality",
    "set_coverage_threshold",
    "module_thresholds",
    "set_reviewer_options",
]


def quality_path(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    return root / context_rel / QUALITY_FILENAME


def load_quality(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    rel = context_rel
    path = quality_path(root, rel)
    if not path.exists():
        return default_quality_config()
    return _normalize(read_json_object(path))


def save_quality(root: Path, data: dict[str, Any], context_rel: str = DEFAULT_CONTEXT) -> Path:
    rel = context_rel
    path = quality_path(root, rel)
    normalized = _normalize(data)
    write_json_object(path, normalized)
    return path


def set_coverage_threshold(
    root: Path,
    pct: float | int,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    lines: bool = True,
    branches: bool = True,
) -> dict[str, Any]:
    """Update global coverage thresholds (used by `connect --coverage` and `quality set-coverage`)."""
    value = float(pct)
    if value < 0 or value > 100:
        raise ValueError("coverage threshold must be between 0 and 100")
    rel = context_rel
    data = load_quality(root, rel)
    cov = data["coverage"]
    if lines:
        cov["lines"] = value
    if branches:
        cov["branches"] = value
    save_quality(root, data, rel)
    return data


def module_thresholds(cfg: dict[str, Any], module: dict[str, Any]) -> tuple[float, float]:
    global_cov = cfg.get("coverage") or {}
    local = module.get("thresholds") or {}
    lines = local.get("lines")
    branches = local.get("branches")
    if lines is None:
        lines = global_cov.get("lines", DEFAULT_COVERAGE_PCT)
    if branches is None:
        branches = global_cov.get("branches", DEFAULT_COVERAGE_PCT)
    return float(lines), float(branches)


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(default_quality_config())
    out["version"] = int(data.get("version") or SCHEMA_VERSION)
    cov_in = data.get("coverage") or {}
    out["coverage"]["lines"] = float(cov_in.get("lines", DEFAULT_COVERAGE_PCT))
    out["coverage"]["branches"] = float(cov_in.get("branches", DEFAULT_COVERAGE_PCT))
    if isinstance(data.get("modules"), list) and data["modules"]:
        out["modules"] = data["modules"]
    mut_in = data.get("mutation") or {}
    out["mutation"].update({k: mut_in[k] for k in mut_in})
    for key in (
        "test_smells",
        "architecture",
        "property_based",
        "e2e",
        "shared_fixtures",
        "batch_release",
    ):
        section = data.get(key)
        if isinstance(section, dict):
            out[key].update(section)
    gates_in = data.get("gates") or {}
    out["gates"].update({k: gates_in[k] for k in gates_in})
    rev_in = data.get("reviewer") or {}
    if isinstance(rev_in, dict):
        out["reviewer"].update({k: rev_in[k] for k in rev_in})
    return out


def set_reviewer_options(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    model: str | None = None,
    effort: str | None = None,
    helper_model: str | None = None,
    budget_max: int | None = None,
    harness: str | None = None,
) -> dict[str, Any]:
    rel = context_rel
    data = load_quality(root, rel)
    rev = data["reviewer"]
    if harness:
        harnesses = rev.get("harnesses")
        if not isinstance(harnesses, dict):
            harnesses = {}
            rev["harnesses"] = harnesses
        entry = harnesses.get(harness)
        if not isinstance(entry, dict):
            entry = {}
            harnesses[harness] = entry
        if model is not None:
            entry["model"] = model
        if effort is not None:
            entry["effort"] = effort
    else:
        if model is not None:
            rev["model"] = model
        if effort is not None:
            rev["effort"] = effort
    if helper_model is not None:
        rev["helper_model"] = helper_model
    if budget_max is not None:
        rev["budget_max"] = int(budget_max)
    save_quality(root, data, rel)
    return data
