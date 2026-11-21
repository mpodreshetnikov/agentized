"""Oracles for connect_languages — under full-cover mutation globs."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentized.connect_languages import (
    MANAGED_LANG_EXCLUDES,
    ConnectRefused,
    merge_managed_language_excludes,
    refuse_incomplete_languages,
)
from agentized.languages import DEFAULT_EXCLUDE_GLOBS
from agentized.quality import save_quality


def _cfg(**lang_kw):
    lang = {
        "supported": ["python", "javascript", "typescript"],
        "exclude_globs": list(DEFAULT_EXCLUDE_GLOBS),
    }
    lang.update(lang_kw)
    return {
        "version": 1,
        "coverage": {"lines": 80, "branches": 80},
        "modules": [
            {
                "id": "r",
                "source": ["."],
                "test_command": "pytest",
                "coverage_lcov": "c.lcov",
                "coverage_json": "c.json",
            }
        ],
        "languages": lang,
        "mutation": {
            "enabled": True,
            "tools": {"python": "mutmut"},
            "include_globs": ["**/*.py"],
        },
        "test_smells": {"enabled": True, "include_globs": ["**/*.py"]},
        "architecture": {
            "enabled": True,
            "tools": {"python": "import-linter"},
            "config": ".importlinter",
        },
    }


def test_constants_and_refused():
    assert MANAGED_LANG_EXCLUDES == ("packages/**", "templates/**")
    exc = ConnectRefused("nope", details={"ok": False, "unsupported": ["go"]})
    assert str(exc) == "nope" and exc.message == "nope"
    assert exc.details == {"ok": False, "unsupported": ["go"]}
    assert ConnectRefused("x").details == {}


def test_refuse_unsupported_and_ok(tmp_path: Path):
    (tmp_path / "x.go").write_text("package main\n", encoding="utf-8")
    with pytest.raises(ConnectRefused) as ei:
        refuse_incomplete_languages(tmp_path, "context")
    assert ei.value.details.get("ok") is False
    assert "go" in (ei.value.details.get("unsupported") or [])

    ctx = "context"
    (tmp_path / ctx).mkdir()
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "x.go").unlink()
    save_quality(tmp_path, _cfg(), context_rel=ctx)
    refuse_incomplete_languages(tmp_path, ctx)


def test_merge_managed_excludes(tmp_path: Path):
    ctx = "context"
    (tmp_path / ctx).mkdir()
    save_quality(tmp_path, _cfg(), context_rel=ctx)
    data = merge_managed_language_excludes(tmp_path, ctx)
    ex = data["languages"]["exclude_globs"]
    assert "packages/**" in ex and "templates/**" in ex
    assert merge_managed_language_excludes(tmp_path, ctx)["languages"]["exclude_globs"].count(
        "packages/**"
    ) == 1

    cfg = _cfg()
    del cfg["languages"]
    save_quality(tmp_path, cfg, context_rel=ctx)
    data = merge_managed_language_excludes(tmp_path, ctx)
    assert data["languages"]["supported"] == ["python", "javascript", "typescript"]
    assert "packages/**" in data["languages"]["exclude_globs"]
