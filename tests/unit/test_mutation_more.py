from __future__ import annotations

import json
from pathlib import Path

from agentized import mutation as mut


def test_mutation_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mut, "load_quality", lambda *a, **k: {"mutation": {"enabled": False}})
    assert mut.run_mutation(tmp_path) == 0


def test_mutation_skip_no_changed(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    monkeypatch.setattr(
        mut,
        "load_quality",
        lambda *a, **k: {
            "mutation": {"enabled": True, "min_score_covered": 100, "include_globs": []},
            "modules": [{"source": ["runtime/agentized"]}],
        },
    )
    monkeypatch.setattr(mut, "_changed_py_files", lambda *a, **k: [])
    monkeypatch.chdir(tmp_path)
    assert mut.run_mutation(tmp_path) == 0
    assert (tmp_path / "reports/mutation/mutation-summary.json").exists()


def test_ensure_link_and_collect(tmp_path: Path):
    (tmp_path / "runtime" / "agentized").mkdir(parents=True)
    assert mut._ensure_agentized_link(tmp_path) is True
    assert mut._ensure_agentized_link(tmp_path) is False
    meta = tmp_path / "mutants" / "x.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text(
        json.dumps(
            {
                "exit_code_by_key": {
                    "agentized.process_control.x_size_check__mutmut_1": 1,
                    "agentized.process_control.x_claim_check__mutmut_1": 0,
                    "agentized.process_control.x_size_check__mutmut_2": 5,
                    "agentized.process_control.x_size_check__mutmut_3": 36,
                    "agentized.process_control.x_size_check__mutmut_4": None,
                }
            }
        ),
        encoding="utf-8",
    )
    stats = mut._collect_stats(tmp_path)
    assert stats["killed"] == 1
    assert stats["survived"] == 1
    assert stats["no_tests"] == 1
    assert stats["timeout"] == 1
    # None exit codes fall into other (whole-file gate; no line scoping).
    assert stats["other"] == 1
    assert stats["totalMutants"] == 4


def test_changed_py_files_filters(tmp_path: Path, monkeypatch):
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = "runtime/agentized/quality.py\ntests/unit/x.py\nREADME.md\n"
            stderr = ""

        return R()

    monkeypatch.setattr(mut.subprocess, "run", fake_run)
    out = mut._changed_py_files(tmp_path, "origin/main", ["runtime/agentized"])
    assert out == ["runtime/agentized/quality.py"]


def test_run_mutation_include_globs_filter_reaches_mutmut(tmp_path: Path, monkeypatch):
    """Drive run_mutation: flat+nested under *.py reach mutmut; outside paths drop."""
    (tmp_path / "context").mkdir()
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "test_quality.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "mutation": {
                    "enabled": True,
                    "min_score_covered": 100,
                    "break_on_survived": True,
                    "break_on_no_tests": True,
                    "include_globs": ["runtime/agentized/*.py"],
                    "base_ref": "origin/main",
                },
                "modules": [{"source": ["runtime/agentized"]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        mut,
        "_changed_py_files",
        lambda *a, **k: [
            "runtime/agentized/board.py",
            "runtime/agentized/sub/pkg.py",
            "runtime/other.py",
            "tests/unit/test_x.py",
        ],
    )
    captured: list[list[str]] = []

    def fake_write_setup(root, only):  # noqa: ARG001
        captured.append(list(only))
        (root / "setup.cfg").write_text("[mutmut]\n", encoding="utf-8")

    monkeypatch.setattr(mut, "_write_setup", fake_write_setup)
    monkeypatch.setattr(mut, "_ensure_agentized_link", lambda root: False)

    class Done(Exception):
        pass

    def fake_run(cmd, **kwargs):  # noqa: ARG001
        class R:
            returncode = 0

        # Pre-mutation unit pytest then mutmut run.
        if cmd[:3] == [__import__("sys").executable, "-m", "pytest"]:
            return R()
        if cmd[:3] == [__import__("sys").executable, "-m", "mutmut"]:
            raise Done("mutmut reached")
        return R()

    monkeypatch.setattr(mut.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mut,
        "_collect_stats",
        lambda root: {  # noqa: ARG001
            "killed": 0,
            "survived": 0,
            "no_tests": 0,
            "timeout": 0,
            "totalMutants": 0,
            "mutationScoreCovered": 100.0,
            "mutationScore": 100.0,
        },
    )
    monkeypatch.chdir(tmp_path)
    try:
        mut.run_mutation(tmp_path)
    except Done:
        pass
    assert captured == [["agentized/board.py", "agentized/sub/pkg.py"]]


def test_write_setup(tmp_path: Path):
    unit = tmp_path / "tests" / "unit"
    unit.mkdir(parents=True)
    (unit / "test_quality.py").write_text("def test_x():\n    assert 1 == 1\n", encoding="utf-8")
    mut._write_setup(tmp_path, ["agentized/quality.py"])
    text = (tmp_path / "setup.cfg").read_text(encoding="utf-8")
    lines = text.splitlines()
    idx = lines.index("only_mutate =")
    assert lines[idx + 1] == "  agentized/quality.py"
    # Durable header still present with the [mutmut] section.
    assert lines[0] == "[mutmut]"
    sel = lines.index("pytest_add_cli_args_test_selection =")
    assert lines[sel + 1] == "  tests/unit/test_quality.py"


def test_test_selection_multi_file(tmp_path: Path):
    unit = tmp_path / "tests" / "unit"
    unit.mkdir(parents=True)
    (unit / "test_process_size.py").write_text(
        "def test_a():\n    assert 1 == 1\n", encoding="utf-8"
    )
    (unit / "test_mutation_gate.py").write_text(
        "def test_b():\n    assert 1 == 1\n", encoding="utf-8"
    )
    (unit / "test_mutation_more.py").write_text(
        "def test_c():\n    assert 1 == 1\n", encoding="utf-8"
    )
    selected = mut._test_selection_for(
        ["agentized/process_size.py", "agentized/mutation.py"],
        tmp_path,
    )
    assert selected == [
        "tests/unit/test_process_size.py",
        "tests/unit/test_mutation_gate.py",
        "tests/unit/test_mutation_more.py",
    ]


def test_test_selection_fallback_all_unit(tmp_path: Path):
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    assert mut._test_selection_for(["agentized/missing_mod.py"], tmp_path) == ["tests/unit"]
