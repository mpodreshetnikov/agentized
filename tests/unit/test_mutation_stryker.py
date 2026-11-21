"""Stryker helpers (AGE-34)."""
from __future__ import annotations

import json
from pathlib import Path

from agentized import mutation as mut
from agentized import mutation_stryker as ms


def _report(tmp_path: Path, payload: dict, name: str = "mutation.json") -> None:
    d = tmp_path / "reports" / "mutation"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(payload))


def test_read_stryker_covered_matrix(tmp_path: Path):
    _report(
        tmp_path,
        {
            "files": {
                "src/a.ts": {
                    "mutants": [
                        {"status": "Killed"},
                        {"status": "Killed"},
                        {"status": "Survived"},
                        {"status": "Survived"},
                        {"status": "NoCoverage"},
                        {"status": "NoCoverage"},
                        {"status": "Timeout"},
                        {"status": "Timeout"},
                        {"status": "Other"},
                    ]
                },
                "src/b.ts": {"mutants": [{"status": "Killed"}]},
            }
        },
    )
    assert ms.read_stryker_covered(tmp_path) == {
        "mutationScoreCovered": 71.43,
        "mutationScore": 55.56,
        "killed": 3,
        "survived": 2,
        "no_tests": 2,
        "timeout": 2,
        "totalMutants": 9,
        "files": ["src/a.ts", "src/b.ts"],
        "source": "reports/mutation/mutation.json",
    }
    assert ms.read_stryker_covered(tmp_path / "missing") is None
    _report(tmp_path, {"files": {"c.ts": {"mutants": [{"status": "Killed"}, {"status": "Survived"}, {"status": "NoCoverage"}]}}})
    got = ms.read_stryker_covered(tmp_path)
    assert (got["mutationScore"], got["mutationScoreCovered"]) == (33.33, 50.0)
    _report(tmp_path, {"files": {}})
    assert ms.read_stryker_covered(tmp_path)["mutationScoreCovered"] is None
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
    assert (got["mutationScoreCovered"], got["mutationScore"]) == (100.0, 100.0)
    preferred = tmp_path / "scripts" / "quality" / "run-mutation-js.cjs"
    preferred.parent.mkdir(parents=True)
    preferred.write_text("x\n")
    (tmp_path / "run-mutation-js.cjs").write_text("y\n")
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
    body = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert set(body) == {
        "schemaVersion", "mode", "base", "gate", "tool", "passed",
        "reasons", "changedFiles", "languages", "minScoreCovered",
    }
    assert body["schemaVersion"] == 1 and body["tool"] == "stryker"
    assert body["reasons"] == ["no_stryker_runner"] and body["passed"] is False
    assert body["gate"] == "hard" and body["mode"] == "incremental"
    (tmp_path / "run-mutation-js.cjs").write_text("//\n")

    class R0:
        returncode = 0

    calls: dict = {}
    monkeypatch.setattr(
        ms.subprocess,
        "run",
        lambda cmd, **kw: calls.update(cmd=cmd, cwd=kw.get("cwd"), env=kw.get("env") or {})
        or R0(),
    )
    assert (
        ms.run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={"x": 1},
            base="origin/main",
            min_score=100.0,
            languages=["typescript"],
            write_summary=mut._write_summary,
        )
        == 0
    )
    assert calls["cmd"] == ["node", str(tmp_path / "run-mutation-js.cjs")]
    assert calls["cwd"] == tmp_path
    assert calls["env"]["MUTATION_BASE"] == "origin/main"
    assert calls["env"]["STRYKER_BASE"] == "origin/main"
    assert calls["env"]["MUTATION_MIN_SCORE_COVERED"] == "100.0"
    assert "MUTATION_BASE" in calls["env"] and "mutation_base" not in calls["env"]

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
