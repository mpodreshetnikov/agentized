"""Mutation oracles for status_gates.py (mutmut test_status_gates_*.py)."""

from __future__ import annotations

from pathlib import Path

from agentized.status_gates import (
    ALL_STATUSES,
    CANONICAL_STATUSES,
    DECISION_SECTION,
    INDEX_ACTIVE_STATUSES,
    MSG_DECISION_PREFIX,
    MSG_PROGRESS_PREFIX,
    MSG_TASK_DELETED,
    MSG_UNKNOWN_STATUS,
    PROGRESS_SECTION,
    STATUS_ALIASES,
    GateResult,
    is_known_status,
    normalize_status,
    run_tasks_validate,
    section_body,
    section_is_prefix,
)


def test_status_gates_vocab_exact():
    assert CANONICAL_STATUSES == (
        "idea",
        "open",
        "queue",
        "in-progress",
        "self-review",
        "for-review",
        "blocked",
        "done",
        "canceled",
    )
    assert STATUS_ALIASES == {"dropped": "canceled", "queued": "queue"}
    assert ALL_STATUSES == CANONICAL_STATUSES + ("dropped", "queued")
    assert INDEX_ACTIVE_STATUSES == (
        "open",
        "queue",
        "in-progress",
        "self-review",
        "for-review",
        "blocked",
    )
    assert MSG_UNKNOWN_STATUS == "unknown status {st!r}"
    assert MSG_UNKNOWN_STATUS.format(st="wip") == "unknown status 'wip'"
    assert normalize_status("dropped") == "canceled"
    assert normalize_status("queued") == "queue"
    assert normalize_status("Open") == "open"
    assert normalize_status("  SELF-REVIEW ") == "self-review"
    assert normalize_status("") == ""
    assert normalize_status(None) == ""
    assert normalize_status("   ") == ""
    assert is_known_status("idea") is True
    assert is_known_status("dropped") is True
    assert is_known_status("queued") is True
    assert is_known_status("wip") is False
    assert is_known_status("") is False
    assert is_known_status(None) is False
    assert is_known_status("done") is True
    assert is_known_status("canceled") is True
    assert PROGRESS_SECTION == "## Progress"
    assert DECISION_SECTION == "## Decision Log"
    assert MSG_PROGRESS_PREFIX == (
        "Progress is not an exact prefix of base (append-only; corrections = append only)"
    )
    assert MSG_DECISION_PREFIX == (
        "Decision Log is not an exact prefix of base (append-only; corrections = append only)"
    )
    assert MSG_TASK_DELETED == "task deleted; set статус: canceled"
    sample = "## Progress\n\na\n\n## Decision Log\n\nb\n"
    assert section_body(sample, PROGRESS_SECTION) == "\n\na\n"
    assert section_body(sample, DECISION_SECTION) == "\n\nb\n"
    assert section_body("x", PROGRESS_SECTION) is None
    assert section_is_prefix("x", sample, PROGRESS_SECTION) is True
    assert (
        section_is_prefix(
            sample,
            "## Progress\n\na\n\n- more\n\n## Decision Log\n\nb\n",
            PROGRESS_SECTION,
        )
        is True
    )
    assert (
        section_is_prefix(sample, "## Progress\n\nZ\n\n## Decision Log\n\nb\n", PROGRESS_SECTION)
        is False
    )
    assert (
        section_is_prefix(sample, "## Progress\n\na\n\n## Decision Log\n\nZ\n", DECISION_SECTION)
        is False
    )
    # find not rfind: first Progress wins when a later Progress exists.
    nested = "## Progress\n\nfirst\n\n## Mid\n\nx\n\n## Progress\n\nsecond\n"
    assert section_body(nested, PROGRESS_SECTION) == "\n\nfirst\n"
    # find not rfind on \\n## : first following H2 wins (not a later one).
    twin = "## Progress\n\nbody\n\n## Decision Log\n\nd1\n\n## Extra\n\ne\n"
    assert section_body(twin, PROGRESS_SECTION) == "\n\nbody\n"
    # end == 0 must slice empty (not treat as missing): Progress immediately followed by H2.
    empty_prog = "## Progress\n## Decision Log\n\nx\n"
    assert section_body(empty_prog, PROGRESS_SECTION) == ""


def test_run_tasks_validate_merges_tip_errors_exact(tmp_path: Path, monkeypatch):
    """Kill tip-merge / pr-forward mutants on run_tasks_validate (#55 surface + AGE-86)."""
    import agentized.status_gates as sg

    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True)
    tip_calls: list[object] = []

    monkeypatch.setattr(sg, "resolve_validate_base_ref", lambda root, *, explicit=None: "BASE")
    monkeypatch.setattr(sg, "previous_task_texts_from_git", lambda *a, **k: {"T-x.md": "# old\n"})
    monkeypatch.setattr(
        sg,
        "validate_tasks_dir",
        lambda *a, **k: GateResult(False, ("gate-err",)),
    )

    def fake_tip(tasks_dir, *, pr=None, env=None, check_index=True):
        tip_calls.append(pr)
        return GateResult(False, ("tip-err",))

    monkeypatch.setattr("agentized.tip_hygiene.validate_tip_hygiene", fake_tip)
    # Also patch the late import target used inside run_tasks_validate.
    import agentized.tip_hygiene as tip_mod

    monkeypatch.setattr(tip_mod, "validate_tip_hygiene", fake_tip)

    ref, result = run_tasks_validate(tasks, repo_root=tmp_path, base_ref="B", pr=42)
    assert ref == "BASE"
    assert tip_calls == [42]
    assert result == GateResult(False, ("gate-err", "tip-err"))
    assert result.ok is False
    assert result.errors == ("gate-err", "tip-err")

    # tip OK → return gate result unchanged (no merge).
    tip_calls.clear()

    def tip_ok(tasks_dir, *, pr=None, env=None, check_index=True):
        tip_calls.append(pr)
        return GateResult(True)

    monkeypatch.setattr(tip_mod, "validate_tip_hygiene", tip_ok)
    ref2, result2 = run_tasks_validate(tasks, repo_root=tmp_path, pr="#7")
    assert ref2 == "BASE"
    assert tip_calls == ["#7"]
    assert result2 == GateResult(False, ("gate-err",))
