"""AGE-85: connect derives quality.json modules from consumer layout."""

from __future__ import annotations

from pathlib import Path

from agentized.quality_detect import detect_quality_config


def test_detect_empty_consumer(tmp_path: Path):
    cfg = detect_quality_config(tmp_path)
    assert cfg["modules"] == []
    assert cfg["mutation"]["include_globs"] == []
    assert cfg["test_smells"]["include_globs"] == []
    assert cfg["architecture"]["source_roots"] == []
    assert cfg["architecture"]["tool"] == "builtin"
    assert cfg["mutation"]["min_score_covered"] == 100


def test_detect_dogfood_layout(tmp_path: Path):
    (tmp_path / "runtime" / "agentized").mkdir(parents=True)
    (tmp_path / "runtime" / "agentized" / "x.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "test_x.py").write_text("def test_x():\n    assert True\n")
    cfg = detect_quality_config(tmp_path)
    assert cfg["modules"][0]["id"] == "runtime"
    assert cfg["modules"][0]["source"] == ["runtime/agentized"]
    assert "tests/unit" in cfg["modules"][0]["test_command"]
    assert cfg["mutation"]["include_globs"] == ["runtime/agentized/*.py"]


def test_detect_src_with_tests(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pkg.py").write_text("V=1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pkg.py").write_text("def test_v():\n    assert True\n")
    cfg = detect_quality_config(tmp_path)
    assert cfg["modules"][0]["id"] == "src"
    assert cfg["modules"][0]["source"] == ["src"]
    assert "--cov=src" in cfg["modules"][0]["test_command"]
    assert cfg["mutation"]["include_globs"] == ["src/*.py"]
    assert cfg["architecture"]["source_roots"] == ["src"]


def test_detect_src_without_tests_still_writes_module(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("A=1\n", encoding="utf-8")
    cfg = detect_quality_config(tmp_path)
    assert cfg["modules"][0]["source"] == ["src"]
    assert "pytest tests" in cfg["modules"][0]["test_command"]
