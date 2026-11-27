"""Mutation oracles for status_gates.py (mutmut test_status_gates_*.py)."""

from __future__ import annotations

from pathlib import Path

from agentized.status_gates import (
    ALL_STATUSES,
    CANONICAL_STATUSES,
    DECISION_SECTION,
    INDEX_ACTIVE_STATUSES,
    MSG_DECISION_DUPLICATE,
    MSG_DECISION_PREFIX,
    MSG_PROGRESS_DUPLICATE,
    MSG_PROGRESS_PREFIX,
    MSG_TASK_DELETED,
    MSG_UNKNOWN_STATUS,
    PROGRESS_SECTION,
    STATUS_ALIASES,
    GateResult,
    is_known_status,
    normalize_status,
    append_only_section_errors,
    run_tasks_validate,
    section_body,
    section_heading_count,
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
    assert section_body(sample, PROGRESS_SECTION) == "\n\na\n\n"
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
    nested = "## Progress\n\nfirst\n\n## Mid\n\nx\n\n## Progress\n\nsecond\n"
    assert section_body(nested, PROGRESS_SECTION) == "\n\nfirst\n\n"
    twin = "## Progress\n\nbody\n\n## Decision Log\n\nd1\n\n## Extra\n\ne\n"
    assert section_body(twin, PROGRESS_SECTION) == "\n\nbody\n\n"
    assert section_body(twin, DECISION_SECTION) == "\n\nd1\n\n"
    empty_prog = "## Progress\n## Decision Log\n\nx\n"
    assert section_body(empty_prog, PROGRESS_SECTION) == "\n"
    no_nl = "## Progress"
    assert section_body(no_nl, PROGRESS_SECTION) == ""


def test_section_heading_exact_match_oracles():
    """Only a whole-line ``## Progress`` / ``## Decision Log`` heading counts."""
    assert (
        MSG_PROGRESS_DUPLICATE
        == "duplicate ## Progress heading (append-only history must have one)"
    )
    assert (
        MSG_DECISION_DUPLICATE
        == "duplicate ## Decision Log heading (append-only history must have one)"
    )
    # Progressive / Decision Logs / inline / indented are not headings.
    assert section_heading_count("## Progressive\nx\n", PROGRESS_SECTION) == 0
    assert section_heading_count("## Progress Notes\n", PROGRESS_SECTION) == 0
    assert section_heading_count("## Decision Logs\n", DECISION_SECTION) == 0
    assert section_heading_count("goal: see ## Progress here\n", PROGRESS_SECTION) == 0
    assert section_heading_count("goal: ## Progress\n", PROGRESS_SECTION) == 0
    assert section_heading_count(" ## Progress\n", PROGRESS_SECTION) == 0
    assert section_heading_count("### Progress\n", PROGRESS_SECTION) == 0
    assert section_heading_count("x\n## Progress\n", PROGRESS_SECTION) == 1
    assert section_heading_count("## Progress", PROGRESS_SECTION) == 1
    assert section_heading_count("## Progress  \t\n", PROGRESS_SECTION) == 1
    assert section_heading_count("## Progress\r\nx\n", PROGRESS_SECTION) == 1
    assert section_heading_count("## Progress\n\n## Progress\n", PROGRESS_SECTION) == 2
    assert section_heading_count("## Decision Log\n## Decision Log\n", DECISION_SECTION) == 2
    # Inline / prefixed text before the real heading must not become the section.
    tricky = "goal ## Progress\n## Progressive\nx\n## Progress\n\nreal\n\n## Decision Log\n\nd\n"
    assert section_body(tricky, PROGRESS_SECTION) == "\n\nreal\n\n"
    # Heading-line trailing blanks are not part of the body.
    assert section_body("## Progress \t\nA\n## X\n", PROGRESS_SECTION) == "\nA\n"
    # Next boundary is an H2 only: ### stays inside the section.
    assert (
        section_body("## Progress\nA\n### sub\nB\n## X\n", PROGRESS_SECTION) == "\nA\n### sub\nB\n"
    )
    # Next boundary needs a space: ##X is body text.
    assert section_body("## Progress\nA\n##X\n## Y\n", PROGRESS_SECTION) == "\nA\n##X\n"


def test_section_separator_and_edge_prefix_oracles():
    base = "## Progress\n\n- a\n\n## Decision Log\n\n- d\n"
    assert section_body(base, PROGRESS_SECTION) == "\n\n- a\n\n"
    # delete separator blank + append → red (same content prefix, fewer separator newlines)
    assert (
        section_is_prefix(
            base, "## Progress\n\n- a\n- b\n## Decision Log\n\n- d\n", PROGRESS_SECTION
        )
        is False
    )
    # add extra separator blank → red
    assert (
        section_is_prefix(
            base, "## Progress\n\n- a\n- b\n\n\n## Decision Log\n\n- d\n", PROGRESS_SECTION
        )
        is False
    )
    # append keeping separator → green
    assert (
        section_is_prefix(
            base, "## Progress\n\n- a\n- b\n\n## Decision Log\n\n- d\n", PROGRESS_SECTION
        )
        is True
    )
    # separator removed, no append → red
    assert (
        section_is_prefix(base, "## Progress\n\n- a\n## Decision Log\n\n- d\n", PROGRESS_SECTION)
        is False
    )
    # section deleted → red
    assert section_is_prefix(base, "## Decision Log\n\n- d\n", PROGRESS_SECTION) is False
    # EOF section: raw prefix, appending with or without final newline stays green
    assert section_is_prefix(base, base + "- e\n", DECISION_SECTION) is True
    assert section_is_prefix(base, base + "- e", DECISION_SECTION) is True
    assert (
        section_is_prefix("## Decision Log\n- d", "## Decision Log\n- d\n- e\n", DECISION_SECTION)
        is True
    )
    # EOF section: delete blank + append → red
    eof_blank = "## Progress\n\n- a\n\n## Decision Log\n\n- d\n\n"
    assert (
        section_is_prefix(
            eof_blank, "## Progress\n\n- a\n\n## Decision Log\n\n- d\n- e\n", DECISION_SECTION
        )
        is False
    )
    # Empty bounded section: only blanks. Appending keeps whole blank run; shrinking it is red.
    empty = "## Progress\n\n## Decision Log\n\n- d\n"
    assert (
        section_is_prefix(empty, "## Progress\n\n- a\n\n## Decision Log\n\n- d\n", PROGRESS_SECTION)
        is True
    )
    assert (
        section_is_prefix(empty, "## Progress\n- a\n\n## Decision Log\n\n- d\n", PROGRESS_SECTION)
        is False
    )
    assert section_is_prefix(empty, empty, PROGRESS_SECTION) is True
    # Blank directly after heading is part of the prefix.
    assert (
        section_is_prefix(base, "## Progress\n- a\n\n## Decision Log\n\n- d\n", PROGRESS_SECTION)
        is False
    )
    # Only newlines are separator: trailing spaces / a final X belong to the protected content.
    spaced = "## Progress\n\n- a  \n\n## Decision Log\n\n- d\n"
    assert section_is_prefix(spaced, spaced.replace("- a  \n", "- a\n"), PROGRESS_SECTION) is False
    lettered = "## Progress\n\n- X\n\n## Decision Log\n\n- d\n"
    assert (
        section_is_prefix(lettered, lettered.replace("- X\n", "- Y\n"), PROGRESS_SECTION) is False
    )
    # Heading-trailing-space variant still matches the same section.
    assert (
        section_is_prefix(base, base.replace("## Progress", "## Progress  "), PROGRESS_SECTION)
        is True
    )


def test_append_only_section_errors_duplicates_exact():
    base = "## Progress\n\n- a\n\n## Decision Log\n\n- d\n"
    assert append_only_section_errors(base, base) == ()
    dup_prog = base + "\n## Progress\n\n- hidden\n"
    assert append_only_section_errors(base, dup_prog) == (MSG_PROGRESS_DUPLICATE,)
    dup_dec = base + "\n## Decision Log\n\n- hidden\n"
    assert append_only_section_errors(base, dup_dec) == (MSG_DECISION_DUPLICATE,)
    both = base + "\n## Progress\n\n- x\n\n## Decision Log\n\n- y\n"
    assert append_only_section_errors(base, both) == (
        MSG_PROGRESS_DUPLICATE,
        MSG_DECISION_DUPLICATE,
    )
    # Duplicate heading on HEAD fails even when base has no such section.
    assert append_only_section_errors("# t\n", "## Progress\n## Progress\n") == (
        MSG_PROGRESS_DUPLICATE,
    )
    # Duplicate wins; prefix error not stacked on the same section.
    broken_dup = "## Progress\n\nZ\n\n## Progress\n\n- a\n\n## Decision Log\n\n- d\n"
    assert append_only_section_errors(base, broken_dup) == (MSG_PROGRESS_DUPLICATE,)
    # Fake heading text inside goal does not hide a rewrite: Progress still compared.
    sneaky = "goal ## Progress\n## Progress\n\nZ\n\n## Decision Log\n\n- d\n"
    assert append_only_section_errors(base, sneaky) == (MSG_PROGRESS_PREFIX,)
    # Progressive heading is not Progress: base Progress missing in HEAD → red.
    renamed = base.replace("## Progress\n", "## Progressive\n")
    assert append_only_section_errors(base, renamed) == (MSG_PROGRESS_PREFIX,)


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
