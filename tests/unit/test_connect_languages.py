"""Oracles for connect_languages — under full-cover mutation globs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentized.connect_languages import (
    MANAGED_LANG_EXCLUDES,
    ConnectRefused,
    merge_managed_language_excludes,
    refuse_incomplete_languages,
)
from agentized.quality import save_quality


def _lang_cfg(**kwargs):
    base = {
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
            ".tox/**",
            ".coverage",
            "htmlcov/**",
            "**/*.example",
            "**/*.example.*",
            "**/*.example.cjs",
            "**/*.example.mjs",
        ],
    }
    base.update(kwargs)
    return {
        "version": 1,
        "coverage": {"lines": 80, "branches": 80},
        "modules": [],
        "languages": base,
        "mutation": {"enabled": True, "tools": {"python": "mutmut"}},
        "test_smells": {"enabled": True, "include_globs": ["**/*.py"]},
        "architecture": {
            "enabled": True,
            "tools": {"python": "import-linter"},
            "config": ".importlinter",
        },
    }


def test_managed_excludes_constant():
    assert MANAGED_LANG_EXCLUDES == ("packages/**", "templates/**")


def test_connect_refused_details():
    exc = ConnectRefused("nope", details={"ok": False, "unsupported": ["go"]})
    assert str(exc) == "nope"
    assert exc.message == "nope"
    assert exc.details == {"ok": False, "unsupported": ["go"]}
    bare = ConnectRefused("x")
    assert bare.details == {}


def test_refuse_without_quality_json(tmp_path: Path):
    (tmp_path / "x.go").write_text("package main\n", encoding="utf-8")
    # No quality.json → require_gates=False; still refuses unsupported.
    with pytest.raises(ConnectRefused) as ei:
        refuse_incomplete_languages(tmp_path, "context")
    assert ei.value.details.get("ok") is False
    assert "go" in (ei.value.details.get("unsupported") or [])


def test_refuse_ok_python_only(tmp_path: Path):
    ctx = "context"
    (tmp_path / ctx).mkdir()
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    cfg = _lang_cfg()
    cfg["modules"] = [
        {
            "id": "r",
            "source": ["."],
            "test_command": "pytest",
            "coverage_lcov": "c.lcov",
            "coverage_json": "c.json",
        }
    ]
    cfg["mutation"] = {
        "enabled": True,
        "tools": {"python": "mutmut"},
        "include_globs": ["**/*.py"],
    }
    save_quality(tmp_path, cfg, context_rel=ctx)
    refuse_incomplete_languages(tmp_path, ctx)  # no raise


def test_merge_managed_excludes(tmp_path: Path):
    ctx = "context"
    (tmp_path / ctx).mkdir()
    save_quality(tmp_path, _lang_cfg(), context_rel=ctx)
    data = merge_managed_language_excludes(tmp_path, ctx)
    ex = data["languages"]["exclude_globs"]
    assert "packages/**" in ex and "templates/**" in ex
    # idempotent
    data2 = merge_managed_language_excludes(tmp_path, ctx)
    assert data2["languages"]["exclude_globs"].count("packages/**") == 1


def test_merge_creates_languages_section(tmp_path: Path):
    ctx = "context"
    (tmp_path / ctx).mkdir()
    cfg = _lang_cfg()
    del cfg["languages"]
    save_quality(tmp_path, cfg, context_rel=ctx)
    data = merge_managed_language_excludes(tmp_path, ctx)
    assert data["languages"]["supported"] == ["python", "javascript", "typescript"]
    assert "packages/**" in data["languages"]["exclude_globs"]
