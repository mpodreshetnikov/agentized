"""Dogfood/template contracts: tasks-validate + INDEX freshness hard-fail in CI."""

from __future__ import annotations

from pathlib import Path

from agentized.connect import MINIMAL_LEASES_INDEX_MD, MINIMAL_TASKS_INDEX_MD
from agentized.leases import rebuild_lease_index
from agentized.tasks import rebuild_task_index

ROOT = Path(__file__).resolve().parents[2]
CI_PATHS = (
    ROOT / ".github" / "workflows" / "ci.yml",
    ROOT / "templates" / "quality" / "ci.yml",
)


def _active_lines(path: Path, needle: str) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if needle in ln and not ln.strip().startswith("#") and "echo " not in ln
    ]


def test_tasks_validate_hard_in_dogfood_and_template_ci():
    expected = '"${CLI[@]}" tasks-validate'
    found = {str(p.relative_to(ROOT)): _active_lines(p, "tasks-validate") for p in CI_PATHS}
    assert found == {
        ".github/workflows/ci.yml": [expected],
        "templates/quality/ci.yml": [expected],
    }
    for path in CI_PATHS:
        step = path.read_text(encoding="utf-8").split("Task status gates + INDEX freshness")[1]
        step = step.split("Coverage + mutation hard gates")[0]
        assert "|| true" not in step


def test_index_freshness_hard_in_dogfood_and_template_ci():
    expected_index = '"${CLI[@]}" index'
    expected_diff = "git diff --exit-code -- context/tasks/INDEX.md context/leases/INDEX.md"
    found_index = {
        str(p.relative_to(ROOT)): [
            ln.strip()
            for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() == expected_index
        ]
        for p in CI_PATHS
    }
    assert found_index == {
        ".github/workflows/ci.yml": [expected_index],
        "templates/quality/ci.yml": [expected_index],
    }
    for path in CI_PATHS:
        step = path.read_text(encoding="utf-8").split("Task status gates + INDEX freshness")[1]
        step = step.split("Coverage + mutation hard gates")[0]
        assert "|| true" not in step
        assert expected_diff in step
        assert "exit 1" in step


def test_connect_seeds_match_empty_rebuild(tmp_path: Path):
    """Fresh connect INDEX seeds must equal generator output (INDEX CI gate)."""
    tasks_dir = tmp_path / "tasks"
    leases_dir = tmp_path / "leases"
    tasks_dir.mkdir()
    leases_dir.mkdir()
    assert MINIMAL_TASKS_INDEX_MD == rebuild_task_index(tasks_dir)
    assert MINIMAL_LEASES_INDEX_MD == rebuild_lease_index(leases_dir)
    assert "skeleton" not in MINIMAL_TASKS_INDEX_MD
    assert "skeleton" not in MINIMAL_LEASES_INDEX_MD
