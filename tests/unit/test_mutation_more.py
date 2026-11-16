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
    meta.write_text(json.dumps({"exit_code_by_key": {"a": 1, "b": 0, "c": 5, "d": 36}}), encoding="utf-8")
    stats = mut._collect_stats(tmp_path)
    assert stats["killed"] == 1
    assert stats["survived"] == 1
    assert stats["no_tests"] == 1
    assert stats["timeout"] == 1


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


def test_include_globs_match_flat_and_nested_modules():
    """Maxim: fnmatch ** does not match zero dirs — dual globs required.

    Mirrors mutation gate filter: any(fnmatch(path, pat) for pat in include_globs).
    """
    import fnmatch

    def matches(path: str, globs: list[str]) -> bool:
        path = path.replace("\\", "/")
        return any(fnmatch.fnmatch(path, pat) for pat in globs)

    root = Path(__file__).resolve().parents[2]
    globs = json.loads((root / "context" / "quality.json").read_text(encoding="utf-8"))[
        "mutation"
    ]["include_globs"]
    assert globs == ["runtime/agentized/*.py", "runtime/agentized/**/*.py"]
    flat = [
        "runtime/agentized/process_control.py",
        "runtime/agentized/board.py",
        "runtime/agentized/quality.py",
    ]
    nested = [
        "runtime/agentized/sub/pkg.py",
        "runtime/agentized/a/b/c.py",
    ]
    assert [matches(p, globs) for p in flat] == [True, True, True]
    assert [matches(p, globs) for p in nested] == [True, True]
    # Regression: ** alone must NOT cover flat files.
    starstar_only = ["runtime/agentized/**/*.py"]
    assert matches("runtime/agentized/process_control.py", starstar_only) is False
    assert matches("runtime/agentized/board.py", starstar_only) is False
    assert matches("runtime/agentized/sub/x.py", starstar_only) is True
    assert matches("runtime/other.py", globs) is False
    assert matches("tests/unit/test_x.py", globs) is False


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
    (unit / "test_process_size.py").write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
    (unit / "test_mutation_gate.py").write_text("def test_b():\n    assert 1 == 1\n", encoding="utf-8")
    (unit / "test_mutation_more.py").write_text("def test_c():\n    assert 1 == 1\n", encoding="utf-8")
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
