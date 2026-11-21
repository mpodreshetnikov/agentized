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


def test_read_stryker_covered_matrix(tmp_path: Path):
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
                        {"status": "Other"},
                    ]
                }
            }
        },
    )
    assert ms.read_stryker_covered(tmp_path) == {
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
    assert ms.read_stryker_covered(tmp_path / "missing") is None
    _report(
        tmp_path,
        {
            "metrics": {"mutationScoreOfCoveredCode": 100, "mutationScore": 90},
            "files": {"a.ts": {"mutants": [{"status": "Killed"}]}},
        },
        name="mutation-result.json",
    )
    (tmp_path / "reports/mutation/mutation.json").unlink()
    got = ms.read_stryker_covered(tmp_path)
    assert got is not None
    assert (got["mutationScoreCovered"], got["mutationScore"]) == (100, 90)
    preferred = tmp_path / "scripts" / "quality" / "run-mutation-js.cjs"
    preferred.parent.mkdir(parents=True)
    preferred.write_text("x\n", encoding="utf-8")
    (tmp_path / "run-mutation-js.cjs").write_text("y\n", encoding="utf-8")
    assert ms.find_stryker_wrapper(tmp_path) == preferred
    assert ms.find_stryker_wrapper(tmp_path / "empty") is None


def test_run_stryker_gate_wrapper_only(tmp_path: Path, monkeypatch):
    assert (
        ms.run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={},
            base="origin/main",
            min_score=100,
            languages=["typescript"],
            write_summary=mut._write_summary,
        )
        == 1
    )
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary == {
        "schemaVersion": 1,
        "mode": "incremental",
        "base": "origin/main",
        "gate": "hard",
        "tool": "stryker",
        "passed": False,
        "reasons": ["no_stryker_runner"],
        "changedFiles": ["src/a.ts"],
        "languages": ["typescript"],
        "minScoreCovered": 100,
    }
    (tmp_path / "run-mutation-js.cjs").write_text("//\n", encoding="utf-8")

    class R:
        returncode = 0

    calls: dict = {}
    monkeypatch.setattr(
        ms.subprocess,
        "run",
        lambda cmd, **kw: calls.update(cmd=cmd, env=kw.get("env") or {}) or R(),
    )
    assert (
        ms.run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={"x": 1},
            base="origin/main",
            min_score=100,
            languages=["typescript"],
            write_summary=mut._write_summary,
        )
        == 0
    )
    assert calls["cmd"] == ["node", str(tmp_path / "run-mutation-js.cjs")]
    assert calls["env"]["MUTATION_MIN_SCORE_COVERED"] == "100"
    assert calls["env"]["MUTATION_BASE"] == "origin/main"
    assert calls["env"]["STRYKER_BASE"] == "origin/main"

    class R7:
        returncode = 7

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: R7())
    assert (
        ms.run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={},
            base="b",
            min_score=80,
            languages=["javascript"],
            write_summary=mut._write_summary,
        )
        == 7
    )


def test_mutation_js_gate_paths(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    monkeypatch.setattr(gate, "run_mutmut", lambda *a, **k: 0)
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {"mutation": {"enabled": False}, "modules": []},
    )
    assert gate.run_mutation(tmp_path) == 0

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "mutation": {
                "enabled": True,
                "tools": {"python": "mutmut"},
                "min_score_covered": 100,
                "include_globs": ["src/*"],
                "base_ref": "origin/main",
            },
            "modules": [{"source": ["src"]}],
        },
    )
    monkeypatch.setattr(
        gate,
        "changed_source_files",
        lambda *a, **k: ["src/a.ts", "src/skip.go", "other/x.ts"],
    )
    monkeypatch.chdir(tmp_path)
    assert gate.run_mutation(tmp_path) == 1
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["reasons"] == ["no_mutation_runner"]
    assert summary["missingRunners"] == ["typescript:1", "unknown:1"]

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
    monkeypatch.setattr(
        gate,
        "run_stryker_gate",
        lambda root, **kw: called.update(kw) or 0,
    )
    assert gate.run_mutation(tmp_path) == 0
    assert called["changed"] == ["src/util.ts"]
    assert called["languages"] == ["typescript"]
    monkeypatch.setattr(gate, "run_stryker_gate", lambda *a, **k: 9)
    assert gate.run_mutation(tmp_path) == 9
