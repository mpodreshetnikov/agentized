"""Dogfood CI contracts: tasks-validate + INDEX freshness hard-fail."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOGFOOD_CI = ROOT / ".github" / "workflows" / "ci.yml"
TEMPLATE_CI = ROOT / "templates" / "quality" / "ci.yml"
PRE_PUSH = ROOT / ".githooks" / "pre-push"
TEMPLATE_PRE_PUSH = ROOT / "templates" / "quality" / "pre-push"


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


def test_template_ci_has_tasks_validate_hard():
    expected = '"${CLI[@]}" tasks-validate'
    step = _gate_step(TEMPLATE_CI)
    assert _exact_lines(step, expected) == [expected]
    soft = [ln for ln in step.splitlines() if "|| true" in ln]
    assert soft == []


def test_pre_push_runs_tasks_validate():
    expected = '"${CLI[@]}" tasks-validate'
    for path in (PRE_PUSH, TEMPLATE_PRE_PUSH):
        text = path.read_text(encoding="utf-8")
        assert _exact_lines(text, expected) == [expected]
        between = text.split("tasks-validate", 1)[1].split("process size", 1)[0]
        soft = [ln for ln in between.splitlines() if "|| true" in ln]
        assert soft == []
