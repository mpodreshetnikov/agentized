"""Default quality.json payload for connect / new projects.

`mutation.include_globs` defaults to full-cover `runtime/agentized/*.py`
(Python `fnmatch` `*` matches `/`, so one pattern covers flat and nested).
Editing this module pulls it into the hard mutation gate when changed.
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
        "languages": {
            # detect:false is refused — always detect (AGE-24).
            "supported": ["python", "javascript", "typescript"],
            "exclude_globs": [
                "node_modules/**",
                "vendor/**",
                "third_party/**",
                "dist/**",
                "build/**",
                "out/**",
                "**/dist/**",
                "**/build/**",
                "**/out/**",
                ".venv/**",
                "venv/**",
                "**/.venv/**",
                "**/venv/**",
                "**/__pycache__/**",
                "**/.tox/**",
                "**/site-packages/**",
                "mutants/**",
                "coverage/**",
                "reports/**",
                "**/*.min.js",
                "**/generated/**",
                "**/.git/**",
                "target/**",
                "**/target/**",
                "Pods/**",
                "**/Pods/**",
                "**/*.example",
                "**/*.example.*",
                "**/*.example.cjs",
                "**/*.example.mjs",
                ".cursor/**",
                ".claude/**",
                ".codex/**",
                ".agents/**",
                "context/hooks/**",
                ".pytest_cache/**",
                "**/.pytest_cache/**",
                ".mypy_cache/**",
                "**/.mypy_cache/**",
                ".ruff_cache/**",
                "**/.ruff_cache/**",
            ],
        },
        "mutation": {
            "enabled": True,
            "tool": "mutmut",
            "tools": {
                "python": "mutmut",
                "javascript": "stryker",
                "typescript": "stryker",
            },
            "gate": "hard",
            "scope": "covered_changed_lines",
            "base_ref": "origin/main",
            # Maxim / Orbit: hard gate on mutationScoreCovered only (not overall score).
            "min_score_covered": 100,
            "break_on_survived": True,
            "break_on_no_tests": True,
            "include_globs": [
                "runtime/agentized/*.py",
            ],
        },
        "test_smells": {
            "enabled": True,
            "mode": "hard",
            "include_globs": [
                "tests/unit/**/*.py",
                "tests/quality/**/*.py",
                "tests/**/test_*.py",
            ],
        },
        "architecture": {
            "enabled": True,
            "mode": "hard",
            "tool": "import-linter",
            "tools": {
                "python": "import-linter",
                "javascript": "dependency-cruiser",
                "typescript": "dependency-cruiser",
            },
            "config": ".importlinter",
            "js_config": ".dependency-cruiser.cjs",
            "js_source": "src",
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
