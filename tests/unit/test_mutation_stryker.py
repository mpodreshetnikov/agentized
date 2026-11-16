"""Stryker dispatch + covered-score parsing (AGE-34)."""
from __future__ import annotations

import json
from pathlib import Path

from agentized import mutation as mut


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
    stats = mut._read_stryker_covered(tmp_path)
    assert stats is not None
    assert stats["killed"] == 1
    assert stats["survived"] == 1
    assert stats["no_tests"] == 1
    assert stats["timeout"] == 1
    # covered = killed+survived+timeout = 3 → (killed+timeout)/covered = 2/3
    assert stats["mutationScoreCovered"] == 66.67


def test_read_stryker_missing(tmp_path: Path):
    stats = mut._read_stryker_covered(tmp_path)
    assert stats == {} or stats is None
    assert (stats or {}).get("killed", 0) == 0


def test_find_stryker_wrapper_prefers_scripts(tmp_path: Path):
    path = tmp_path / "scripts" / "quality" / "run-mutation-js.cjs"
    path.parent.mkdir(parents=True)
    path.write_text("console.log(1)\n", encoding="utf-8")
    assert mut._find_stryker_wrapper(tmp_path) == path


def test_run_stryker_gate_no_runner(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mut, "_find_stryker_wrapper", lambda root: None)
    monkeypatch.setattr(mut.shutil, "which", lambda name: None)
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
    assert "no_stryker_runner" in summary["reasons"]


def test_run_stryker_gate_uses_wrapper(tmp_path: Path, monkeypatch):
    wrapper = tmp_path / "run-mutation-js.cjs"
    wrapper.write_text("// stub\n", encoding="utf-8")
    monkeypatch.setattr(mut, "_find_stryker_wrapper", lambda root: wrapper)

    class R:
        returncode = 0

    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return R()

    monkeypatch.setattr(mut.subprocess, "run", fake_run)
    rc = mut._run_stryker_gate(
        tmp_path,
        changed=["src/a.ts"],
        mut={},
        base="origin/main",
        min_score=100,
        languages=["typescript"],
    )
    assert rc == 0
    assert calls["cmd"][0] == "node"
    assert calls["cmd"][1] == str(wrapper)


def test_run_stryker_inline_gates_score(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mut, "_find_stryker_wrapper", lambda root: None)
    monkeypatch.setattr(mut.shutil, "which", lambda name: "/usr/bin/npx" if name == "npx" else None)

    class R:
        returncode = 0

    monkeypatch.setattr(mut.subprocess, "run", lambda *a, **k: R())
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
    assert any("survived=" in r or "score_covered=" in r for r in summary["reasons"])


def test_run_stryker_inline_missing_json(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mut, "_find_stryker_wrapper", lambda root: None)
    monkeypatch.setattr(mut.shutil, "which", lambda name: "/usr/bin/npx")

    class R:
        returncode = 0

    monkeypatch.setattr(mut.subprocess, "run", lambda *a, **k: R())
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
    assert "missing_stryker_json" in summary["reasons"]


def test_run_stryker_inline_exit_nonzero(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mut, "_find_stryker_wrapper", lambda root: None)
    monkeypatch.setattr(mut.shutil, "which", lambda name: "/usr/bin/npx")

    class R:
        returncode = 7

    monkeypatch.setattr(mut.subprocess, "run", lambda *a, **k: R())
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
    # Exact path→bool vector (list Eq) — not bare `is True`/`is False` oracles.
    paths = [
        "runtime/agentized/test_smells.py",
        "tests/unit/test_foo.py",
        "src/foo.test.ts",
        "src/__tests__/x.ts",
        "src/util.ts",
    ]
    assert [mut._is_test_path(p) for p in paths] == [False, True, True, True, False]

