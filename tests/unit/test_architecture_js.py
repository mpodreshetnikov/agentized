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

    seen: dict = {}
    monkeypatch.setattr(ajs.shutil, "which", lambda n: "/usr/bin/npx")
    monkeypatch.setattr(
        ajs.subprocess,
        "run",
        lambda cmd, **k: seen.update(cmd=list(cmd)) or R(),
    )
    assert ajs.run_dependency_cruiser(
        tmp_path, {"js_config": ".dependency-cruiser.cjs", "js_source": "src"}
    ) == (0, "ok")
    assert seen["cmd"] == [
        "/usr/bin/npx",
        "--yes",
        "dependency-cruiser",
        "--config",
        str(tmp_path / ".dependency-cruiser.cjs"),
        "src",
    ]
    assert ajs.run_eslint_boundaries(tmp_path, {}) == (0, "ok")
    assert ajs.run_eslint_boundaries(tmp_path, {"eslint_config": "eslint.config.js"})[0] == 0
    assert seen["cmd"] == [
        "/usr/bin/npx",
        "--yes",
        "eslint",
        ".",
        "--config",
        "eslint.config.js",
    ]
    monkeypatch.setattr(ajs.shutil, "which", lambda n: None)
    assert ajs.run_dependency_cruiser(tmp_path, {"js_config": ".dependency-cruiser.cjs"}) == (
        1,
        "npx-missing",
    )
    assert ajs.run_eslint_boundaries(tmp_path, {}) == (1, "npx-missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ajs.run_dependency_cruiser(empty, {"js_config": ".dependency-cruiser.cjs"}) == (
        1,
        "missing:.dependency-cruiser.cjs",
    )
    monkeypatch.setattr(ajs.shutil, "which", lambda n: "/bin/npx")
    monkeypatch.setattr(
        ajs.subprocess,
        "run",
        lambda cmd, **k: type("R", (), {"returncode": 2, "stdout": "", "stderr": "bad"})(),
    )
    assert ajs.run_eslint_boundaries(tmp_path, {"eslint_boundaries_command": ["eslint"]}) == (
        2,
        "bad",
    )


def test_architecture_js_gate_matrix(tmp_path: Path, monkeypatch):
    from datetime import datetime, timezone

    fixed = datetime(2020, 1, 2, tzinfo=timezone.utc)
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.ts").write_text("export {}\n", encoding="utf-8")
    (src / "app.js").write_text("export {}\n", encoding="utf-8")
    monkeypatch.setattr(gate, "run_python_architecture", lambda *a, **k: 0)

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {"architecture": {"enabled": False}},
    )
    assert gate.run_architecture_gate(tmp_path) == 0

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "languages": {"exclude_globs": []},
            "architecture": {"enabled": True, "mode": "hard", "tools": {}, "tool": "builtin"},
        },
    )
    assert gate.run_architecture_gate(tmp_path, now=lambda tz: fixed) == 1
    summary = json.loads(
        (tmp_path / "reports/architecture/architecture-js-summary.json").read_text()
    )
    assert summary["generatedAt"] == fixed.isoformat()
    assert summary["passed"] is False
    assert {f["kind"] for f in summary["findings"]} == {"no_architecture_runner"}

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "languages": {"exclude_globs": []},
            "architecture": {
                "enabled": True,
                "mode": "hard",
                "tools": {
                    "typescript": "dependency-cruiser",
                    "javascript": "dependency-cruiser",
                },
                "js_config": ".dependency-cruiser.cjs",
            },
        },
    )
    monkeypatch.setattr(gate, "run_dependency_cruiser", lambda root, section: (0, "ok"))
    assert gate.run_architecture_gate(tmp_path, now=lambda tz: fixed) == 0
    summary = json.loads(
        (tmp_path / "reports/architecture/architecture-js-summary.json").read_text()
    )
    assert summary["toolsRun"] == ["dependency-cruiser"]
    assert summary["passed"] is True

    monkeypatch.setattr(gate, "run_dependency_cruiser", lambda root, section: (1, "boom"))
    assert gate.run_architecture_gate(tmp_path, now=lambda tz: fixed) == 1

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "languages": {"exclude_globs": []},
            "architecture": {
                "enabled": True,
                "mode": "warn",
                "tools": {"typescript": "eslint-boundaries"},
            },
        },
    )
    monkeypatch.setattr(gate, "run_eslint_boundaries", lambda root, section: (1, "x"))
    assert gate.run_architecture_gate(tmp_path, now=lambda tz: fixed) == 0
    summary = json.loads(
        (tmp_path / "reports/architecture/architecture-js-summary.json").read_text()
    )
    assert summary["passed"] is True

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "languages": {"exclude_globs": []},
            "architecture": {
                "enabled": True,
                "mode": "hard",
                "tools": {"typescript": "weird-tool"},
            },
        },
    )
    assert gate.run_architecture_gate(tmp_path, now=lambda tz: fixed) == 1
    summary = json.loads(
        (tmp_path / "reports/architecture/architecture-js-summary.json").read_text()
    )
    kinds = {f["kind"] for f in summary["findings"]}
    assert "unknown_architecture_tool" in kinds
    assert "no_architecture_runner" in kinds

    monkeypatch.setattr(gate, "run_python_architecture", lambda *a, **k: 3)
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "languages": {"exclude_globs": []},
            "architecture": {
                "enabled": True,
                "mode": "hard",
                "tools": {
                    "typescript": "dependency-cruiser",
                    "javascript": "dependency-cruiser",
                },
            },
        },
    )
    monkeypatch.setattr(gate, "run_dependency_cruiser", lambda root, section: (0, "ok"))
    assert gate.run_architecture_gate(tmp_path, now=lambda tz: fixed) == 3
