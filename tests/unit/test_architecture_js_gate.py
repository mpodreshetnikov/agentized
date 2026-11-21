"""Direct architecture_js_gate coverage (mutmut dependency map)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agentized import architecture_js_gate as gate


def test_run_js_architecture_branches(tmp_path: Path, monkeypatch):
    detected = {"typescript": ["a.ts"], "javascript": ["a.js"]}
    seen: list = []
    monkeypatch.setattr(
        gate,
        "run_dependency_cruiser",
        lambda root, section: seen.append(("dc", root)) or (0, "ok"),
    )
    monkeypatch.setattr(
        gate,
        "run_eslint_boundaries",
        lambda root, section: seen.append(("es", root)) or (0, "ok"),
    )
    findings, tools = gate.run_js_architecture(
        tmp_path,
        {"tools": {"typescript": "dependency-cruiser", "javascript": "eslint-boundaries"}},
        detected,
    )
    assert findings == [] and tools == ["eslint-boundaries", "dependency-cruiser"]
    assert seen == [("es", tmp_path), ("dc", tmp_path)]
    seen.clear()
    assert (
        gate.run_js_architecture(
            tmp_path,
            {"tools": {"typescript": "dependency-cruiser", "javascript": "dependency-cruiser"}},
            detected,
        )[1]
        == ["dependency-cruiser"]
    )
    assert len(seen) == 1
    def dc_bad(root, s):
        assert s is not None and root is tmp_path
        return (1, "bad")
    monkeypatch.setattr(gate, "run_dependency_cruiser", dc_bad)
    assert gate.run_js_architecture(
        tmp_path,
        {"tools": {"typescript": "dependency-cruiser"}, "js_config": "custom.cjs"},
        {"typescript": ["a.ts"]},
    )[0] == [{"file": "custom.cjs", "kind": "dependency_cruiser", "detail": "bad"}]
    monkeypatch.setattr(gate, "run_dependency_cruiser", lambda root, s: (1, ""))
    assert gate.run_js_architecture(
        tmp_path,
        {"tools": {"typescript": "dependency-cruiser"}, "js_config": "custom.cjs"},
        {"typescript": ["a.ts"]},
    )[0][0]["detail"] == "exit 1"
    assert gate.run_js_architecture(tmp_path, {"tools": {}}, detected)[0] == [
        {
            "file": "(architecture)",
            "kind": "no_architecture_runner",
            "detail": "missing architecture.tools.javascript",
        },
        {
            "file": "(architecture)",
            "kind": "no_architecture_runner",
            "detail": "missing architecture.tools.typescript",
        },
    ]
    assert gate.run_js_architecture(
        tmp_path, {"tools": {"typescript": "nope"}}, {"typescript": ["a.ts"]}
    ) == (
        [{"file": "(architecture)", "kind": "unknown_architecture_tool", "detail": "nope"}],
        ["nope"],
    )
    def es_bad(root, s):
        assert s is not None
        return (2, "eslint-out")
    monkeypatch.setattr(gate, "run_eslint_boundaries", es_bad)
    assert gate.run_js_architecture(
        tmp_path,
        {"tools": {"javascript": "eslint-boundaries"}, "eslint_config": "e.js"},
        {"javascript": ["a.js"]},
    )[0] == [{"file": "e.js", "kind": "eslint_boundaries", "detail": "eslint-out"}]
    assert gate.run_js_architecture(
        tmp_path, {"tools": {"javascript": "eslint-boundaries"}}, {"javascript": ["a.js"]}
    )[0] == [{"file": "eslint", "kind": "eslint_boundaries", "detail": "eslint-out"}]
    assert gate.run_js_architecture(tmp_path, {"tools": {}}, {}) == ([], [])


def test_architecture_gate_payload_and_args(tmp_path: Path, monkeypatch):
    fixed = datetime(2020, 1, 2)
    loads: list = []
    pys: list = []

    def load(root, ctx):
        loads.append((root, ctx))
        return {"architecture": {}}

    def py(root, **k):
        pys.append((root, k.get("context")))
        return 0

    monkeypatch.setattr(gate, "find_repo_root", lambda: Path("/not-used"))
    monkeypatch.setattr(gate, "load_quality", load)
    monkeypatch.setattr(gate, "run_python_architecture", py)
    assert gate.run_architecture_gate(tmp_path, context="c") == 0
    assert loads[-1] == (tmp_path, "c") and pys[-1] == (tmp_path, "c")
    monkeypatch.setattr(gate, "find_repo_root", lambda: tmp_path)
    assert gate.run_architecture_gate(None, context="c") == 0
    assert loads[-1][0] is tmp_path

    def load_on(root, ctx):
        assert root is tmp_path and ctx == "c"
        return {
            "architecture": {
                "enabled": True,
                "mode": "warn",
                "tools": {"typescript": "dependency-cruiser"},
            }
        }

    def py_on(root, **k):
        assert root is tmp_path and k.get("context") == "c"
        return 0

    def detect(root, **k):
        assert root is tmp_path
        return {"typescript": ["a.ts"]}

    def dc(root, s):
        assert root is tmp_path
        return (0, "ok")

    monkeypatch.setattr(gate, "load_quality", load_on)
    monkeypatch.setattr(gate, "run_python_architecture", py_on)
    monkeypatch.setattr(gate, "detect_languages", detect)
    monkeypatch.setattr(gate, "run_dependency_cruiser", dc)
    assert gate.run_architecture_gate(tmp_path, context="c", now=lambda: fixed) == 0
    payload = json.loads((tmp_path / "reports/architecture/architecture-js-summary.json").read_text())
    assert payload["schemaVersion"] == 1 and payload["generatedAt"] == fixed.isoformat()
    assert payload["detectedLanguages"] == ["typescript"]
    assert payload["mode"] == "warn" and payload["passed"] is True
    assert payload["toolsRun"] == ["dependency-cruiser"] and payload["findings"] == []
    monkeypatch.setattr(gate, "run_dependency_cruiser", lambda root, s: (1, "x"))
    assert gate.run_architecture_gate(tmp_path, context="c", now=lambda: fixed) == 0
    warn_fail = json.loads((tmp_path / "reports/architecture/architecture-js-summary.json").read_text())
    assert warn_fail["passed"] is True and warn_fail["findings"]

    def dc_fail(root, s):
        assert root is tmp_path
        return (1, "x")

    def py_fail(root, **k):
        assert root is tmp_path
        return 0

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda root, ctx: {
            "architecture": {
                "enabled": True,
                "tools": {"typescript": "dependency-cruiser"},
            }
        },
    )
    monkeypatch.setattr(gate, "run_python_architecture", py_fail)
    monkeypatch.setattr(gate, "run_dependency_cruiser", dc_fail)
    assert gate.run_architecture_gate(tmp_path, context="c", now=lambda: fixed) == 1
    hard = json.loads((tmp_path / "reports/architecture/architecture-js-summary.json").read_text())
    assert hard["mode"] == "hard" and hard["passed"] is False
    assert hard["findings"][0]["file"] == ".dependency-cruiser.cjs"
