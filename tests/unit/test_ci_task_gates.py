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


def test_tasks_validate_hard_in_dogfood_and_template_ci():
    expected = '"${CLI[@]}" tasks-validate'
    for path in CI_PATHS:
        step = _gate_step(path)
        assert "|| true" not in step
        lines = [ln.strip() for ln in step.splitlines() if ln.strip() == expected]
        assert lines == [expected]


def test_index_freshness_uses_porcelain_no_hardcoded_paths():
    expected_index = '"${CLI[@]}" index'
    porcelain = '[[ -n "$(git status --porcelain)" ]]'
    for path in CI_PATHS:
        step = _gate_step(path)
        assert "|| true" not in step
        assert expected_index in step
        assert porcelain in step
        assert "exit 1" in step
        # Path-independent: template (and dogfood) must not hardcode context/ paths.
        assert "context/tasks/INDEX.md" not in step
        assert "context/leases/INDEX.md" not in step
        assert "git diff --exit-code" not in step
