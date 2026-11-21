"""Dogfood + shipped-template contracts: tasks-validate hard-fail (AGE-67 / AGE-86).

AGE-86: templates gain tasks-validate + INDEX porcelain (prefix gate surface).
Dogfood pre-push keeps tip-hygiene echo from AGE-76/#55.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOGFOOD_CI = ROOT / ".github" / "workflows" / "ci.yml"
TEMPLATE_CI = ROOT / "templates" / "quality" / "ci.yml"
DOGFOOD_PRE_PUSH = ROOT / ".githooks" / "pre-push"
TEMPLATE_PRE_PUSH = ROOT / "templates" / "quality" / "pre-push"


def _gate_step(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("Task status gates + INDEX freshness")[1].split(
        "Coverage + mutation hard gates"
    )[0]


def _exact_lines(step: str, expected: str) -> list[str]:
    return [ln.strip() for ln in step.splitlines() if ln.strip() == expected]


def _assert_tasks_validate_hard(path: Path) -> None:
    expected = '"${CLI[@]}" tasks-validate'
    step = _gate_step(path)
    assert _exact_lines(step, expected) == [expected]
    soft = [ln for ln in step.splitlines() if "|| true" in ln]
    assert soft == []


def _assert_index_porcelain(path: Path) -> None:
    expected_index = '"${CLI[@]}" index'
    step = _gate_step(path)
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


def _assert_pre_push_tasks_validate(path: Path) -> None:
    expected = '"${CLI[@]}" tasks-validate'
    text = path.read_text(encoding="utf-8")
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if "tasks-validate" in ln and not ln.strip().startswith("#") and "echo " not in ln
    ]
    assert lines == [expected]
    soft = [ln for ln in text.splitlines() if "|| true" in ln]
    assert soft == []


def test_tasks_validate_hard_in_dogfood_ci():
    _assert_tasks_validate_hard(DOGFOOD_CI)


def test_tasks_validate_hard_in_template_ci():
    _assert_tasks_validate_hard(TEMPLATE_CI)


def test_index_freshness_uses_porcelain_no_hardcoded_paths():
    _assert_index_porcelain(DOGFOOD_CI)
    _assert_index_porcelain(TEMPLATE_CI)


def test_tasks_validate_hard_in_pre_push_hooks():
    _assert_pre_push_tasks_validate(DOGFOOD_PRE_PUSH)
    _assert_pre_push_tasks_validate(TEMPLATE_PRE_PUSH)
