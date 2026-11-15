"""Default quality.json payload (kept outside mutation include_globs).

Literal defaults create hundreds of uninformative mutmut survivors; the
hard gate still covers `quality.py` merge/normalize/save logic.
"""
from __future__ import annotations

from typing import Any

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
            # Maxim / Orbit: hard gate on mutationScoreCovered only (not overall score).
            "min_score_covered": 100,
            "break_on_survived": True,
            "break_on_no_tests": True,
            "include_globs": [
                "runtime/agentized/quality.py",
                "runtime/agentized/paths.py",
                "runtime/agentized/tasks.py",
                "runtime/agentized/leases.py",
                "runtime/agentized/hook_common.py",
            ],
        },
        "test_smells": {
            "enabled": True,
            "mode": "warn",
            "include_globs": [
                "tests/unit/**/*.py",
                "tests/quality/**/*.py",
                "tests/**/test_*.py",
            ],
        },
        "architecture": {
            "enabled": True,
            "mode": "warn",
            "tool": "import-linter",
            "config": ".importlinter",
            "source_roots": ["runtime/agentized"],
            "forbidden_edges": [],
        },
        "property_based": {
            "enabled": False,
            "tools": {"python": "hypothesis", "javascript": "fast-check"},
            "pilot_modules": [],
        },
        "e2e": {
            "enabled": False,
            "on_failure_artifacts": ["video", "screenshot"],
            "new_spec_retries": 3,
            "forbid": ["pixel_compare", "snapshot_markup", "formal_contracts"],
        },
        "shared_fixtures": {
            "required_when_duplicated_logic": True,
        },
        "batch_release": {
            "shared_ci_for_reviewed_prs": True,
            "keep_up_to_date_protection": True,
        },
        "gates": {
            "pre_push": [
                "mechanical",
                "module_tests",
                "coverage",
                "test_smells",
                "architecture",
                "mutation",
            ],
            "ci": [
                "mechanical",
                "module_tests",
                "coverage",
                "test_smells",
                "architecture",
                "mutation",
            ],
        },
        "reviewer": {
            "enabled": True,
            "helper_model": "composer-2",
            "budget_max": 3,
            "delta_lines": 200,
            "harnesses": {
                "cursor": {
                    "model": "grok-4.7[reasoning_effort=medium]",
                    "effort": "medium",
                },
                "claude": {"model": "claude-fable-5-2", "effort": "medium"},
                "codex": {"model": "gpt-6-astra", "effort": "medium"},
            },
        },
    }
