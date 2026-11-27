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


def test_load_quality_without_file_detects_layout(tmp_path: Path):
    from agentized.quality import load_quality

    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "m.py").write_text("M=1\n", encoding="utf-8")
    assert load_quality(tmp_path) == detect_quality_config(tmp_path)
    assert load_quality(tmp_path)["modules"][0]["source"] == ["lib"]


def _expected_src(source: str, tests: list[str]) -> dict:
    from agentized.quality_defaults import default_quality_config

    cfg = default_quality_config()
    args = " ".join(tests)
    cfg["modules"] = [
        {
            "id": source,
            "source": [source],
            "test_command": (
                f"python3 -m pytest {args} -q --cov={source} --cov-branch "
                "--cov-report=term-missing "
                f"--cov-report=lcov:coverage/{source}/lcov.info "
                f"--cov-report=json:coverage/{source}/coverage.json "
                "--cov-fail-under=0"
            ),
            "coverage_lcov": f"coverage/{source}/lcov.info",
            "coverage_json": f"coverage/{source}/coverage.json",
            "thresholds": {},
        }
    ]
    cfg["mutation"]["include_globs"] = [f"{source}/*.py"]
    cfg["test_smells"]["include_globs"] = [f"{t}/**/*.py" for t in tests]
    cfg["architecture"]["source_roots"] = [source]
    cfg["architecture"]["tool"] = "builtin"
    return cfg


def test_detect_full_config_src_tests_and_test(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("A=1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "test").mkdir()
    assert detect_quality_config(tmp_path) == _expected_src("src", ["tests", "test"])


def test_detect_full_config_test_dir_only(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("M=1\n", encoding="utf-8")
    (tmp_path / "test").mkdir()
    assert detect_quality_config(tmp_path) == _expected_src("app", ["test"])


def test_detect_full_config_no_tests_references_tests(tmp_path: Path):
    (tmp_path / "lib" / "pkg").mkdir(parents=True)
    (tmp_path / "lib" / "pkg" / "deep.py").write_text("D=1\n", encoding="utf-8")
    assert detect_quality_config(tmp_path) == _expected_src("lib", ["tests"])


def test_detect_skips_source_dir_without_python(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "README.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "b.py").write_text("B=1\n", encoding="utf-8")
    assert detect_quality_config(tmp_path)["modules"][0]["id"] == "lib"
    (tmp_path / "lib" / "b.py").unlink()
    assert detect_quality_config(tmp_path)["modules"] == []


def test_detect_partial_dogfood_is_not_dogfood(tmp_path: Path):
    (tmp_path / "runtime" / "agentized").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("A=1\n", encoding="utf-8")
    assert detect_quality_config(tmp_path) == _expected_src("src", ["tests"])
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    from agentized.quality_defaults import default_quality_config

    assert detect_quality_config(tmp_path) == default_quality_config()


def test_detect_empty_full_config(tmp_path: Path):
    from agentized.quality_defaults import default_quality_config

    cfg = default_quality_config()
    cfg["modules"] = []
    cfg["mutation"]["include_globs"] = []
    cfg["test_smells"]["include_globs"] = []
    cfg["architecture"]["source_roots"] = []
    cfg["architecture"]["tool"] = "builtin"
    assert detect_quality_config(tmp_path) == cfg
