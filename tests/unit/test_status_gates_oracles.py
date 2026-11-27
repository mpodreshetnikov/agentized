"""Mutation oracles for status_gates.py (mutmut test_status_gates_*.py)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from agentized.status_gates import (
    ALL_STATUSES,
    CANONICAL_STATUSES,
    DECISION_SECTION,
    INDEX_ACTIVE_STATUSES,
    MSG_BASE_NOT_BEFORE_HEAD,
    MSG_BASE_UNRESOLVED,
    MSG_DECISION_DUPLICATE,
    MSG_DECISION_PREFIX,
    MSG_PROGRESS_DUPLICATE,
    MSG_PROGRESS_PREFIX,
    MSG_TASK_DELETED,
    MSG_UNKNOWN_STATUS,
    PROGRESS_SECTION,
    STATUS_ALIASES,
    GateResult,
    append_only_section_errors,
    is_known_status,
    normalize_status,
    require_base_before_head,
    resolve_validate_base_ref,
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
    monkeypatch.setattr(sg, "require_base_before_head", lambda *a: None)
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


def test_last_line_is_frozen_exact_oracles():
    """Whatever follows the last base line must start on a new line (no suffix / trailing blanks)."""
    base = "## Progress\n\n- a\n\n## Decision Log\n\n- d\n"
    head = "## Progress\n\n- a{x}\n\n## Decision Log\n\n- d\n"
    assert section_is_prefix(base, head.format(x=""), PROGRESS_SECTION) is True
    assert section_is_prefix(base, head.format(x="b"), PROGRESS_SECTION) is False
    assert section_is_prefix(base, head.format(x=" "), PROGRESS_SECTION) is False
    assert section_is_prefix(base, head.format(x="  \t"), PROGRESS_SECTION) is False
    assert section_is_prefix(base, head.format(x="\n- b"), PROGRESS_SECTION) is True
    assert section_is_prefix(base, head.format(x="\n\n- b"), PROGRESS_SECTION) is True
    assert append_only_section_errors(base, head.format(x="b")) == (MSG_PROGRESS_PREFIX,)
    assert append_only_section_errors(base, head.format(x=" ")) == (MSG_PROGRESS_PREFIX,)
    assert append_only_section_errors(base, head.format(x="\n- b")) == ()
    # EOF section (Decision Log last): same freeze, with or without a final newline.
    eof = "## Decision Log\n\n- d"
    assert section_is_prefix(eof, eof, DECISION_SECTION) is True
    assert section_is_prefix(eof, eof + "x", DECISION_SECTION) is False
    assert section_is_prefix(eof, eof + " ", DECISION_SECTION) is False
    assert section_is_prefix(eof, eof + "\n- e\n", DECISION_SECTION) is True
    assert section_is_prefix(eof, eof + "\n", DECISION_SECTION) is True
    assert section_is_prefix(eof + "\n", eof + "\n- e", DECISION_SECTION) is True
    assert section_is_prefix("## Decision Log", "## Decision Log\n- e", DECISION_SECTION) is True
    assert section_is_prefix("## Decision Log", "## Decision Log", DECISION_SECTION) is True


def _git(root: Path, *args: str) -> str:
    cmd = ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args]
    return subprocess.run(cmd, cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _task_text(progress_line: str) -> str:
    return (
        "# T-261121-hist — history\n\nстатус: open\nтеги: t\nродитель: _(пусто)_\n"
        "claim: _(пусто)_\n\nЦенность: v\n\n## Цель\n\ng\n\n## Progress\n\n"
        f"_(append-only)_\n- {progress_line}\n\n## Decision Log\n\n_(append-only)_\n"
    )


def _history_repo(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """Return (root, tasks, base_sha, head_sha); head rewrites the base Progress line."""
    root = tmp_path / "repo"
    tasks = root / "context" / "tasks"
    tasks.mkdir(parents=True)
    root.joinpath("README.md").write_text("x\n", encoding="utf-8")
    _git(root, "init", "-q")
    task = tasks / "T-261121-hist.md"
    task.write_text(_task_text("original"), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/main", base)
    task.write_text(_task_text("REWRITTEN"), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "rewrite")
    return root, tasks, base, _git(root, "rev-parse", "HEAD")


def test_resolve_ignores_env_and_guards_head_base(tmp_path: Path, monkeypatch):
    root, tasks, base, head = _history_repo(tmp_path)
    for var in ("MUTATION_BASE", "TASKS_VALIDATE_BASE"):
        monkeypatch.delenv("MUTATION_BASE", raising=False)
        monkeypatch.delenv("TASKS_VALIDATE_BASE", raising=False)
        monkeypatch.setenv(var, "HEAD")
        assert resolve_validate_base_ref(root) == base
        monkeypatch.setenv(var, head)
        assert resolve_validate_base_ref(root) == base
        ref, result = run_tasks_validate(tasks, repo_root=root)
        assert ref == base
        assert result.ok is False
        assert any(MSG_PROGRESS_PREFIX in e for e in result.errors)
    monkeypatch.delenv("TASKS_VALIDATE_BASE", raising=False)
    monkeypatch.delenv("MUTATION_BASE", raising=False)

    assert resolve_validate_base_ref(root, explicit="X") == "X"
    for bad in ("HEAD", head, "@"):
        with pytest.raises(RuntimeError) as exc:
            run_tasks_validate(tasks, repo_root=root, base_ref=bad)
        assert str(exc.value) == MSG_BASE_NOT_BEFORE_HEAD.format(ref=bad)
    require_base_before_head(root, base)
    _git(root, "checkout", "-q", "-b", "later")
    (root / "later.txt").write_text("l\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "later")
    later = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", head)
    with pytest.raises(RuntimeError) as exc2:
        require_base_before_head(root, later)
    assert str(exc2.value) == MSG_BASE_NOT_BEFORE_HEAD.format(ref=later)
    with pytest.raises(RuntimeError) as exc3:
        require_base_before_head(root, "no-such-ref")
    assert str(exc3.value).startswith(
        MSG_BASE_UNRESOLVED.format(ref="no-such-ref", detail="").rstrip()
    )
    assert "no-such-ref" in str(exc3.value)


def test_main_push_uses_first_parent_not_head(tmp_path: Path):
    root, tasks, base, head = _history_repo(tmp_path)
    _git(root, "update-ref", "refs/remotes/origin/main", head)
    assert resolve_validate_base_ref(root) == base
    ref, result = run_tasks_validate(tasks, repo_root=root)
    assert ref == base
    assert result.ok is False
    # Single-commit repo: nothing earlier than HEAD → fail closed.
    solo = tmp_path / "solo"
    (solo / "context" / "tasks").mkdir(parents=True)
    (solo / "context" / "tasks" / "T-261121-hist.md").write_text(_task_text("a"), encoding="utf-8")
    _git(solo, "init", "-q")
    _git(solo, "add", "-A")
    _git(solo, "commit", "-qm", "only")
    only = _git(solo, "rev-parse", "HEAD")
    _git(solo, "update-ref", "refs/remotes/origin/main", only)
    assert resolve_validate_base_ref(solo) == only
    with pytest.raises(RuntimeError) as exc:
        run_tasks_validate(solo / "context" / "tasks", repo_root=solo)
    assert str(exc.value) == MSG_BASE_NOT_BEFORE_HEAD.format(ref=only)


def test_resolve_git_oserror_message(tmp_path: Path, monkeypatch):
    def boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError) as exc:
        resolve_validate_base_ref(tmp_path)
    assert str(exc.value) == "git merge-base failed: boom"
    with pytest.raises(RuntimeError) as exc2:
        require_base_before_head(tmp_path, "main")
    assert str(exc2.value) == MSG_BASE_UNRESOLVED.format(ref="main", detail="boom")
