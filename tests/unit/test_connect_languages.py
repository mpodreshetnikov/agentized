"""Oracles for connect_languages — under full-cover mutation globs."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentized.connect_languages import ConnectRefused, refuse_incomplete_languages
from agentized.languages import DEFAULT_EXCLUDE_GLOBS
from agentized.quality import load_quality, save_quality


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


def test_connect_refused():
    exc = ConnectRefused("nope", details={"ok": False, "unsupported": ["go"]})
    assert (str(exc), exc.message, exc.details) == (
        "nope",
        "nope",
        {"ok": False, "unsupported": ["go"]},
    )
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
    # Defaults never inject dogfood-only packages/** / templates/**
    ex = load_quality(tmp_path, ctx)["languages"]["exclude_globs"]
    assert "packages/**" not in ex and "templates/**" not in ex


def test_refuse_forwards_kwargs_and_missing_ok(tmp_path: Path, monkeypatch):
    seen: dict = {}

    def fake_check(root, *, context, cfg, require_gates):
        seen.update(context=context, cfg=cfg, require_gates=require_gates)
        return {"message": "ok"}  # no ok → fail-closed refuse

    monkeypatch.setattr("agentized.languages.check_language_coverage", fake_check)
    with pytest.raises(ConnectRefused):
        refuse_incomplete_languages(tmp_path, "myctx")
    assert seen["context"] == "myctx"
    assert seen["cfg"] is not None
    assert seen["require_gates"] is False

    def fake_ok(root, *, context, cfg, require_gates):
        return {"ok": True, "message": "language coverage OK: (none)"}

    monkeypatch.setattr("agentized.languages.check_language_coverage", fake_ok)
    refuse_incomplete_languages(tmp_path, "myctx")
