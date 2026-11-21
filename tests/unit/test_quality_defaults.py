"""Pin default_quality_config — kills mutmut survivors on this module."""

from __future__ import annotations

from agentized.quality_defaults import (
    DEFAULT_COVERAGE_PCT,
    SCHEMA_VERSION,
    default_quality_config,
)


def test_constants():
    assert DEFAULT_COVERAGE_PCT == 80
    assert SCHEMA_VERSION == 1


def test_default_quality_config_full_cover_globs_and_structure():
    cfg = default_quality_config()
    assert cfg["version"] == 1
    assert cfg["coverage"] == {"lines": 80, "branches": 80}
    assert cfg["modules"] == [
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
    ]
    mut = cfg["mutation"]
    assert mut == {
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
        "min_score_covered": 100,
        "break_on_survived": True,
        "break_on_no_tests": True,
        # Python fnmatch *: matches / — one pattern covers flat + nested.
        "include_globs": ["runtime/agentized/*.py"],
    }
    assert cfg["test_smells"] == {
        "enabled": True,
        "mode": "hard",
        "include_globs": [
            "tests/unit/**/*.py",
            "tests/quality/**/*.py",
            "tests/**/test_*.py",
            "**/*.{test,spec}.{js,jsx,ts,tsx}",
            "**/__tests__/**/*.{js,jsx,ts,tsx}",
        ],
    }
    assert cfg["architecture"] == {
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
    }
    assert cfg["property_based"] == {
        "enabled": False,
        "tools": {"python": "hypothesis", "javascript": "fast-check"},
        "pilot_modules": [],
    }
    assert cfg["e2e"] == {
        "enabled": False,
        "on_failure_artifacts": ["video", "screenshot"],
        "new_spec_retries": 3,
        "forbid": ["pixel_compare", "snapshot_markup", "formal_contracts"],
    }
    assert cfg["shared_fixtures"] == {"required_when_duplicated_logic": True}
    assert cfg["batch_release"] == {
        "shared_ci_for_reviewed_prs": True,
        "keep_up_to_date_protection": True,
    }
    assert cfg["gates"] == {
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
    }
    assert cfg["reviewer"] == {
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
    }
    # Fresh call is independent (no shared mutable default).
    cfg2 = default_quality_config()
    cfg["mutation"]["include_globs"].append("x")
    assert cfg2["mutation"]["include_globs"] == ["runtime/agentized/*.py"]
