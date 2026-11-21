"""Stryker helpers + mutation_js_gate (AGE-34)."""
from __future__ import annotations

import json
from pathlib import Path

from agentized import mutation as mut
from agentized import mutation_js_gate as gate
from agentized import mutation_stryker as ms


def _report(tmp_path: Path, payload: dict, name: str = "mutation.json") -> Path:
    d = tmp_path / "reports" / "mutation"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(payload), encoding="utf-8")
    return d


def test_read_stryker_covered_and_wrapper(tmp_path: Path):
    _report(
        tmp_path,
        {
            "files": {
                "src/a.ts": {
                    "mutants": [
                        {"status": "Killed"},
                        {"status": "Survived"},
                        {"status": "NoCoverage"},
                        {"status": "Timeout"},
                    ]
                }
            }
        },
    )
    stats = ms.read_stryker_covered(tmp_path)
    assert stats == {
        "mutationScoreCovered": 66.67,
        "mutationScore": 50.0,
        "killed": 1,
        "survived": 1,
        "no_tests": 1,
        "timeout": 1,
        "totalMutants": 4,
        "files": ["src/a.ts"],
        "source": "reports/mutation/mutation.json",
    }
    assert ms.read_stryker_covered(tmp_path / "empty") is None
    preferred = tmp_path / "scripts" / "quality" / "run-mutation-js.cjs"
    preferred.parent.mkdir(parents=True)
    preferred.write_text("x\n", encoding="utf-8")
    (tmp_path / "run-mutation-js.cjs").write_text("y\n", encoding="utf-8")
    assert ms.find_stryker_wrapper(tmp_path) == preferred


def test_run_stryker_gate_matrix(tmp_path: Path, monkeypatch):
    assert (
        ms.run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={"break_on_survived": True},
            base="origin/main",
            min_score=100,
            languages=["typescript"],
            write_summary=mut._write_summary,
        )
        == 1
    )
    assert json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())[
        "reasons"
    ] == ["no_stryker_runner"]

    (tmp_path / "run-mutation-js.cjs").write_text("//\n", encoding="utf-8")
    reports = _report(tmp_path, {"files": {"src/a.ts": {"mutants": [{"status": "Killed"}]}}})

    class R0:
        returncode = 0

    calls: dict = {}
    monkeypatch.setattr(
        ms.subprocess,
        "run",
        lambda cmd, **kw: calls.update(cmd=cmd, env=kw.get("env") or {}) or R0(),
    )
    assert (
        ms.run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={"break_on_survived": True},
            base="origin/main",
            min_score=100,
            languages=["typescript"],
            write_summary=mut._write_summary,
        )
        == 0
    )
    assert calls["cmd"][0] == "node"
    assert json.loads((reports / "mutation-summary.json").read_text())["passed"] is True


def test_mutation_js_gate_fail_closed_and_dispatch(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "mutation": {
                "enabled": True,
                "tool": "mutmut",
                "tools": {"python": "mutmut"},
                "min_score_covered": 100,
                "include_globs": [],
            },
            "modules": [{"source": ["src"]}],
        },
    )
    monkeypatch.setattr(gate, "changed_source_files", lambda *a, **k: ["src/service.go"])
    monkeypatch.chdir(tmp_path)
    assert gate.run_mutation(tmp_path) == 1
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["reasons"] == ["no_mutation_runner"]

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "mutation": {
                "enabled": True,
                "tools": {"typescript": "stryker", "python": "mutmut"},
                "min_score_covered": 100,
                "include_globs": [],
            },
            "modules": [{"source": ["src"]}],
        },
    )
    monkeypatch.setattr(gate, "changed_source_files", lambda *a, **k: ["src/util.ts"])
    called: dict = {}

    def fake_stryker(root, **kwargs):
        called.update(kwargs)
        return 0

    monkeypatch.setattr(gate, "run_stryker_gate", fake_stryker)
    monkeypatch.setattr(gate, "run_mutmut", lambda *a, **k: 0)
    assert gate.run_mutation(tmp_path) == 0
    assert called["changed"] == ["src/util.ts"]
    assert called["languages"] == ["typescript"]
