from __future__ import annotations
import json
from pathlib import Path
from agentized import mutation_js_gate as gate


def test_run_mutation_paths(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    monkeypatch.chdir(tmp_path)
    loads: list = []
    mutmuts: list = []
    monkeypatch.setattr(gate, "find_repo_root", lambda: Path("/not-used"))
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda root, ctx: loads.append((root, ctx)) or {"mutation": {"enabled": False}},
    )
    monkeypatch.setattr(
        gate, "run_mutmut", lambda root, **k: mutmuts.append((root, k.get("context"))) or 0
    )
    assert gate.run_mutation(tmp_path, context="ctx-a") == 0
    assert loads[-1] == (tmp_path, "ctx-a") and mutmuts[-1] == (tmp_path, "ctx-a")
    monkeypatch.setattr(gate, "find_repo_root", lambda: tmp_path)
    assert gate.run_mutation(None, context="ctx-a") == 0
    assert loads[-1][0] is tmp_path
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    bases: list = []

    def changed(root, base, prefixes):
        bases.append((root, base, list(prefixes)))
        return ["src/a.ts", "src/b.go", "outside/x.ts"]

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda root, ctx: {
            "mutation": {
                "enabled": True,
                "include_globs": ["src/**"],
                "base_ref": "origin/custom",
                "tools": {"python": "mutmut"},
            },
            "modules": [{"source": ["src", "pkg\\lib"]}],
        },
    )
    monkeypatch.setattr(gate, "changed_source_files", changed)
    assert gate.run_mutation(tmp_path) == 1
    assert bases[-1] == (tmp_path, "origin/custom", ["src", "pkg/lib"])
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary == {
        "schemaVersion": 1,
        "mode": "incremental",
        "base": "origin/custom",
        "gate": "hard",
        "passed": False,
        "reasons": ["no_mutation_runner"],
        "missingRunners": ["typescript:1", "unknown:1"],
        "changedFiles": ["src/a.ts", "src/b.go"],
    }
    monkeypatch.setenv("MUTATION_BASE", "origin/feature")
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda root, ctx: {
            "mutation": {
                "enabled": True,
                "include_globs": [],
                "min_score_covered": 88,
                "tools": {"typescript": "stryker", "javascript": "stryker", "python": "mutmut"},
            },
            "modules": [],
        },
    )
    monkeypatch.setattr(
        gate,
        "changed_source_files",
        lambda root, base, prefixes: (
            ["runtime/agentized/x.py", "src/a.ts", "src/b.js"]
            if prefixes == ["runtime/agentized"] and base == "origin/feature"
            else []
        ),
    )
    seen: dict = {}

    def fake_stryker(root, **kw):
        assert root is tmp_path
        assert kw.get("mut") is not None
        assert callable(kw.get("write_summary"))
        seen.update(kw)
        return 0

    monkeypatch.setattr(gate, "run_stryker_gate", fake_stryker)
    mutmuts.clear()
    assert gate.run_mutation(tmp_path) == 0
    assert seen["base"] == "origin/feature"
    assert seen["min_score"] == 88.0
    assert seen["changed"] == ["src/a.ts", "src/b.js"]
    assert seen["languages"] == ["javascript", "typescript"]
    assert mutmuts[-1] == (tmp_path, gate.DEFAULT_CONTEXT)
    monkeypatch.setattr(gate, "run_stryker_gate", lambda *a, **k: 5)
    assert gate.run_mutation(tmp_path) == 5
    monkeypatch.setattr(gate, "changed_source_files", lambda *a, **k: ["runtime/agentized/x.py"])
    monkeypatch.setattr(gate, "run_stryker_gate", fake_stryker)
    n = len(mutmuts)
    assert gate.run_mutation(tmp_path, context="ctx-final") == 0
    assert mutmuts[n:] == [(tmp_path, "ctx-final")]
