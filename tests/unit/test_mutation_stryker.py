"""Stryker dispatch + covered-score parsing (AGE-34)."""
from __future__ import annotations

import json
from pathlib import Path

from agentized import mutation as mut
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
    assert mut._read_stryker_covered(tmp_path) == stats
    assert ms.read_stryker_covered(tmp_path / "empty") is None
    _report(
        tmp_path,
        {
            "mutationScoreOfCoveredCode": 100,
            "mutationScore": 90,
            "files": {"a.ts": {"mutants": [{"status": "Killed"}]}},
        },
        name="mutation-result.json",
    )
    # mutation.json still preferred when both exist
    assert ms.read_stryker_covered(tmp_path)["source"].endswith("mutation.json")
    (tmp_path / "reports/mutation/mutation.json").unlink()
    got = ms.read_stryker_covered(tmp_path)
    assert got is not None and got["mutationScoreCovered"] == 100
    preferred = tmp_path / "scripts" / "quality" / "run-mutation-js.cjs"
    preferred.parent.mkdir(parents=True)
    preferred.write_text("x\n", encoding="utf-8")
    (tmp_path / "run-mutation-js.cjs").write_text("y\n", encoding="utf-8")
    assert ms.find_stryker_wrapper(tmp_path) == preferred == mut._find_stryker_wrapper(tmp_path)


def test_run_stryker_gate_matrix(tmp_path: Path, monkeypatch):
    assert (
        mut._run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={"break_on_survived": True},
            base="origin/main",
            min_score=100,
            languages=["typescript"],
        )
        == 1
    )
    assert json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())[
        "reasons"
    ] == ["no_stryker_runner"]

    wrapper = tmp_path / "run-mutation-js.cjs"
    wrapper.write_text("//\n", encoding="utf-8")
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
        mut._run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={"break_on_survived": True},
            base="origin/main",
            min_score=100,
            languages=["typescript"],
        )
        == 0
    )
    assert calls["cmd"] == ["node", str(wrapper)]
    assert calls["env"]["MUTATION_MIN_SCORE_COVERED"] == "100"
    assert json.loads((reports / "mutation-summary.json").read_text())["passed"] is True

    class R7:
        returncode = 7

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: R7())
    assert (
        mut._run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={},
            base="origin/main",
            min_score=100,
            languages=["typescript"],
        )
        == 7
    )

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: R0())
    (reports / "mutation.json").unlink()
    assert (
        mut._run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={},
            base="origin/main",
            min_score=100,
            languages=["typescript"],
        )
        == 1
    )
    _report(
        tmp_path,
        {"files": {"src/a.ts": {"mutants": [{"status": "Killed"}, {"status": "Survived"}]}}},
    )
    assert (
        mut._run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={"break_on_survived": True},
            base="origin/main",
            min_score=100,
            languages=["typescript"],
        )
        == 1
    )
    _report(
        tmp_path,
        {
            "mutationScoreOfCoveredCode": 100,
            "files": {"src/a.ts": {"mutants": [{"status": "Killed"}, {"status": "Survived"}]}},
        },
    )
    assert (
        mut._run_stryker_gate(
            tmp_path,
            changed=["src/a.ts"],
            mut={"break_on_survived": False},
            base="origin/main",
            min_score=50,
            languages=["javascript"],
        )
        == 0
    )


def test_changed_source_and_test_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        mut,
        "_git_changed_names",
        lambda root, base: [
            "src/a.ts",
            "src/a.test.ts",
            "src/__tests__/b.ts",
            "runtime/agentized/x.py",
            "tests/unit/t.py",
            "README.md",
        ],
    )
    assert mut._changed_source_files(tmp_path, "origin/main", ["src", "runtime/agentized"]) == [
        "runtime/agentized/x.py",
        "src/a.ts",
    ]
    paths = [
        "runtime/agentized/test_smells.py",
        "tests/unit/test_foo.py",
        "src/foo.test.ts",
        "src/__tests__/x.ts",
        "src/util.ts",
        "pkg/foo_test.py",
        "pkg/foo-test.js",
        "pkg/foo.spec.js",
    ]
    assert [mut._is_test_path(p) for p in paths] == [
        False,
        True,
        True,
        True,
        False,
        True,
        True,
        True,
    ]


def test_git_changed_names_fallback(tmp_path: Path, monkeypatch):
    n = {"i": 0}

    class R1:
        returncode = 1
        stdout = ""
        stderr = "fail1"

    class R2:
        returncode = 0
        stdout = "src/a.py\n"
        stderr = ""

    def fake_run(*a, **k):
        n["i"] += 1
        return R1() if n["i"] == 1 else R2()

    monkeypatch.setattr(mut.subprocess, "run", fake_run)
    assert mut._git_changed_names(tmp_path, "origin/main") == ["src/a.py"]
