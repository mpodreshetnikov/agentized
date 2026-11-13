"""Versioned quality config (coverage thresholds, modules, mutation gate)."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT

QUALITY_FILENAME = "quality.json"
DEFAULT_COVERAGE_PCT = 80
SCHEMA_VERSION = 1


def default_quality_config() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "coverage": {"lines": DEFAULT_COVERAGE_PCT, "branches": DEFAULT_COVERAGE_PCT},
        "modules": [
            {
                "id": "runtime",
                "source": ["runtime/agentized"],
                "test_command": (
                    "python3 -m pytest tests/unit tests/quality -q --cov=runtime/agentized --cov-branch "
                    "--cov-report=term-missing "
                    "--cov-report=lcov:coverage/runtime/lcov.info "
                    "--cov-report=json:coverage/runtime/coverage.json "
                    "--cov-fail-under=0"
                ),
                "coverage_lcov": "coverage/runtime/lcov.info",
                "coverage_json": "coverage/runtime/coverage.json",
                "thresholds": {},
            }
        ],
        "mutation": {
            "enabled": True,
            "tool": "mutmut",
            "gate": "hard",
            "scope": "covered_changed_lines",
            "base_ref": "origin/main",
            "min_score_covered": 50,
            "break_on_survived": False,
            "break_on_no_tests": True,
            "include_globs": [
                "runtime/agentized/quality.py",
                "runtime/agentized/paths.py",
                "runtime/agentized/tasks.py",
                "runtime/agentized/leases.py",
                "runtime/agentized/hook_common.py",
            ],
        },
        "gates": {
            "pre_push": ["mechanical", "module_tests", "coverage", "mutation"],
            "ci": ["mechanical", "module_tests", "coverage", "mutation"],
        },
    }


def quality_path(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    return root / context_rel / QUALITY_FILENAME


def load_quality(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    path = quality_path(root, context_rel)
    if not path.exists():
        return default_quality_config()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return _normalize(data)


def save_quality(root: Path, data: dict[str, Any], context_rel: str = DEFAULT_CONTEXT) -> Path:
    path = quality_path(root, context_rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize(data)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    data = load_quality(root, context_rel)
    cov = data.setdefault("coverage", {})
    if lines:
        cov["lines"] = value
    if branches:
        cov["branches"] = value
    save_quality(root, data, context_rel)
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
    gates_in = data.get("gates") or {}
    out["gates"].update({k: gates_in[k] for k in gates_in})
    return out
