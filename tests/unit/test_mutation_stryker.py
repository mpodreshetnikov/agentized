"""Stryker dispatch + covered-score parsing (AGE-34)."""
from __future__ import annotations

import json
from pathlib import Path

from agentized import mutation as mut
from agentized import mutation_stryker as ms


def test_read_stryker_covered_from_json(tmp_path: Path):
    reports = tmp_path / "reports" / "mutation"
    reports.mkdir(parents=True)
    (reports / "mutation.json").write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
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
    # Alias on mutation module stays wired.
    assert mut._read_stryker_covered(tmp_path) == stats


def test_read_stryker_prefers_tool_metrics(tmp_path: Path):
    reports = tmp_path / "reports" / "mutation"
    reports.mkdir(parents=True)
    (reports / "mutation-result.json").write_text(
        json.dumps(
            {
                "mutationScoreOfCoveredCode": 100,
                "mutationScore": 90,
                "files": {"a.ts": {"mutants": [{"status": "Killed"}]}},
            }
        ),
        encoding="utf-8",
    )
    stats = ms.read_stryker_covered(tmp_path)
    assert stats is not None
    assert stats["mutationScoreCovered"] == 100
    assert stats["mutationScore"] == 90
    assert stats["source"] == "reports/mutation/mutation-result.json"


def test_read_stryker_missing(tmp_path: Path):
    assert ms.read_stryker_covered(tmp_path) is None


def test_find_stryker_wrapper_order(tmp_path: Path):
    preferred = tmp_path / "scripts" / "quality" / "run-mutation-js.cjs"
    preferred.parent.mkdir(parents=True)
    preferred.write_text("console.log(1)\n", encoding="utf-8")
    (tmp_path / "run-mutation-js.cjs").write_text("console.log(2)\n", encoding="utf-8")
    assert ms.find_stryker_wrapper(tmp_path) == preferred
    assert mut._find_stryker_wrapper(tmp_path) == preferred


def test_run_stryker_gate_no_runner(tmp_path: Path):
    rc = mut._run_stryker_gate(
        tmp_path,
        changed=["src/a.ts"],
        mut={"break_on_survived": True},
        base="origin/main",
        min_score=100,
        languages=["typescript"],
    )
    assert rc == 1
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["reasons"] == ["no_stryker_runner"]
    assert summary["passed"] is False


def test_run_stryker_gate_uses_wrapper(tmp_path: Path, monkeypatch):
    wrapper = tmp_path / "run-mutation-js.cjs"
    wrapper.write_text("// stub\n", encoding="utf-8")
    reports = tmp_path / "reports" / "mutation"
    reports.mkdir(parents=True)
    (reports / "mutation.json").write_text(
        json.dumps({"files": {"src/a.ts": {"mutants": [{"status": "Killed"}]}}}),
        encoding="utf-8",
    )

    class R:
        returncode = 0

    calls: dict = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["env"] = kwargs.get("env") or {}
        return R()

    monkeypatch.setattr(ms.subprocess, "run", fake_run)
    rc = mut._run_stryker_gate(
        tmp_path,
        changed=["src/a.ts"],
        mut={"break_on_survived": True},
        base="origin/main",
        min_score=100,
        languages=["typescript"],
    )
    assert rc == 0
    assert calls["cmd"] == ["node", str(wrapper)]
    assert calls["env"]["MUTATION_BASE"] == "origin/main"
    assert calls["env"]["STRYKER_BASE"] == "origin/main"
    assert calls["env"]["MUTATION_MIN_SCORE_COVERED"] == "100"
    summary = json.loads((reports / "mutation-summary.json").read_text())
    assert summary["passed"] is True
    assert summary["reasons"] == []
    assert summary["languages"] == ["typescript"]


def test_run_stryker_wrapper_exit_nonzero(tmp_path: Path, monkeypatch):
    wrapper = tmp_path / "run-mutation-js.cjs"
    wrapper.write_text("// stub\n", encoding="utf-8")

    class R:
        returncode = 7

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: R())
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
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["reasons"] == ["stryker_exit=7"]


def test_run_stryker_missing_json_after_wrapper(tmp_path: Path, monkeypatch):
    wrapper = tmp_path / "run-mutation-js.cjs"
    wrapper.write_text("// stub\n", encoding="utf-8")

    class R:
        returncode = 0

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: R())
    rc = mut._run_stryker_gate(
        tmp_path,
        changed=["src/a.ts"],
        mut={},
        base="origin/main",
        min_score=100,
        languages=["typescript"],
    )
    assert rc == 1
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["reasons"] == ["missing_stryker_json"]


def test_run_stryker_survived_fails(tmp_path: Path, monkeypatch):
    wrapper = tmp_path / "run-mutation-js.cjs"
    wrapper.write_text("// stub\n", encoding="utf-8")
    reports = tmp_path / "reports" / "mutation"
    reports.mkdir(parents=True)
    (reports / "mutation.json").write_text(
        json.dumps(
            {
                "files": {
                    "src/a.ts": {
                        "mutants": [{"status": "Killed"}, {"status": "Survived"}]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class R:
        returncode = 0

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: R())
    rc = mut._run_stryker_gate(
        tmp_path,
        changed=["src/a.ts"],
        mut={"break_on_survived": True},
        base="origin/main",
        min_score=100,
        languages=["typescript"],
    )
    assert rc == 1
    summary = json.loads((reports / "mutation-summary.json").read_text())
    assert any(r.startswith("survived=") or r.startswith("score_covered=") for r in summary["reasons"])


def test_run_stryker_break_on_survived_false(tmp_path: Path, monkeypatch):
    wrapper = tmp_path / "run-mutation-js.cjs"
    wrapper.write_text("// stub\n", encoding="utf-8")
    reports = tmp_path / "reports" / "mutation"
    reports.mkdir(parents=True)
    (reports / "mutation.json").write_text(
        json.dumps(
            {
                "mutationScoreOfCoveredCode": 100,
                "files": {
                    "src/a.ts": {
                        "mutants": [{"status": "Killed"}, {"status": "Survived"}]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class R:
        returncode = 0

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: R())
    rc = mut._run_stryker_gate(
        tmp_path,
        changed=["src/a.ts"],
        mut={"break_on_survived": False},
        base="origin/main",
        min_score=50,
        languages=["javascript"],
    )
    assert rc == 0


def test_changed_source_files_filters_tests(tmp_path: Path, monkeypatch):
    def fake_names(root, base):
        return [
            "src/a.ts",
            "src/a.test.ts",
            "src/__tests__/b.ts",
            "runtime/agentized/x.py",
            "tests/unit/t.py",
            "README.md",
        ]

    monkeypatch.setattr(mut, "_git_changed_names", fake_names)
    out = mut._changed_source_files(tmp_path, "origin/main", ["src", "runtime/agentized"])
    assert out == ["runtime/agentized/x.py", "src/a.ts"]


def test_git_changed_names_fallback(tmp_path: Path, monkeypatch):
    calls = {"n": 0}

    class R1:
        returncode = 1
        stdout = ""
        stderr = "fail1"

    class R2:
        returncode = 0
        stdout = "src/a.py\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        return R1() if calls["n"] == 1 else R2()

    monkeypatch.setattr(mut.subprocess, "run", fake_run)
    assert mut._git_changed_names(tmp_path, "origin/main") == ["src/a.py"]


def test_is_test_path_keeps_production_test_smells_module():
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
