"""Exact oracles for languages_text — kills string/case mutmut survivors."""
from __future__ import annotations

from agentized import languages_text as t


def test_keys_and_markers():
    assert t.KEY_SUPPORTED == "supported"
    assert t.KEY_EXCLUDE_GLOBS == "exclude_globs"
    assert t.ARCH_DEP_CRUISER == "dependency-cruiser"
    assert t.ARCH_BUILTIN == "builtin"
    assert t.MUT_ENABLED == "enabled"
    assert t.MUT_INCLUDE == "include_globs"
    assert t.COV_LCOV == "coverage_lcov"
    assert t.COV_JSON == "coverage_json"
    assert t.JS_CONFIG == "js_config"
    assert t.ARCH_CONFIG == "config"
    assert t.TEST_COMMAND == "test_command"
    assert t.EXCLUDE_GLOBS_REQUIRED == (
        "exclude_globs is required (empty/missing refused by check_language_coverage)"
    )


def test_result_and_messages_exact():
    assert t.result(ok=True, message="m") == {
        "ok": True,
        "detected": {},
        "unsupported": [],
        "missing_gates": {},
        "message": "m",
        "skipped": False,
    }
    assert t.msg_detect_false() == (
        "agentized: REFUSED — languages.detect=false is not allowed "
        "(fail-closed language coverage; AGE-24)."
    )
    assert t.msg_supported_missing() == (
        "agentized: REFUSED — languages.supported is missing or empty "
        "(fail-closed; no silent defaults)."
    )
    assert t.msg_exclude_missing() == (
        "agentized: REFUSED — languages.exclude_globs is missing or empty "
        "(fail-closed; no silent defaults)."
    )
    assert t.msg_ok({"python": ["a.py"], "go": ["b.go"]}) == "language coverage OK: go, python"
    assert t.msg_ok({}) == "language coverage OK: (none)"
    assert t.msg_illegal_supported(["go"], ["python"], ["mutation"]) == (
        "agentized: REFUSED — languages.supported contains language(s) "
        "without a gate suite: go. "
        "Allowed: python. "
        "Required gates: mutation."
    )
    assert t.msg_coverage_incomplete(
        ["go"],
        {"python": ["mutation"]},
        {"go": ["x.go"], "python": ["a.py"]},
        ("coverage", "mutation"),
    ) == (
        "agentized: REFUSED — language coverage incomplete: "
        "go unsupported (e.g. x.go); "
        "python missing gates [mutation] (e.g. a.py; need coverage, mutation). "
        "Configure modules/test_command/coverage, mutation.tools, "
        "architecture.tools+config, test_smells include_globs per language, "
        "and JS/TS AGE-34 runners when those languages are present."
    )
    assert "e.g. ?" in t.msg_coverage_incomplete(["rust"], {}, {}, ("coverage",))
