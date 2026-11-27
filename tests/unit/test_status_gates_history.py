"""AGE-96: Progress / Decision Log exact-prefix gate across branch history (mutmut oracles)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentized.status_gates import (
    MSG_DECISION_PREFIX,
    MSG_GIT_ERROR,
    MSG_GIT_FAILED,
    MSG_HISTORY_BASE_DELETED,
    MSG_HISTORY_PAIR,
    MSG_HISTORY_RENAME,
    MSG_PROGRESS_PREFIX,
    MSG_TASK_DELETED,
    MSG_UNREADABLE,
    GateResult,
    branch_history_errors,
    previous_task_texts_from_git,
    run_tasks_validate,
    validate_tasks_dir,
)

NAME = "T-261127-hist.md"
REL = f"context/tasks/{NAME}"


def _git(root: Path, *args: str) -> str:
    cmd = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _doc(progress: list[str], decision: list[str] | None = None) -> str:
    prog = "".join(f"- {line}\n" for line in progress)
    dec = "".join(f"- {line}\n" for line in decision or [])
    return (
        "# T-261127-hist — history\n\nстатус: open\nтеги: t\nродитель: _(пусто)_\n"
        "claim: _(пусто)_\n\nЦенность: v\n\n## Цель\n\ng\n\n"
        f"## Progress\n\n_(append-only)_\n{prog}\n## Decision Log\n\n_(append-only)_\n{dec}"
    )


def _commit(root: Path, files: dict[str, str | bytes | None], msg: str) -> str:
    for rel, body in files.items():
        path = root / rel
        if body is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg)
    return _git(root, "rev-parse", "HEAD")


def _repo(
    tmp_path: Path, base_files: dict[str, str | None] | None = None
) -> tuple[Path, Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    base = _commit(
        root, {"README.md": "x\n", "context/tasks/INDEX.md": "i\n", **(base_files or {})}, "base"
    )
    return root, root / "context" / "tasks", base


def _msg(old: str, new: str, err: str) -> str:
    return MSG_HISTORY_PAIR.format(name=NAME, old=old[:7], new=new[:7], err=err)


def _bad_history(root: Path) -> tuple[str, str, str]:
    c1 = _commit(root, {REL: _doc(["A", "B"])}, "add")
    c2 = _commit(root, {REL: _doc(["A"])}, "delete B")
    c3 = _commit(root, {REL: _doc(["A", "C"])}, "append C")
    return c1, c2, c3


def _tip_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentized.tip_hygiene.validate_tip_hygiene", lambda *a, **k: GateResult(True)
    )


def test_message_constants_exact():
    assert MSG_HISTORY_PAIR == "{name}: branch history {old}..{new}: {err}"
    assert MSG_GIT_FAILED == "git {cmd} failed: {detail}"
    assert MSG_HISTORY_BASE_DELETED == (
        "task file present on base deleted in a branch commit; "
        "set статус: canceled instead of deleting (fail closed)"
    )
    assert MSG_HISTORY_RENAME == (
        "{old} -> {new}: branch history {parent}..{commit}: task file renamed or moved; "
        "history identity is lost (fail closed)"
    )


def test_delete_mid_branch_then_readd_other_lines_is_red(tmp_path: Path, monkeypatch):
    root, tasks, base = _repo(tmp_path)
    c1, c2, _c3 = _bad_history(root)
    expected = (_msg(c1, c2, MSG_PROGRESS_PREFIX),)
    assert branch_history_errors(tasks, repo_root=root, ref=base) == expected
    prev = previous_task_texts_from_git(tasks, repo_root=root, ref=base)
    assert validate_tasks_dir(tasks, previous_by_name=prev) == GateResult(True)
    _tip_ok(monkeypatch)
    ref, result = run_tasks_validate(tasks, repo_root=root, base_ref=base)
    assert ref == base
    assert result == GateResult(False, expected)


def test_delete_then_restore_file_on_base_is_red(tmp_path: Path):
    root, tasks, base = _repo(tmp_path, {REL: _doc(["A", "B"])})
    c1 = _commit(root, {REL: _doc(["A"])}, "delete B")
    _commit(root, {REL: _doc(["A", "B"])}, "restore B")
    assert (root / REL).read_text(encoding="utf-8") == _doc(["A", "B"])
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        _msg(base, c1, MSG_PROGRESS_PREFIX),
    )


def test_pure_appends_across_commits_are_green(tmp_path: Path, monkeypatch):
    root, tasks, base = _repo(tmp_path)
    _commit(root, {REL: _doc(["A"], ["d1"])}, "add")
    _commit(root, {REL: _doc(["A", "B"], ["d1"])}, "append progress")
    _commit(root, {REL: _doc(["A", "B"], ["d1", "d2"])}, "append decision")
    _commit(root, {REL: _doc(["A", "B", "C"], ["d1", "d2"])}, "append more")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == ()
    _tip_ok(monkeypatch)
    assert run_tasks_validate(tasks, repo_root=root, base_ref=base) == (base, GateResult(True))


def test_force_push_rewrite_to_clean_history_is_green(tmp_path: Path, monkeypatch):
    root, tasks, base = _repo(tmp_path)
    c1, c2, c3 = _bad_history(root)
    final = (root / REL).read_text(encoding="utf-8")
    assert final == _doc(["A", "C"])
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        _msg(c1, c2, MSG_PROGRESS_PREFIX),
    )
    _git(root, "reset", "-q", "--hard", base)
    d1 = _commit(root, {REL: _doc(["A"])}, "add clean")
    d2 = _commit(root, {REL: _doc(["A", "C"])}, "append C")
    assert {d1, d2}.isdisjoint({c1, c2, c3})
    assert (root / REL).read_text(encoding="utf-8") == final
    assert branch_history_errors(tasks, repo_root=root, ref=base) == ()
    _tip_ok(monkeypatch)
    assert run_tasks_validate(tasks, repo_root=root, base_ref=base) == (base, GateResult(True))


def test_decision_log_and_both_sections_report_exact_errors(tmp_path: Path):
    root, tasks, base = _repo(tmp_path)
    c1 = _commit(root, {REL: _doc(["A", "B"], ["d1", "d2"])}, "add")
    c2 = _commit(root, {REL: _doc(["A", "B"], ["d1"])}, "drop decision")
    c3 = _commit(root, {REL: _doc(["A"], ["d1", "x"])}, "drop progress and reword")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        _msg(c1, c2, MSG_DECISION_PREFIX),
        _msg(c2, c3, MSG_PROGRESS_PREFIX),
    )
    c4 = _commit(root, {REL: _doc(["Z"], ["d1"])}, "break both")
    assert branch_history_errors(tasks, repo_root=root, ref=base)[2:] == (
        _msg(c3, c4, MSG_PROGRESS_PREFIX),
        _msg(c3, c4, MSG_DECISION_PREFIX),
    )


def test_only_task_files_in_tasks_dir_are_judged(tmp_path: Path):
    root, tasks, base = _repo(tmp_path)
    big, small = _doc(["A", "B"]), _doc(["A"])
    real = "context/tasks/T-zzz.md"
    others = [
        "context/tasks/INDEX.md",
        "context/tasks/T-note.txt",
        "context/tasks/notes-T-x.md",
        "docs/T-outside.md",
    ]
    c1 = _commit(root, {rel: big for rel in [*others, real]}, "add")
    c2 = _commit(root, {rel: small for rel in [*others, real]}, "shrink")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        MSG_HISTORY_PAIR.format(name="T-zzz.md", old=c1[:7], new=c2[:7], err=MSG_PROGRESS_PREFIX),
    )


def test_every_changed_task_file_in_a_commit_is_judged(tmp_path: Path):
    root, tasks, base = _repo(tmp_path)
    a, b = "context/tasks/T-a.md", "context/tasks/T-b.md"
    c1 = _commit(root, {a: _doc(["A", "B"]), b: _doc(["A", "B"])}, "add both")
    c2 = _commit(root, {a: None, b: _doc(["A"])}, "delete a, shrink b")
    c3 = _commit(root, {a: _doc(["A", "B"], ["d"]), b: _doc(["A", "C"])}, "re-add a, append b")
    c4 = _commit(root, {a: _doc(["A", "B", "C"], ["d"]), b: _doc(["Z"])}, "mixed")
    pair = MSG_HISTORY_PAIR
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        pair.format(name="T-b.md", old=c1[:7], new=c2[:7], err=MSG_PROGRESS_PREFIX),
        pair.format(name="T-b.md", old=c3[:7], new=c4[:7], err=MSG_PROGRESS_PREFIX),
    )


def test_merge_commits_are_not_pair_endpoints_but_successors_are(tmp_path: Path):
    root, tasks, base = _repo(tmp_path, {REL: _doc(["A"])})
    _git(root, "checkout", "-q", "-b", "side")
    _commit(root, {REL: _doc(["A", "S"])}, "side append")
    _git(root, "checkout", "-q", "-")
    f1 = _commit(root, {REL: _doc(["A", "B"])}, "feature append")
    _git(root, "merge", "-q", "--no-commit", "--no-ff", "-s", "ours", "side")
    merged = _commit(root, {REL: _doc(["A", "S", "B"])}, "merge, concurrent appends reordered")
    assert len(_git(root, "rev-list", "--parents", "-n1", merged).split()) == 3
    assert not _doc(["A", "S", "B"]).startswith(_doc(["A", "B"])[: -len("\n## Decision Log\n")])
    assert f1 != merged
    assert branch_history_errors(tasks, repo_root=root, ref=base) == ()
    _commit(root, {REL: _doc(["A", "S", "B", "C"])}, "append after merge")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == ()
    after = _commit(root, {REL: _doc(["A", "B", "C"])}, "drop S")
    assert branch_history_errors(tasks, repo_root=root, ref=base)[-1:] == (
        _msg(_git(root, "rev-parse", "HEAD~1"), after, MSG_PROGRESS_PREFIX),
    )


def test_delete_file_then_readd_shorter_is_red(tmp_path: Path):
    root, tasks, base = _repo(tmp_path)
    _commit(root, {REL: _doc(["A", "B"])}, "add")
    c2 = _commit(root, {REL: None}, "delete file")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == ()
    c3 = _commit(root, {REL: _doc(["A"])}, "re-add shorter")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        _msg(c2, c3, MSG_PROGRESS_PREFIX),
    )


def test_root_commit_in_range_has_no_pair_but_successors_do(tmp_path: Path):
    root, tasks, base = _repo(tmp_path)
    _git(root, "checkout", "-q", "--orphan", "unrelated")
    r1 = _commit(root, {REL: _doc(["A", "B"])}, "root")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == ()
    r2 = _commit(root, {REL: _doc(["A"])}, "shrink")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        _msg(r1, r2, MSG_PROGRESS_PREFIX),
    )


def test_run_tasks_validate_orders_gate_history_tip_errors(tmp_path: Path, monkeypatch):
    import agentized.status_gates as sg

    seen: list[tuple] = []
    monkeypatch.setattr(sg, "resolve_validate_base_ref", lambda root, *, explicit=None: "BASE")
    monkeypatch.setattr(sg, "require_base_before_head", lambda *a: None)
    monkeypatch.setattr(sg, "previous_task_texts_from_git", lambda *a, **k: {})
    monkeypatch.setattr(sg, "validate_tasks_dir", lambda *a, **k: GateResult(False, ("g",)))

    def fake_history(tasks_dir, *, repo_root, ref):
        seen.append((tasks_dir, repo_root, ref))
        return ("h",)

    monkeypatch.setattr(sg, "branch_history_errors", fake_history)
    monkeypatch.setattr(
        "agentized.tip_hygiene.validate_tip_hygiene",
        lambda *a, **k: GateResult(False, ("t",)),
    )
    tasks = tmp_path / "context" / "tasks"
    assert run_tasks_validate(tasks, repo_root=tmp_path) == (
        "BASE",
        GateResult(False, ("g", "h", "t")),
    )
    assert seen == [(tasks, tmp_path, "BASE")]
    monkeypatch.setattr(sg, "validate_tasks_dir", lambda *a, **k: GateResult(True))
    monkeypatch.setattr(sg, "branch_history_errors", lambda *a, **k: ("h",))
    monkeypatch.setattr(
        "agentized.tip_hygiene.validate_tip_hygiene", lambda *a, **k: GateResult(True)
    )
    assert run_tasks_validate(tasks, repo_root=tmp_path)[1] == GateResult(False, ("h",))


def test_unreadable_history_fails_closed_with_exact_messages(tmp_path: Path, monkeypatch):
    root, tasks, base = _repo(tmp_path)
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--parents", "--topo-order", "--reverse"]
        + ["no-such-ref..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    detail = (probe.stderr or probe.stdout).strip()
    assert detail
    with pytest.raises(RuntimeError) as bad_ref:
        branch_history_errors(tasks, repo_root=root, ref="no-such-ref")
    assert str(bad_ref.value) == MSG_GIT_FAILED.format(cmd="rev-list", detail=detail)

    other = tmp_path / "elsewhere"
    other.mkdir()
    with pytest.raises(RuntimeError) as outside:
        branch_history_errors(other, repo_root=root, ref=base)
    with pytest.raises(ValueError) as ve:
        other.resolve().relative_to(root.resolve())
    assert str(outside.value) == MSG_GIT_ERROR.format(
        rel="elsewhere", ref=base, detail=str(ve.value)
    )

    bad = b"- \xff\xfe\n"
    c1 = _commit(root, {REL: bad}, "not utf-8")
    with pytest.raises(UnicodeDecodeError) as ue:
        bad.decode("utf-8")
    with pytest.raises(RuntimeError) as nonutf:
        branch_history_errors(tasks, repo_root=root, ref=base)
    assert str(nonutf.value) == f"{REL}@{c1}: {MSG_UNREADABLE.format(detail=ue.value)}"
    _commit(root, {REL: _doc(["A"])}, "fix")

    real_run = subprocess.run

    def with_show(show):
        def fake(argv, **kwargs):
            return show(argv, kwargs) if "show" in argv else real_run(argv, **kwargs)

        return fake

    def failing(stderr: bytes):
        def show(argv, kwargs):
            assert kwargs == {"capture_output": True, "check": False}
            assert argv[:4] == ["git", "-C", str(root), "show"]
            return SimpleNamespace(returncode=128, stdout=b"", stderr=stderr)

        return show

    for stderr, expected in (
        (b"fatal: bad object\n", "fatal: bad object"),
        (b"fatal: bad \xff object", "fatal: bad \ufffd object"),
        (b"", "exit 128"),
    ):
        monkeypatch.setattr(subprocess, "run", with_show(failing(stderr)))
        with pytest.raises(RuntimeError) as show_err:
            branch_history_errors(tasks, repo_root=root, ref=base)
        assert str(show_err.value) == MSG_GIT_ERROR.format(rel=REL, ref=base, detail=expected)

    def boom(argv, kwargs):
        raise OSError("show-boom")

    monkeypatch.setattr(subprocess, "run", with_show(boom))
    with pytest.raises(RuntimeError) as show_os:
        branch_history_errors(tasks, repo_root=root, ref=base)
    assert str(show_os.value) == MSG_GIT_ERROR.format(rel=REL, ref=base, detail="show-boom")

    def rev_boom(argv, **kwargs):
        raise OSError("rev-boom")

    monkeypatch.setattr(subprocess, "run", rev_boom)
    with pytest.raises(RuntimeError) as rev_os:
        branch_history_errors(tasks, repo_root=root, ref=base)
    assert str(rev_os.value) == MSG_GIT_FAILED.format(cmd="rev-list", detail="rev-boom")


OTHER = "T-261127-moved.md"
OTHER_REL = f"context/tasks/{OTHER}"
LONG = [f"entry {n} with enough text to keep similarity high" for n in range(8)]


def _rename_msg(old: str, new: str, parent: str, commit: str) -> str:
    return MSG_HISTORY_RENAME.format(old=old, new=new, parent=parent[:7], commit=commit[:7])


def test_branch_only_task_renamed_and_rewritten_is_red(tmp_path: Path, monkeypatch):
    root, tasks, base = _repo(tmp_path)
    c1 = _commit(root, {REL: _doc(LONG)}, "add")
    c2 = _commit(root, {REL: None, OTHER_REL: _doc(LONG[:2])}, "rename and wipe prefix")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        _rename_msg(REL, OTHER_REL, c1, c2),
    )
    prev = previous_task_texts_from_git(tasks, repo_root=root, ref=base)
    assert validate_tasks_dir(tasks, previous_by_name=prev) == GateResult(True)
    _tip_ok(monkeypatch)
    assert run_tasks_validate(tasks, repo_root=root, base_ref=base)[1] == GateResult(
        False, (_rename_msg(REL, OTHER_REL, c1, c2),)
    )


def test_base_task_renamed_is_red_by_deletion_and_by_history(tmp_path: Path, monkeypatch):
    root, tasks, base = _repo(tmp_path, {REL: _doc(LONG)})
    c1 = _commit(root, {REL: None, OTHER_REL: _doc(LONG)}, "rename")
    expected_history = (_rename_msg(REL, OTHER_REL, base, c1),)
    assert branch_history_errors(tasks, repo_root=root, ref=base) == expected_history
    prev = previous_task_texts_from_git(tasks, repo_root=root, ref=base)
    assert validate_tasks_dir(tasks, previous_by_name=prev) == GateResult(
        False, (f"{NAME}: {MSG_TASK_DELETED}",)
    )
    _tip_ok(monkeypatch)
    assert run_tasks_validate(tasks, repo_root=root, base_ref=base)[1] == GateResult(
        False, (f"{NAME}: {MSG_TASK_DELETED}",) + expected_history
    )


def test_rename_to_or_from_non_task_name_is_red_but_non_task_rename_is_ignored(tmp_path: Path):
    plain = "context/tasks/notes.txt"
    plain2 = "context/tasks/notes-2.txt"
    root, tasks, base = _repo(tmp_path, {REL: _doc(LONG), plain: _doc(LONG)})
    c1 = _commit(root, {plain: None, plain2: _doc(LONG)}, "rename non-task")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == ()
    c2 = _commit(root, {REL: None, plain: _doc(LONG)}, "task to non-task")
    c3 = _commit(root, {plain2: None, OTHER_REL: _doc(LONG)}, "non-task to task")
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        _rename_msg(REL, plain, c1, c2),
        _rename_msg(plain2, OTHER_REL, c2, c3),
    )


def test_entries_around_a_rename_in_the_same_commit_are_still_judged(tmp_path: Path):
    first, last = "T-261127-aaaa", "T-261127-zzzz"
    src = "context/tasks/T-261127-qqqq.md"
    root, tasks, base = _repo(
        tmp_path,
        {
            src: _doc(LONG),
            f"context/tasks/{first}.md": _doc(["A"]),
            f"context/tasks/{last}.md": _doc(["A", "B"]),
        },
    )
    _commit(root, {OTHER_REL: _doc(LONG)}, "add branch-only target")
    c1 = _commit(root, {OTHER_REL: None}, "free the target name")
    c2 = _commit(
        root,
        {
            f"context/tasks/{first}.md": _doc(["A", "C"]),
            src: None,
            OTHER_REL: _doc(LONG[:2]),
            f"context/tasks/{last}.md": _doc(["A"]),
        },
        "append aaaa, rename qqqq onto freed name, shrink zzzz",
    )
    assert branch_history_errors(tasks, repo_root=root, ref=base) == (
        _rename_msg(src, OTHER_REL, c1, c2),
        f"{last}.md: branch history {c1[:7]}..{c2[:7]}: {MSG_PROGRESS_PREFIX}",
    )


def test_base_task_deleted_mid_branch_and_restored_identically_is_red(tmp_path: Path, monkeypatch):
    root, tasks, base = _repo(tmp_path, {REL: _doc(LONG)})
    c1 = _commit(root, {REL: None}, "delete base task")
    _commit(root, {REL: _doc(LONG)}, "restore identical")
    assert (root / REL).read_text(encoding="utf-8") == _doc(LONG)
    expected = (_msg(base, c1, MSG_HISTORY_BASE_DELETED),)
    assert branch_history_errors(tasks, repo_root=root, ref=base) == expected
    prev = previous_task_texts_from_git(tasks, repo_root=root, ref=base)
    assert validate_tasks_dir(tasks, previous_by_name=prev) == GateResult(True)
    _tip_ok(monkeypatch)
    assert run_tasks_validate(tasks, repo_root=root, base_ref=base)[1] == GateResult(
        False, expected
    )


def test_base_task_replaced_by_dissimilar_file_then_restored_is_red(tmp_path: Path, monkeypatch):
    root, tasks, base = _repo(tmp_path, {REL: _doc(LONG)})
    c1 = _commit(
        root,
        {REL: None, OTHER_REL: _doc([f"unrelated {n * 9973}" for n in range(40)])},
        "delete and add dissimilar",
    )
    status = _git(root, "diff", "--name-status", "-M", base, c1, "--", "context/tasks")
    assert status.splitlines() == [f"D\t{REL}", f"A\t{OTHER_REL}"]
    _commit(root, {REL: _doc(LONG)}, "restore original path")
    expected = (_msg(base, c1, MSG_HISTORY_BASE_DELETED),)
    assert branch_history_errors(tasks, repo_root=root, ref=base) == expected
    prev = previous_task_texts_from_git(tasks, repo_root=root, ref=base)
    assert validate_tasks_dir(tasks, previous_by_name=prev) == GateResult(True)
    _tip_ok(monkeypatch)
    assert run_tasks_validate(tasks, repo_root=root, base_ref=base)[1] == GateResult(
        False, expected
    )


def test_deleting_branch_only_task_is_green_and_base_files_stay_untouched(tmp_path: Path):
    root, tasks, base = _repo(tmp_path, {OTHER_REL: _doc(LONG)})
    _commit(root, {REL: _doc(LONG)}, "add branch-only")
    _commit(root, {REL: None}, "delete branch-only")
    assert not (root / REL).exists()
    assert branch_history_errors(tasks, repo_root=root, ref=base) == ()
