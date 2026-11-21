"""Dogfood CI contracts: tasks-validate + INDEX freshness hard-fail.

AGE-76 REJECT r3 (b): tip hygiene stays dogfood-only. Template CI/pre-push
do NOT wire tasks-validate until AGE-68 ships connect INDEX seeds.
"""

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


def test_template_ci_omits_tip_hygiene_until_age68():
    """REJECT r3 (b): templates must not call tasks-validate (INDEX seed = AGE-68)."""
    text = TEMPLATE_CI.read_text(encoding="utf-8")
    tv_hits = [ln.strip() for ln in text.splitlines() if "tasks-validate" in ln]
    gate_hits = [
        ln.strip() for ln in text.splitlines() if "Task status gates + INDEX freshness" in ln
    ]
    assert tv_hits == []
    assert gate_hits == []
    assert _exact_lines(text, '"${CLI[@]}" process size') == ['"${CLI[@]}" process size']
    assert _exact_lines(text, '"${CLI[@]}" quality check') == ['"${CLI[@]}" quality check']


def test_pre_push_dogfood_runs_tasks_validate_templates_do_not():
    expected = '"${CLI[@]}" tasks-validate'
    dog = PRE_PUSH.read_text(encoding="utf-8")
    assert _exact_lines(dog, expected) == [expected]
    between = dog.split("tasks-validate", 1)[1].split("process size", 1)[0]
    soft = [ln for ln in between.splitlines() if "|| true" in ln]
    assert soft == []

    tmpl = TEMPLATE_PRE_PUSH.read_text(encoding="utf-8")
    tmpl_tv = [ln.strip() for ln in tmpl.splitlines() if "tasks-validate" in ln]
    assert tmpl_tv == []
    assert _exact_lines(tmpl, '"${CLI[@]}" process size') == ['"${CLI[@]}" process size']
