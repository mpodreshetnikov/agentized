"""High-signal tests for quality.py merge/normalize (mutation hard gate)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentized.quality import (
    DEFAULT_COVERAGE_PCT,
    SCHEMA_VERSION,
    default_quality_config,
    load_quality,
    module_thresholds,
    quality_path,
    save_quality,
    set_coverage_threshold,
    set_reviewer_options,
)


def test_default_config_contract():
    cfg = default_quality_config()
    assert cfg["version"] == SCHEMA_VERSION
    assert cfg["coverage"]["lines"] == DEFAULT_COVERAGE_PCT
    assert cfg["mutation"]["min_score_covered"] == 100
    assert cfg["mutation"]["break_on_survived"] is True
    assert cfg["test_smells"]["mode"] == "hard"
    assert cfg["architecture"]["mode"] == "hard"
    assert "mutation" in cfg["gates"]["ci"]


def test_load_missing_returns_defaults(tmp_path: Path):
    data = load_quality(tmp_path / "nope")
    assert data["mutation"]["gate"] == "hard"
    assert data["coverage"]["lines"] == DEFAULT_COVERAGE_PCT


def test_load_rejects_non_object(tmp_path: Path):
    path = quality_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("[1,2]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected JSON object"):
        load_quality(tmp_path)


def test_normalize_merges_sections_and_preserves_modules(tmp_path: Path):
    save_quality(
        tmp_path,
        {
            "version": "2",
            "coverage": {"lines": 91},
            "modules": [{"id": "only", "source": ["src"]}],
            "mutation": {"min_score_covered": 100, "enabled": False},
            "test_smells": {"mode": "hard", "oracle_token": "KEEP_SMELLS"},
            "architecture": {"tool": "builtin"},
            "property_based": {"enabled": True, "pilot_modules": ["a"]},
            "e2e": {"enabled": True, "new_spec_retries": 5},
            "shared_fixtures": {"required_when_duplicated_logic": False},
            "batch_release": {"keep_up_to_date_protection": False},
            "gates": {"ci": ["coverage", "mutation"]},
            "reviewer": {"budget_max": 9, "helper_model": "x"},
        },
    )
    data = load_quality(tmp_path)
    assert data["version"] == 2
    assert data["coverage"]["lines"] == 91.0
    assert data["coverage"]["branches"] == float(DEFAULT_COVERAGE_PCT)
    assert data["modules"] == [{"id": "only", "source": ["src"]}]
    assert data["mutation"]["enabled"] is False
    assert data["mutation"]["min_score_covered"] == 100
    assert data["test_smells"]["mode"] == "hard"
    assert data["test_smells"]["oracle_token"] == "KEEP_SMELLS"
    assert data["architecture"]["tool"] == "builtin"
    assert data["property_based"]["pilot_modules"] == ["a"]
    assert data["e2e"]["new_spec_retries"] == 5
    assert data["shared_fixtures"]["required_when_duplicated_logic"] is False
    assert data["batch_release"]["keep_up_to_date_protection"] is False
    assert data["gates"]["ci"] == ["coverage", "mutation"]
    assert data["reviewer"]["budget_max"] == 9
    assert data["reviewer"]["helper_model"] == "x"
    assert "languages" in data
    assert "python" in data["languages"]["supported"]
    assert data["mutation"]["tools"]["python"] == "mutmut"
    # Kill mutants that rename the "languages" merge key — custom section must win.
    save_quality(
        tmp_path,
        {
            "languages": {
                "supported": ["python"],
                "exclude_globs": ["CUSTOM_ONLY/**"],
            }
        },
    )
    lang = load_quality(tmp_path)["languages"]
    assert lang["supported"] == ["python"]
    assert lang["exclude_globs"] == ["CUSTOM_ONLY/**"]
    # empty modules list must not wipe defaults
    save_quality(tmp_path, {"modules": [], "coverage": {"branches": 66}})
    data2 = load_quality(tmp_path)
    assert data2["modules"]  # defaults restored
    assert data2["coverage"]["branches"] == 66.0


def test_set_coverage_lines_only_and_bounds(tmp_path: Path):
    save_quality(tmp_path, default_quality_config())
    # Default kwargs update BOTH lines and branches (kills branches=False default).
    both = set_coverage_threshold(tmp_path, 55)
    assert both["coverage"]["lines"] == 55.0
    assert both["coverage"]["branches"] == 55.0
    out = set_coverage_threshold(tmp_path, 88, lines=True, branches=False)
    assert out["coverage"]["lines"] == 88.0
    assert out["coverage"]["branches"] == 55.0
    out2 = set_coverage_threshold(tmp_path, 77, lines=False, branches=True)
    assert out2["coverage"]["lines"] == 88.0
    assert out2["coverage"]["branches"] == 77.0
    # Inclusive bounds: 0 and 100 must be accepted.
    assert set_coverage_threshold(tmp_path, 0)["coverage"]["lines"] == 0.0
    assert set_coverage_threshold(tmp_path, 100)["coverage"]["lines"] == 100.0
    with pytest.raises(ValueError, match="^coverage threshold must be between 0 and 100$"):
        set_coverage_threshold(tmp_path, -1)
    with pytest.raises(ValueError, match="^coverage threshold must be between 0 and 100$"):
        set_coverage_threshold(tmp_path, 101)


def test_custom_context_rel_and_exact_json_layout(tmp_path: Path):
    """Kill mutants that drop context_rel or alter dumps formatting."""
    ctx = "alt-context"
    # Do NOT pre-create parents — save must mkdir nested a/b/c/ctx/.
    nested = tmp_path / "a" / "b" / "c"
    save_quality(nested, {"coverage": {"lines": 83, "branches": 84}}, context_rel=ctx)
    path = quality_path(nested, ctx)
    assert path.exists()
    assert not quality_path(nested).exists()  # default context unused
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '"lines": 83.0' in text or '"lines": 83' in text
    # indent=2 layout (not compact, not indent=3)
    assert '\n  "version"' in text or '\n  "coverage"' in text
    assert '\n   "' not in text  # no 3-space indent markers from indent=3
    data = load_quality(nested, context_rel=ctx)
    assert data["coverage"]["lines"] == 83.0
    # Second save must succeed when the directory already exists (exist_ok path).
    save_quality(nested, {"coverage": {"lines": 83, "branches": 84}}, context_rel=ctx)
    # Partial update must load *this* context (not defaults): keep branches=84.
    set_coverage_threshold(nested, 92, context_rel=ctx, lines=True, branches=False)
    again = load_quality(nested, context_rel=ctx)
    assert again["coverage"]["lines"] == 92.0
    assert again["coverage"]["branches"] == 84.0
    assert not quality_path(nested).exists()
    set_reviewer_options(
        nested, context_rel=ctx, harness="codex", model="m-codex", helper_model="помощник"
    )
    loaded = load_quality(nested, context_rel=ctx)
    assert loaded["reviewer"]["harnesses"]["codex"]["model"] == "m-codex"
    assert loaded["reviewer"]["helper_model"] == "помощник"
    # ensure_ascii=False keeps Cyrillic literal (not \\uXXXX).
    assert "помощник" in quality_path(nested, ctx).read_text(encoding="utf-8")
    # Seed effort then preserve it across model-only update (kills entry=None wipe).
    set_reviewer_options(nested, context_rel=ctx, harness="codex", model="m1", effort="high")
    set_reviewer_options(nested, context_rel=ctx, harness="codex", model="m2")
    preserved = load_quality(nested, context_rel=ctx)
    assert preserved["reviewer"]["harnesses"]["codex"] == {"model": "m2", "effort": "high"}
    assert preserved["reviewer"]["helper_model"] == "помощник"
    assert not quality_path(nested).exists()


def test_module_thresholds_fallbacks():
    cfg = {"coverage": {"lines": 80, "branches": 70}}
    assert module_thresholds(cfg, {"thresholds": {}}) == (80.0, 70.0)
    # Non-default lines kills get("lines")→get(None)/LINES equivalent-at-80 mutants
    cfg81 = {"coverage": {"lines": 81, "branches": 70}}
    assert module_thresholds(cfg81, {"thresholds": {}}) == (81.0, 70.0)
    assert module_thresholds(cfg, {"thresholds": {"lines": 60}}) == (60.0, 70.0)
    assert module_thresholds({}, {"thresholds": {}}) == (
        float(DEFAULT_COVERAGE_PCT),
        float(DEFAULT_COVERAGE_PCT),
    )
    assert module_thresholds({"coverage": {}}, {"thresholds": {"branches": 55}}) == (
        float(DEFAULT_COVERAGE_PCT),
        55.0,
    )


def test_set_reviewer_harness_and_global(tmp_path: Path):
    save_quality(tmp_path, default_quality_config())
    set_reviewer_options(tmp_path, harness="cursor", model="m1", effort="high")
    data = load_quality(tmp_path)
    assert data["reviewer"]["harnesses"]["cursor"]["model"] == "m1"
    assert data["reviewer"]["harnesses"]["cursor"]["effort"] == "high"
    set_reviewer_options(tmp_path, model="legacy", effort="low", helper_model="h", budget_max=4)
    data2 = load_quality(tmp_path)
    assert data2["reviewer"]["model"] == "legacy"
    assert data2["reviewer"]["effort"] == "low"
    assert data2["reviewer"]["helper_model"] == "h"
    assert data2["reviewer"]["budget_max"] == 4
    raw = json.loads(quality_path(tmp_path).read_text(encoding="utf-8"))
    assert raw["reviewer"]["budget_max"] == 4
    # New harness name must be created when missing without wiping others.
    set_reviewer_options(tmp_path, harness="brand-new", model="n1", effort="medium")
    harnesses = load_quality(tmp_path)["reviewer"]["harnesses"]
    assert harnesses["brand-new"] == {"model": "n1", "effort": "medium"}
    assert harnesses["cursor"]["model"] == "m1"
    # Recovery when harnesses was corrupted to a non-dict by a prior write.
    save_quality(tmp_path, {"reviewer": {"harnesses": "bad", "helper_model": "keep"}})
    assert load_quality(tmp_path)["reviewer"]["harnesses"] == "bad"
    set_reviewer_options(tmp_path, harness="recovered", model="r1", effort="low")
    recovered = load_quality(tmp_path)["reviewer"]
    assert recovered["helper_model"] == "keep"
    assert recovered["harnesses"]["recovered"] == {"model": "r1", "effort": "low"}
