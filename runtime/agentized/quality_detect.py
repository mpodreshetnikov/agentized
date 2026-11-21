"""Detect consumer source/test layout for connect-written quality.json (AGE-85)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .quality_defaults import default_quality_config

_SOURCE_CANDIDATES = ("src", "lib", "app")
_TEST_CANDIDATES = ("tests", "test")


def _has_python(dir_path: Path) -> bool:
    if not dir_path.is_dir():
        return False
    return next(dir_path.rglob("*.py"), None) is not None


def _dogfood_layout(root: Path) -> bool:
    return (root / "runtime" / "agentized").is_dir() and (root / "tests" / "unit").is_dir()


def _empty_consumer_quality() -> dict[str, Any]:
    cfg = default_quality_config()
    cfg["modules"] = []
    cfg["mutation"]["include_globs"] = []
    cfg["test_smells"]["include_globs"] = []
    cfg["architecture"]["source_roots"] = []
    cfg["architecture"]["tool"] = "builtin"
    return cfg


def _module_for_source(source: str, test_dirs: list[str]) -> dict[str, Any]:
    mid = source.replace("/", "-")
    # Convention when no tests dir yet: still reference tests/ (fail-closed at check).
    targets = test_dirs or ["tests"]
    test_args = " ".join(targets)
    return {
        "id": mid,
        "source": [source],
        "test_command": (
            f"python3 -m pytest {test_args} -q --cov={source} --cov-branch "
            f"--cov-report=term-missing "
            f"--cov-report=lcov:coverage/{mid}/lcov.info "
            f"--cov-report=json:coverage/{mid}/coverage.json "
            f"--cov-fail-under=0"
        ),
        "coverage_lcov": f"coverage/{mid}/lcov.info",
        "coverage_json": f"coverage/{mid}/coverage.json",
        "thresholds": {},
    }


def detect_quality_config(root: Path) -> dict[str, Any]:
    """Build quality.json for a consumer (or dogfood) checkout.

    - Agentized dogfood layout → full defaults (runtime + tests/unit).
    - ``src``/``lib``/``app`` with Python → one module + matching globs.
    - Nothing detected → empty modules / globs / source_roots (valid; gates skip
      clearly, not a silent pass over a stale dogfood module list).
    """
    if _dogfood_layout(root):
        return default_quality_config()

    source = next((c for c in _SOURCE_CANDIDATES if _has_python(root / c)), None)
    if source is None:
        return _empty_consumer_quality()

    test_dirs = [t for t in _TEST_CANDIDATES if (root / t).is_dir()]
    cfg = default_quality_config()
    cfg["modules"] = [_module_for_source(source, test_dirs)]
    cfg["mutation"]["include_globs"] = [f"{source}/*.py"]
    smell_globs = [f"{t}/**/*.py" for t in (test_dirs or ["tests"])]
    smell_globs.append("tests/**/test_*.py")
    cfg["test_smells"]["include_globs"] = smell_globs
    cfg["architecture"]["source_roots"] = [source]
    cfg["architecture"]["tool"] = "builtin"
    return cfg
