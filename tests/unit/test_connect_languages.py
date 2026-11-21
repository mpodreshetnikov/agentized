"""Oracles for connect_languages (full-cover). Never use DEFAULT_CONTEXT."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentized.connect_languages import ConnectRefused, refuse_incomplete_languages
from agentized.languages import DEFAULT_EXCLUDE_GLOBS
from agentized.paths import DEFAULT_CONTEXT
from agentized.quality import load_quality, save_quality

CTX = "dogfood-ctx-not-default"
assert CTX != DEFAULT_CONTEXT


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
    details = {"ok": False, "unsupported": ["go"]}
    exc = ConnectRefused("nope", details=details)
    assert (str(exc), exc.message, exc.details is details) == ("nope", "nope", True)
    bare = ConnectRefused("x")
    assert bare.details == {} and bare.details is not None


def test_refuse_nondefault_context_gates(tmp_path: Path):
    (tmp_path / "x.go").write_text("package main\n", encoding="utf-8")
    with pytest.raises(ConnectRefused) as ei:
        refuse_incomplete_languages(tmp_path, CTX)
    assert ei.value.details.get("unsupported") == ["go"]
    assert ei.value.message == ei.value.details["message"]

    (tmp_path / CTX).mkdir()
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "x.go").unlink()
    bad = _cfg()
    bad["modules"] = [{"id": "r", "source": ["."]}]
    save_quality(tmp_path, bad, context_rel=CTX)
    with pytest.raises(ConnectRefused) as ei2:
        refuse_incomplete_languages(tmp_path, CTX)
    assert ei2.value.details.get("ok") is False
    assert "python" in (ei2.value.details.get("missing_gates") or {})

    save_quality(tmp_path, _cfg(), context_rel=CTX)
    refuse_incomplete_languages(tmp_path, CTX)
    ex = load_quality(tmp_path, CTX)["languages"]["exclude_globs"]
    assert "packages/**" not in ex and "templates/**" not in ex


def test_refuse_forwards_context_and_ok(tmp_path: Path, monkeypatch):
    seen: dict = {}

    def fake_qpath(root, context_rel=DEFAULT_CONTEXT):
        seen["qpath"] = context_rel
        return tmp_path / context_rel / "quality.json"

    def fake_load(root, context_rel=DEFAULT_CONTEXT):
        seen["load"] = context_rel
        return _cfg()

    def fake_check(root, *, context, cfg, require_gates):
        seen["check"] = (context, require_gates, cfg is not None)
        return {"ok": True, "message": "language coverage OK: (none)"}

    monkeypatch.setattr("agentized.quality.quality_path", fake_qpath)
    monkeypatch.setattr("agentized.quality.load_quality", fake_load)
    monkeypatch.setattr("agentized.languages.check_language_coverage", fake_check)
    refuse_incomplete_languages(tmp_path, CTX)
    assert seen["qpath"] == seen["load"] == CTX
    assert seen["check"] == (CTX, False, True)

    payload = {"ok": False, "message": "explicit false", "unsupported": []}
    monkeypatch.setattr(
        "agentized.languages.check_language_coverage",
        lambda root, *, context, cfg, require_gates: payload,
    )
    with pytest.raises(ConnectRefused) as ei:
        refuse_incomplete_languages(tmp_path, CTX)
    assert ei.value.details is payload and ei.value.message == "explicit false"

    monkeypatch.setattr(
        "agentized.languages.check_language_coverage",
        lambda root, *, context, cfg, require_gates: {"message": "no ok"},
    )
    with pytest.raises(ConnectRefused) as ei2:
        refuse_incomplete_languages(tmp_path, CTX)
    assert ei2.value.message == "no ok"


def test_require_gates_tracks_quality_file(tmp_path: Path, monkeypatch):
    calls: list[bool] = []

    def fake(root, *, context, cfg, require_gates):
        calls.append(require_gates)
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr("agentized.languages.check_language_coverage", fake)
    refuse_incomplete_languages(tmp_path, CTX)
    (tmp_path / CTX).mkdir()
    save_quality(tmp_path, _cfg(), context_rel=CTX)
    refuse_incomplete_languages(tmp_path, CTX)
    assert calls == [False, True]
