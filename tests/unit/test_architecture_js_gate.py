from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agentized import architecture_js_gate as gate

# fmt: off


def test_filter_and_architecture_gate(tmp_path: Path, monkeypatch):
    detected = {
        "typescript": ["src/a.ts", "scripts/tool.ts", "packages/app/x.ts"],
        "javascript": ["src/b.js", "tools/probe.js"], "python": ["runtime/x.py"]}
    assert gate.filter_js_project_files(detected, {}) == {
        "typescript": ["src/a.ts"], "javascript": ["src/b.js"]}
    assert gate.filter_js_project_files(detected, {"js_source": "packages/app"}) == {
        "typescript": ["packages/app/x.ts"]}
    assert gate.filter_js_project_files(detected, {"js_source": "src/"})["typescript"] == ["src/a.ts"]
    assert gate.filter_js_project_files({"typescript": ["/src/a.ts"]}, {"js_source": "\\" + "src"}) == {
        "typescript": ["/src/a.ts"]}
    assert gate.filter_js_project_files({"typescript": ["src/a.ts"]}, {"js_source": "src" + "\\"}) == {
        "typescript": ["src/a.ts"]}
    assert gate.filter_js_project_files({"typescript": ["x.ts"]}, {}) == {}
    assert gate.filter_js_project_files({}, {"js_source": "src"}) == {}
    detected = {"typescript": ["src/a.ts"], "javascript": ["src/a.js"]}
    seen: list = []
    sec = {"tools": {"typescript": "dependency-cruiser", "javascript": "eslint-boundaries"}}
    monkeypatch.setattr(
        gate, "run_dependency_cruiser",
        lambda root, section: seen.append(("dc", root, section is sec)) or (0, "ok"))
    monkeypatch.setattr(
        gate, "run_eslint_boundaries",
        lambda root, section: seen.append(("es", root, section is sec)) or (0, "ok"))
    findings, tools = gate.run_js_architecture(tmp_path, sec, detected)
    assert findings == [] and tools == ["eslint-boundaries", "dependency-cruiser"]
    assert seen == [("es", tmp_path, True), ("dc", tmp_path, True)]
    seen.clear()
    assert gate.run_js_architecture(
        tmp_path, {"tools": {"typescript": "dependency-cruiser", "javascript": "dependency-cruiser"}}, detected
    )[1] == ["dependency-cruiser"] and len(seen) == 1
    monkeypatch.setattr(
        gate, "run_dependency_cruiser", lambda root, s: (1, "bad") if root is tmp_path else (0, ""))
    assert gate.run_js_architecture(
        tmp_path, {"tools": {"typescript": "dependency-cruiser"}, "js_config": "custom.cjs"},
        {"typescript": ["src/a.ts"]},
    )[0] == [{"file": "custom.cjs", "kind": "dependency_cruiser", "detail": "bad"}]
    monkeypatch.setattr(gate, "run_dependency_cruiser", lambda root, s: (1, ""))
    assert gate.run_js_architecture(
        tmp_path, {"tools": {"typescript": "dependency-cruiser"}, "js_config": "custom.cjs"},
        {"typescript": ["src/a.ts"]},
    )[0][0]["detail"] == "exit 1"
    miss = lambda lang: {"file": "(architecture)", "kind": "no_architecture_runner",
                         "detail": f"missing architecture.tools.{lang}"}
    assert gate.run_js_architecture(tmp_path, {"tools": {}}, detected)[0] == [
        miss("javascript"), miss("typescript")]
    assert gate.run_js_architecture(
        tmp_path, {"tools": {"typescript": "nope"}}, {"typescript": ["src/a.ts"]}
    ) == ([{"file": "(architecture)", "kind": "unknown_architecture_tool", "detail": "nope"}], ["nope"])
    monkeypatch.setattr(gate, "run_eslint_boundaries", lambda root, s: (2, "eslint-out"))
    assert gate.run_js_architecture(
        tmp_path, {"tools": {"javascript": "eslint-boundaries"}, "eslint_config": "e.js"},
        {"javascript": ["src/a.js"]},
    )[0] == [{"file": "e.js", "kind": "eslint_boundaries", "detail": "eslint-out"}]
    assert gate.run_js_architecture(
        tmp_path, {"tools": {"javascript": "eslint-boundaries"}}, {"javascript": ["src/a.js"]}
    )[0] == [{"file": "eslint", "kind": "eslint_boundaries", "detail": "eslint-out"}]
    assert gate.run_js_architecture(tmp_path, {"tools": {}}, {}) == ([], [])
    fixed = datetime(2020, 1, 2)
    loads: list = []; pys: list = []
    monkeypatch.setattr(gate, "find_repo_root", lambda: Path("/not-used"))
    monkeypatch.setattr(
        gate, "load_quality", lambda root, ctx: loads.append((root, ctx)) or {"architecture": {}})
    monkeypatch.setattr(
        gate, "run_python_architecture", lambda root, **k: pys.append((root, k.get("context"))) or 0)
    assert gate.run_architecture_gate(tmp_path, context="c") == 0
    assert loads[-1] == (tmp_path, "c") and pys[-1] == (tmp_path, "c")
    monkeypatch.setattr(gate, "find_repo_root", lambda: tmp_path)
    assert gate.run_architecture_gate(None, context="c") == 0 and loads[-1][0] is tmp_path
    arch = {"enabled": True, "mode": "warn", "tools": {"typescript": "dependency-cruiser"}}
    py_seen: list = []; det_seen: list = []; js_seen: list = []
    real_py, real_js = gate.run_python_architecture, gate.run_js_architecture
    monkeypatch.setattr(gate, "load_quality", lambda root, ctx: {"architecture": arch})
    monkeypatch.setattr(
        gate, "run_python_architecture",
        lambda root, **k: py_seen.append((root, k.get("context"))) or real_py(root, **k))
    monkeypatch.setattr(
        gate, "detect_languages",
        lambda root, **k: det_seen.append(root) or {"typescript": ["src/a.ts", "scripts/tool.ts"]})
    monkeypatch.setattr(
        gate, "run_js_architecture",
        lambda root, section, detected: js_seen.append((root, section, detected)) or real_js(root, section, detected))
    monkeypatch.setattr(gate, "run_dependency_cruiser", lambda root, s: (0, "ok"))
    assert gate.run_architecture_gate(tmp_path, context="c", now=lambda: fixed) == 0
    assert py_seen[-1] == (tmp_path, "c") and det_seen[-1] is tmp_path
    assert js_seen[-1][0] is tmp_path and js_seen[-1][2] == {"typescript": ["src/a.ts"]}
    path = tmp_path / "reports/architecture/architecture-js-summary.json"
    payload = json.loads(path.read_text())
    assert payload["schemaVersion"] == 1 and payload["generatedAt"] == fixed.isoformat()
    assert payload["detectedLanguages"] == ["typescript"]
    assert payload["mode"] == "warn" and payload["passed"] is True
    assert payload["toolsRun"] == ["dependency-cruiser"] and payload["findings"] == []
    monkeypatch.setattr(gate, "run_dependency_cruiser", lambda root, s: (1, "x"))
    assert gate.run_architecture_gate(tmp_path, context="c", now=lambda: fixed) == 0
    assert json.loads(path.read_text())["passed"] is True
    monkeypatch.setattr(
        gate, "load_quality",
        lambda root, ctx: {"architecture": {"enabled": True, "tools": {"typescript": "dependency-cruiser"}}})
    assert gate.run_architecture_gate(tmp_path, context="c", now=lambda: fixed) == 1
    hard = json.loads(path.read_text())
    assert hard["mode"] == "hard" and hard["passed"] is False
    assert hard["findings"][0]["file"] == ".dependency-cruiser.cjs"
    monkeypatch.setattr(gate, "detect_languages", lambda root, **k: {"javascript": ["scripts/probe.js"]})
    monkeypatch.setattr(
        gate, "load_quality",
        lambda root, ctx: {"architecture": {"enabled": True, "mode": "hard", "tools": {}}})
    assert gate.run_architecture_gate(tmp_path, context="c", now=lambda: fixed) == 0
    skip = json.loads(path.read_text())
    assert skip["passed"] is True and skip["toolsRun"] == [] and skip["findings"] == []
# fmt: on
