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
            "mutation": {"enabled": True, "min_score_covered": 50, "include_globs": []},
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


def test_write_setup(tmp_path: Path):
    mut._write_setup(tmp_path, ["agentized/quality.py"])
    text = (tmp_path / "setup.cfg").read_text(encoding="utf-8")
    assert "only_mutate" in text
    assert "agentized/quality.py" in text
