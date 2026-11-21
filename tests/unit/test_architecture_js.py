"""JS/TS architecture runners + gate (AGE-34)."""
from __future__ import annotations

import json
from pathlib import Path

from agentized import architecture_js as ajs
from agentized import architecture_js_gate as gate


def test_dependency_cruiser_and_eslint(tmp_path: Path, monkeypatch):
    (tmp_path / ".dependency-cruiser.cjs").write_text("module.exports={}\n", encoding="utf-8")

    class R:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(ajs.shutil, "which", lambda n: "/usr/bin/npx")
    monkeypatch.setattr(ajs.subprocess, "run", lambda *a, **k: R())
    assert ajs.run_dependency_cruiser(
        tmp_path, {"js_config": ".dependency-cruiser.cjs", "js_source": "src"}
    ) == (0, "ok")
    assert ajs.run_eslint_boundaries(tmp_path, {})[0] == 0
    seen: dict = {}
    monkeypatch.setattr(
        ajs.subprocess,
        "run",
        lambda cmd, **k: seen.update(cmd=cmd)
        or type("R", (), {"returncode": 0, "stdout": "", "stderr": "clean"})(),
    )
    rc, out = ajs.run_eslint_boundaries(tmp_path, {"eslint_config": "eslint.config.js"})
    assert (rc, out) == (0, "clean")
    assert seen["cmd"][-2:] == ["--config", "eslint.config.js"]
    monkeypatch.setattr(ajs.shutil, "which", lambda n: None)
    assert ajs.run_dependency_cruiser(tmp_path, {"js_config": ".dependency-cruiser.cjs"})[0] == 1
    assert ajs.run_eslint_boundaries(tmp_path, {})[0] == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ajs.run_dependency_cruiser(empty, {"js_config": ".dependency-cruiser.cjs"})[0] == 1


def test_architecture_js_gate_missing_and_pass(tmp_path: Path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.ts").write_text("export {}\n", encoding="utf-8")
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "languages": {"exclude_globs": []},
            "architecture": {"enabled": True, "mode": "hard", "tools": {}, "tool": "builtin"},
        },
    )
    monkeypatch.setattr(gate, "run_python_architecture", lambda *a, **k: 0)
    assert gate.run_architecture_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports/architecture/architecture-js-summary.json").read_text()
    )
    assert any(f["kind"] == "no_architecture_runner" for f in summary["findings"])

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "languages": {"exclude_globs": []},
            "architecture": {
                "enabled": True,
                "mode": "hard",
                "tools": {"typescript": "dependency-cruiser"},
                "js_config": ".dependency-cruiser.cjs",
            },
        },
    )
    monkeypatch.setattr(gate, "run_dependency_cruiser", lambda root, section: (0, "ok"))
    assert gate.run_architecture_gate(tmp_path) == 0
