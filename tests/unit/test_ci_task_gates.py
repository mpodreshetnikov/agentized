"""Dogfood/template contracts: tasks-validate + INDEX freshness hard-fail in CI."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_PATHS = (
    ROOT / ".github" / "workflows" / "ci.yml",
    ROOT / "templates" / "quality" / "ci.yml",
)


def _gate_step(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("Task status gates + INDEX freshness")[1].split(
        "Coverage + mutation hard gates"
    )[0]


def _exact_lines(step: str, expected: str) -> list[str]:
    return [ln.strip() for ln in step.splitlines() if ln.strip() == expected]


def test_tasks_validate_hard_in_dogfood_and_template_ci():
    expected = '"${CLI[@]}" tasks-validate'
    found = {str(p.relative_to(ROOT)): _exact_lines(_gate_step(p), expected) for p in CI_PATHS}
    assert found == {
        ".github/workflows/ci.yml": [expected],
        "templates/quality/ci.yml": [expected],
    }
    soft = {
        str(p.relative_to(ROOT)): [ln for ln in _gate_step(p).splitlines() if "|| true" in ln]
        for p in CI_PATHS
    }
    assert soft == {".github/workflows/ci.yml": [], "templates/quality/ci.yml": []}


def test_index_freshness_uses_porcelain_no_hardcoded_paths():
    expected_index = '"${CLI[@]}" index'
    found_index = {
        str(p.relative_to(ROOT)): _exact_lines(_gate_step(p), expected_index) for p in CI_PATHS
    }
    assert found_index == {
        ".github/workflows/ci.yml": [expected_index],
        "templates/quality/ci.yml": [expected_index],
    }
    porcelain = {
        str(p.relative_to(ROOT)): [
            ln.strip()
            for ln in _gate_step(p).splitlines()
            if "git status --porcelain" in ln and not ln.strip().startswith("#")
        ]
        for p in CI_PATHS
    }
    expected_porc = [
        'if [[ -n "$(git status --porcelain)" ]]; then',
        "git status --porcelain >&2",
    ]
    assert porcelain == {
        ".github/workflows/ci.yml": expected_porc,
        "templates/quality/ci.yml": expected_porc,
    }
    soft = {
        str(p.relative_to(ROOT)): [ln for ln in _gate_step(p).splitlines() if "|| true" in ln]
        for p in CI_PATHS
    }
    assert soft == {".github/workflows/ci.yml": [], "templates/quality/ci.yml": []}
    hardcoded = {
        str(p.relative_to(ROOT)): [
            ln.strip()
            for ln in _gate_step(p).splitlines()
            if "context/tasks/INDEX.md" in ln
            or "context/leases/INDEX.md" in ln
            or "git diff --exit-code" in ln
        ]
        for p in CI_PATHS
    }
    assert hardcoded == {".github/workflows/ci.yml": [], "templates/quality/ci.yml": []}
    exits = {str(p.relative_to(ROOT)): _exact_lines(_gate_step(p), "exit 1") for p in CI_PATHS}
    assert exits == {
        ".github/workflows/ci.yml": ["exit 1", "exit 1"],
        "templates/quality/ci.yml": ["exit 1", "exit 1"],
    }
