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
from agentized.quality import load_quality, save_quality


def _cfg(**lang_kw):
    lang = {"supported": ["python", "javascript", "typescript"], "exclude_globs": list(DEFAULT_EXCLUDE_GLOBS)}
    lang.update(lang_kw)
    return {
        "version": 1, "coverage": {"lines": 80, "branches": 80},
        "modules": [{"id": "r", "source": ["."], "test_command": "pytest", "coverage_lcov": "c.lcov", "coverage_json": "c.json"}],
        "languages": lang,
        "mutation": {"enabled": True, "tools": {"python": "mutmut"}, "include_globs": ["**/*.py"]},
        "test_smells": {"enabled": True, "include_globs": ["**/*.py"]},
        "architecture": {"enabled": True, "tools": {"python": "import-linter"}, "config": ".importlinter"},
    }



def test_constants_and_refused():
    assert MANAGED_LANG_EXCLUDES == ("packages/**", "templates/**")
    exc = ConnectRefused("nope", details={"ok": False, "unsupported": ["go"]})
    assert (str(exc), exc.message, exc.details) == ("nope", "nope", {"ok": False, "unsupported": ["go"]})
    assert ConnectRefused("x").details == {}


def test_refuse_uses_context_and_gates(tmp_path: Path):
    (tmp_path / "x.go").write_text("package main\n", encoding="utf-8")
    with pytest.raises(ConnectRefused) as ei:
        refuse_incomplete_languages(tmp_path, "context")
    assert ei.value.details.get("unsupported") == ["go"]
    assert "REFUSED" in ei.value.message

    ctx = "myctx"
    (tmp_path / ctx).mkdir()
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "x.go").unlink()
    bad = _cfg()
    bad["modules"] = [{"id": "r", "source": ["."]}]
    save_quality(tmp_path, bad, context_rel=ctx)
    with pytest.raises(ConnectRefused) as ei2:
        refuse_incomplete_languages(tmp_path, ctx)
    assert ei2.value.details.get("ok") is False
    assert "python" in (ei2.value.details.get("missing_gates") or {})

    save_quality(tmp_path, _cfg(), context_rel=ctx)
    refuse_incomplete_languages(tmp_path, ctx)


def test_merge_preserves_excludes_and_context(tmp_path: Path, monkeypatch):
    ctx = "myctx"
    (tmp_path / ctx).mkdir()
    save_quality(tmp_path, _cfg(), context_rel=ctx)
    before = list(load_quality(tmp_path, ctx)["languages"]["exclude_globs"])
    assert before[0] == "node_modules/**" and "packages/**" not in before
    data = merge_managed_language_excludes(tmp_path, ctx)
    assert data["languages"]["exclude_globs"] == before + ["packages/**", "templates/**"]
    assert data["languages"]["supported"] == ["python", "javascript", "typescript"]
    assert merge_managed_language_excludes(tmp_path, ctx)["languages"]["exclude_globs"] == (
        before + ["packages/**", "templates/**"]
    )

    saved: dict = {}

    def fake_load(root, context_rel):
        assert context_rel == ctx
        return {"languages": ["nope"]}

    def fake_save(root, data, context_rel):
        assert context_rel == ctx
        saved["data"] = data

    monkeypatch.setattr("agentized.quality.load_quality", fake_load)
    monkeypatch.setattr("agentized.quality.save_quality", fake_save)
    out = merge_managed_language_excludes(tmp_path, ctx)
    assert out["languages"]["supported"] == ["python", "javascript", "typescript"]
    assert out["languages"]["exclude_globs"] == ["packages/**", "templates/**"]
    assert saved["data"]["languages"]["exclude_globs"] == ["packages/**", "templates/**"]


def test_refuse_forwards_kwargs(tmp_path: Path, monkeypatch):
    seen: dict = {}

    def fake_check(root, *, context, cfg, require_gates):
        seen.update(context=context, cfg=cfg, require_gates=require_gates)
        return {"message": "ok"}  # no ok key → default True must not raise

    monkeypatch.setattr("agentized.languages.check_language_coverage", fake_check)
    refuse_incomplete_languages(tmp_path, "myctx")
    assert seen == {"context": "myctx", "cfg": seen["cfg"], "require_gates": False}
    assert seen["cfg"] is not None


def test_merge_sets_supported_when_missing(tmp_path: Path, monkeypatch):
    saved: dict = {}

    def fake_load(root, context_rel):
        return {"languages": {"exclude_globs": ["node_modules/**"], "supported": ["python"]}}

    def fake_save(root, data, context_rel):
        saved["data"] = data

    monkeypatch.setattr("agentized.quality.load_quality", fake_load)
    monkeypatch.setattr("agentized.quality.save_quality", fake_save)
    out = merge_managed_language_excludes(tmp_path, "myctx")
    assert out["languages"]["supported"] == ["python"]
    assert out["languages"]["exclude_globs"] == ["node_modules/**", "packages/**", "templates/**"]
