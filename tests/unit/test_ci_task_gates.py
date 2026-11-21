"""Dogfood CI contracts: tasks-validate + INDEX freshness hard-fail."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOGFOOD_CI = ROOT / ".github" / "workflows" / "ci.yml"


def _gate_step(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("Task status gates + INDEX freshness")[1].split(
        "Coverage + mutation hard gates"
    )[0]


def _exact_lines(step: str, expected: str) -> list[str]:
    return [ln.strip() for ln in step.splitlines() if ln.strip() == expected]


def test_tasks_validate_hard_in_dogfood_ci():
    expected = '"${CLI[@]}" tasks-validate'
    step = _gate_step(DOGFOOD_CI)
    assert _exact_lines(step, expected) == [expected]
    soft = [ln for ln in step.splitlines() if "|| true" in ln]
    assert soft == []
    # AGE-76: tip hygiene needs the PR number under validation.
    assert "TASKS_VALIDATE_PR: ${{ github.event.pull_request.number }}" in DOGFOOD_CI.read_text(
        encoding="utf-8"
    )


def test_index_freshness_uses_porcelain_no_hardcoded_paths():
    expected_index = '"${CLI[@]}" index'
    step = _gate_step(DOGFOOD_CI)
    assert _exact_lines(step, expected_index) == [expected_index]
    porcelain = [
        ln.strip()
        for ln in step.splitlines()
        if "git status --porcelain" in ln and not ln.strip().startswith("#")
    ]
    assert porcelain == [
        'if [[ -n "$(git status --porcelain)" ]]; then',
        "git status --porcelain >&2",
    ]
    soft = [ln for ln in step.splitlines() if "|| true" in ln]
    assert soft == []
    hardcoded = [
        ln.strip()
        for ln in step.splitlines()
        if "context/tasks/INDEX.md" in ln
        or "context/leases/INDEX.md" in ln
        or "git diff --exit-code" in ln
    ]
    assert hardcoded == []
    assert _exact_lines(step, "exit 1") == ["exit 1", "exit 1"]
