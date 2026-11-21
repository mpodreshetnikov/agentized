"""Hard status gates (AGE-22/49)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agentized.status_gates import (
    ALLOWED_TRANSITIONS,
    MSG_BAD_PR,
    MSG_BLOCKED_DEADLINE,
    MSG_BLOCKED_DEADLINE_FMT,
    MSG_BLOCKED_DEADLINE_INVALID,
    MSG_BLOCKED_REASON,
    MSG_DONE_EVIDENCE,
    MSG_DUPLICATE_FIELD,
    MSG_GIT_ERROR,
    MSG_ILLEGAL,
    MSG_MISSING_STATUS,
    MSG_MISSING_VALUE,
    MSG_NEW_PATH,
    MSG_REVIEW_EVIDENCE,
    MSG_TASK_DELETED,
    MSG_UNKNOWN_NEW,
    MSG_UNKNOWN_OLD,
    MSG_UNKNOWN_STATUS,
    MSG_UNREADABLE,
    NEW_PATH_ALLOWED_STATUSES,
    GateResult,
    _cmd_detail,
    _git_err,
    _git_missing_path,
    duplicate_field_errors,
    extract_status,
    has_value_line,
    is_known_status,
    is_real_pr_ref,
    normalize_status,
    header_block,
    parse_task_fields,
    previous_task_texts_from_git,
    resolve_validate_base_ref,
    run_tasks_validate,
    validate_status_requirements,
    validate_task_file,
    validate_task_text,
    validate_tasks_dir,
    validate_transition,
)


def _task(status: str, *, value: bool = True, extra: str = "", body: str = "") -> str:
    lines = [
        "# T-261116-test — Demo",
        "",
        f"статус: {status}",
        "теги: t",
        "родитель: _(пусто)_",
        "claim: _(пусто)_",
    ]
    if extra:
        lines.append(extra.rstrip())
    lines.append("")
    if value:
        lines.extend(["Ценность: люди видят доску без harness", ""])
    lines.append("## Цель\n\nGoal.\n")
    if body:
        lines.append(body)
    return "\n".join(lines) + "\n"


def test_normalize_extract_empty_refuse():
    assert normalize_status("Dropped") == "canceled"
    assert normalize_status("queued") == "queue"
    assert normalize_status("") == normalize_status(None) == ""
    assert has_value_line("Ценность: x") is True
    assert has_value_line("Ценность: _(пусто)_") is False
    assert has_value_line("value: x") is has_value_line("") is has_value_line(None) is False
    text = _task("in-progress")
    assert parse_task_fields(text)["статус"] == extract_status(text) == "in-progress"
    assert extract_status("# only title\n\nЦенность: x\n") == ""
    assert extract_status("") == extract_status("статус:   \n") == ""
    assert parse_task_fields("") == parse_task_fields(None) == {}
    assert duplicate_field_errors("") == duplicate_field_errors(None) == ()
    bare = "# T-261116-x — X\n\nЦенность: v\n"
    assert validate_task_text(bare, check_transition=False) == GateResult(
        False, (MSG_MISSING_STATUS,)
    )
    blank = _task("open").replace("статус: open", "статус:   ")
    assert validate_task_text(blank, check_transition=False) == GateResult(
        False, (MSG_MISSING_STATUS,)
    )
    assert validate_status_requirements(bare) == GateResult(False, (MSG_MISSING_STATUS,))
    assert (
        validate_transition("", "open")
        == validate_transition("open", "")
        == GateResult(False, (MSG_MISSING_STATUS,))
    )


def test_transition_matrix_pass_fail():
    assert validate_transition("open", "in-progress") == GateResult(True)
    assert validate_transition("in-progress", "self-review") == GateResult(True)
    bad = validate_transition("open", "done")
    assert bad == GateResult(
        False,
        (MSG_ILLEGAL.format(old="open", new="done", allowed=sorted(ALLOWED_TRANSITIONS["open"])),),
    )
    assert validate_transition("done", "canceled").ok is False
    assert validate_transition("open", "open") == GateResult(True)
    for old, news in ALLOWED_TRANSITIONS.items():
        for new in news:
            assert validate_transition(old, new) == GateResult(True), f"{old}->{new}"
    assert sum(len(v) for v in ALLOWED_TRANSITIONS.values()) == 37


def test_blocked_and_calendar():
    assert validate_status_requirements(_task("blocked")) == GateResult(
        False, (MSG_BLOCKED_REASON, MSG_BLOCKED_DEADLINE)
    )
    placeholders = _task("blocked", extra="blocked_reason: _(пусто)_\nblocked_deadline: _(пусто)_")
    assert validate_status_requirements(placeholders) == GateResult(
        False, (MSG_BLOCKED_REASON, MSG_BLOCKED_DEADLINE)
    )
    assert validate_status_requirements(
        _task("blocked", extra="blocked_reason: wait\nblocked_deadline: soon")
    ) == GateResult(False, (MSG_BLOCKED_DEADLINE_FMT.format(deadline="soon"),))
    assert validate_status_requirements(
        _task(
            "blocked",
            extra="blocked_reason: waiting API\nblocked_deadline: 2026-12-01",
        )
    ) == GateResult(True)
    assert validate_status_requirements(
        _task("blocked", extra="blocked_reason: x\nblocked_deadline: 2026-13-40")
    ) == GateResult(False, (MSG_BLOCKED_DEADLINE_INVALID.format(deadline="2026-13-40"),))


def test_review_pr_and_done_fields():
    for st in ("self-review", "for-review"):
        assert validate_status_requirements(_task(st)) == GateResult(
            False, (MSG_REVIEW_EVIDENCE.format(st=st),)
        )
        assert validate_status_requirements(
            _task(st, extra="review_note: checklist complete")
        ) == GateResult(True)
        assert validate_status_requirements(_task(st, extra="pr: #25")) == GateResult(True)
        assert validate_status_requirements(_task(st, extra="pr: PR #25")) == GateResult(True)
        assert validate_status_requirements(
            _task(st, extra="pr: https://github.com/mpodreshetnikov/agentized/pull/25")
        ) == GateResult(True)
        assert validate_status_requirements(
            _task(st, body="See https://github.com/o/r/pull/1\n")
        ) == GateResult(False, (MSG_REVIEW_EVIDENCE.format(st=st),))
        assert validate_status_requirements(_task(st, extra="pr: ready-for-lead")) == GateResult(
            False,
            (MSG_BAD_PR.format(pr="ready-for-lead"), MSG_REVIEW_EVIDENCE.format(st=st)),
        )
        assert validate_status_requirements(
            _task(st, extra="review_note: _(пусто)_")
        ) == GateResult(False, (MSG_REVIEW_EVIDENCE.format(st=st),))
    assert validate_status_requirements(_task("done")) == GateResult(False, (MSG_DONE_EVIDENCE,))
    assert validate_status_requirements(
        _task("done", extra="acceptance_note: lead signed off")
    ) == GateResult(True)
    assert validate_status_requirements(_task("done", extra="review_note: ship it")) == GateResult(
        False, (MSG_DONE_EVIDENCE,)
    )
    assert validate_status_requirements(_task("done", extra="pr: #3")) == GateResult(
        False, (MSG_DONE_EVIDENCE,)
    )
    assert is_real_pr_ref("#12") is is_real_pr_ref("PR #12") is True
    assert is_real_pr_ref("https://github.com/o/r/pull/12") is True
    assert is_real_pr_ref("https://example.com/x") is is_real_pr_ref("merged") is False
    assert is_real_pr_ref("") is is_real_pr_ref("_(пусто)_") is is_real_pr_ref(None) is False


def test_value_transition_file_dir(tmp_path: Path):
    text = _task("open", value=False)
    assert validate_task_text(text, check_transition=False) == GateResult(
        False, (MSG_MISSING_VALUE,)
    )
    path = tmp_path / "T-261116-abc.md"
    path.write_text(_task("open"), encoding="utf-8")
    old = path.read_text(encoding="utf-8")
    bad = _task("done", extra="acceptance_note: lead signed off")
    bad_r = validate_task_text(bad, old_status="open")
    assert bad_r.ok is False
    assert bad_r.errors[0].startswith("illegal transition open → done")
    blocked = _task("open").replace("статус: open", "статус: blocked", 1)
    assert validate_task_text(blocked, old_status="open") == GateResult(
        False, (MSG_BLOCKED_REASON, MSG_BLOCKED_DEADLINE)
    )
    good_blocked = _task("blocked", extra="blocked_reason: dep\nblocked_deadline: 2026-11-20")
    assert validate_task_text(good_blocked, old_status="open") == GateResult(True)
    path.write_text(good_blocked, encoding="utf-8")
    assert validate_task_file(path, old_text=old) == GateResult(True)

    (tmp_path / "T-261116-aaa.md").write_text(_task("open"), encoding="utf-8")
    bbb = tmp_path / "T-261116-bbb.md"
    bbb.write_text(_task("done"), encoding="utf-8")
    assert validate_tasks_dir(tmp_path) == GateResult(
        False, (f"T-261116-bbb.md: {MSG_DONE_EVIDENCE}",)
    )
    bbb.write_text(_task("done", extra="acceptance_note: lead signed off"), encoding="utf-8")
    assert validate_tasks_dir(tmp_path) == GateResult(True)
    (tmp_path / "T-261116-ccc.md").write_text(_task("open", value=False), encoding="utf-8")
    assert validate_tasks_dir(tmp_path) == GateResult(
        False, (f"T-261116-ccc.md: {MSG_MISSING_VALUE}",)
    )


def test_unknown_and_gate_message():
    text = _task("open").replace("статус: open", "статус: flying")
    assert validate_task_text(text, check_transition=False) == GateResult(
        False, (MSG_UNKNOWN_STATUS.format(st="flying"),)
    )
    assert validate_transition("open", "flying") == GateResult(
        False, (MSG_UNKNOWN_NEW.format(new="flying"),)
    )
    assert validate_status_requirements(text) == GateResult(
        False, (MSG_UNKNOWN_STATUS.format(st="flying"),)
    )
    assert validate_transition("flying", "open") == GateResult(
        False, (MSG_UNKNOWN_OLD.format(old="flying"),)
    )
    assert GateResult(True).message == ""
    assert GateResult(False, ("a", "b")).message == "a; b"
    assert is_known_status("open") is True
    assert is_known_status("Dropped") is is_known_status("queued") is True
    assert is_known_status(None) is is_known_status("") is is_known_status("  ") is False
    assert is_known_status("flying") is False


def test_header_only_and_new_path(tmp_path: Path):
    end_status = "# T-261116-x — X\n\nЦенность: v\n\n## Цель\n\ng\n\n## Progress\n\nстатус: open\n"
    assert "статус: open" not in header_block(end_status)
    assert header_block("## Цель\n\nx\n") == ""
    multi = "# T\n\nстатус: open\n\n## Цель\n\ng\n\n## Progress\n\nnote\n"
    assert header_block(multi) == "# T\n\nстатус: open\n"
    assert extract_status(end_status) == ""
    assert validate_task_text(end_status) == GateResult(False, (MSG_MISSING_STATUS,))
    body_note = _task("self-review").rstrip() + "\n## Progress\n\nreview_note: buried\n"
    assert validate_status_requirements(body_note) == GateResult(
        False, (MSG_REVIEW_EVIDENCE.format(st="self-review"),)
    )
    dup = _task("open").replace("claim: _(пусто)_\n", "claim: _(пусто)_\nстатус: open\n", 1)
    dups = (MSG_DUPLICATE_FIELD.format(key="статус"),)
    assert duplicate_field_errors(dup) == dups
    assert validate_status_requirements(dup) == GateResult(False, dups)
    assert validate_task_text(dup, check_transition=False) == GateResult(False, dups)
    assert duplicate_field_errors(_task("open") + "статус: open\n") == ()
    twin_val = _task("open").replace(
        "Ценность: люди видят доску без harness\n",
        "Ценность: люди видят доску без harness\nЦенность: other\n",
        1,
    )
    assert MSG_DUPLICATE_FIELD.format(key="Ценность") in duplicate_field_errors(twin_val)
    assert NEW_PATH_ALLOWED_STATUSES == frozenset({"idea", "open", "queue", "in-progress"})
    fresh = tmp_path / "brand"
    fresh.mkdir()
    (fresh / "T-261116-newdone.md").write_text(
        _task("done", extra="acceptance_note: forged"), encoding="utf-8"
    )
    (fresh / "T-261116-newsr-bad.md").write_text(
        _task("self-review", extra="review_note: ok"), encoding="utf-8"
    )
    (fresh / "T-261116-newsr-ok.md").write_text(
        _task("self-review", extra="pr: #25\nreview_note: ready"), encoding="utf-8"
    )
    (fresh / "T-261116-newblocked.md").write_text(
        _task("blocked", extra="blocked_reason: x\nblocked_deadline: 2026-12-01"),
        encoding="utf-8",
    )
    (fresh / "T-261116-ok.md").write_text(_task("open"), encoding="utf-8")
    bad_new = validate_tasks_dir(fresh, previous_by_name={})
    assert any(MSG_NEW_PATH.format(st="done") in e for e in bad_new.errors)
    assert any(MSG_NEW_PATH.format(st="self-review") in e for e in bad_new.errors)
    assert any(MSG_NEW_PATH.format(st="blocked") in e for e in bad_new.errors)
    assert not any("T-261116-newsr-ok.md" in e for e in bad_new.errors)
    assert not any("T-261116-ok.md" in e for e in bad_new.errors)
    (fresh / "T-261116-newsr-bad.md").write_text(
        _task("self-review", extra="pr: #25"), encoding="utf-8"
    )
    bad2 = validate_tasks_dir(fresh, previous_by_name={})
    assert any("T-261116-newsr-bad.md" in e and "self-review" in e for e in bad2.errors)
    gone = validate_tasks_dir(
        fresh,
        previous_by_name={
            "T-261116-ok.md": _task("open"),
            "T-261116-zz-gone.md": _task("open"),
        },
    )
    assert any(e == f"T-261116-zz-gone.md: {MSG_TASK_DELETED}" for e in gone.errors)
    bad_bytes = tmp_path / "T-261116-bin.md"
    bad_bytes.write_bytes(b"\xff\xfe status")
    try:
        bad_bytes.read_bytes().decode("utf-8")
        raise AssertionError("expected UnicodeDecodeError")
    except UnicodeDecodeError as exc:
        assert validate_task_file(bad_bytes) == GateResult(
            False, (MSG_UNREADABLE.format(detail=exc),)
        )
    locked = tmp_path / "T-261116-lock.md"
    locked.write_text(_task("open"), encoding="utf-8")
    locked.chmod(0)
    try:
        try:
            locked.read_bytes()
            raise AssertionError("expected OSError")
        except OSError as exc:
            assert (
                f"{locked.name}: {MSG_UNREADABLE.format(detail=exc)}"
                in validate_tasks_dir(tmp_path).errors
            )
    finally:
        locked.chmod(0o644)


def test_file_skip_transition_flags(tmp_path: Path):
    missing = tmp_path / "T-261116-nope.md"
    assert validate_task_file(missing) == GateResult(False, (f"missing task file {missing}",))
    early = tmp_path / "T-261116-aaa.md"
    early.write_text(_task("open"), encoding="utf-8")
    later = tmp_path / "T-261116-zzz.md"
    later.write_text(_task("done"), encoding="utf-8")
    assert validate_tasks_dir(tmp_path, skip_stems=frozenset({"T-261116-aaa"})) == GateResult(
        False, (f"T-261116-zzz.md: {MSG_DONE_EVIDENCE}",)
    )
    later.write_text(_task("done", extra="acceptance_note: lead signed off"), encoding="utf-8")
    assert validate_tasks_dir(tmp_path, skip_stems=frozenset({"T-261116-aaa"})) == GateResult(True)

    path = tmp_path / "T-261116-jump.md"
    old = _task("open")
    path.write_text(_task("done", extra="acceptance_note: lead signed off"), encoding="utf-8")
    bad = validate_task_file(path, old_text=old)
    assert bad.ok is False
    assert bad.errors[0] == MSG_ILLEGAL.format(
        old="open", new="done", allowed=sorted(ALLOWED_TRANSITIONS["open"])
    )
    assert validate_status_requirements(_task("open"), status="blocked") == GateResult(
        False, (MSG_BLOCKED_REASON, MSG_BLOCKED_DEADLINE)
    )
    done = _task("done", extra="acceptance_note: lead signed off")
    assert validate_task_text(done, old_status="open", check_transition=False) == GateResult(True)
    assert validate_task_text(_task("open"), old_status=None) == GateResult(True)

    name = "T-261116-jump2.md"
    d = tmp_path / "prev"
    d.mkdir()
    jp = d / name
    jp.write_text(_task("done", extra="acceptance_note: lead signed off"), encoding="utf-8")
    assert validate_tasks_dir(d) == GateResult(True)
    assert validate_tasks_dir(d, previous_by_name={name: old}).ok is False
    jp.write_text(_task("in-progress"), encoding="utf-8")
    assert validate_tasks_dir(d, previous_by_name={name: old}) == GateResult(True)
    assert validate_tasks_dir(d, previous_by_name={name: "# T\n\nЦенность: x\n"}) == GateResult(
        False, (f"{name}: {MSG_MISSING_STATUS} (previous)",)
    )


def test_git_previous_and_base_ref(tmp_path: Path, monkeypatch):
    import subprocess

    (tmp_path / ".git").mkdir()
    ctx = tmp_path / "context" / "tasks"
    ctx.mkdir(parents=True)
    name = "T-261116-git.md"
    (ctx / name).write_text(_task("open"), encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    blobs = previous_task_texts_from_git(ctx, repo_root=tmp_path, ref="HEAD")
    assert name in blobs and "статус: open" in blobs[name]
    (ctx / "T-261116-new.md").write_text(_task("open"), encoding="utf-8")
    blobs2 = previous_task_texts_from_git(ctx, repo_root=tmp_path, ref="HEAD")
    assert "T-261116-new.md" not in blobs2 and name in blobs2
    # deleted on disk but still at base
    (ctx / name).unlink()
    blobs3 = previous_task_texts_from_git(ctx, repo_root=tmp_path, ref="HEAD")
    assert name in blobs3
    del_r = validate_tasks_dir(ctx, previous_by_name=blobs3)
    assert any(MSG_TASK_DELETED in e for e in del_r.errors)

    with pytest.raises(RuntimeError):
        previous_task_texts_from_git(ctx, repo_root=tmp_path / "nope", ref="HEAD")

    repo = tmp_path / "repo"
    tasks = repo / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261116-a.md").write_text(_task("open"), encoding="utf-8")
    (tasks / "T-261116-b.md").write_text(_task("open"), encoding="utf-8")

    def fake_run(argv, **kwargs):
        cmd = " ".join(argv)
        if "ls-tree" in cmd:
            return SimpleNamespace(returncode=0, stdout="T-261116-a.md\nT-261116-b.md\n", stderr="")
        if cmd.endswith("T-261116-a.md"):
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="fatal: path 'x' does not exist in 'HEAD'",
            )
        if "show" in argv:
            return SimpleNamespace(returncode=0, stdout="ok-b\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert previous_task_texts_from_git(tasks, repo_root=repo, ref="HEAD") == {
        "T-261116-b.md": "ok-b\n"
    }

    def boom(argv, **kwargs):
        if "ls-tree" in argv or "show" in argv:
            return SimpleNamespace(returncode=128, stdout="", stderr="fatal: not a git repository")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError) as boom_exc:
        previous_task_texts_from_git(tasks, repo_root=repo, ref="HEAD")
    assert str(boom_exc.value) == MSG_GIT_ERROR.format(
        rel="context/tasks", ref="HEAD", detail="fatal: not a git repository"
    )

    def miss_tree(argv, **kwargs):
        assert kwargs.get("check") is False
        if "ls-tree" in argv:
            return SimpleNamespace(
                returncode=128,
                stdout="",
                stderr="fatal: path 'context/tasks' does not exist in 'HEAD'",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", miss_tree)
    assert previous_task_texts_from_git(tasks, repo_root=repo, ref="HEAD") == {}

    assert resolve_validate_base_ref(tmp_path, explicit="abc123") == "abc123"
    monkeypatch.setenv("MUTATION_BASE", "env-base")
    assert resolve_validate_base_ref(tmp_path) == "env-base"
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    monkeypatch.setenv("TASKS_VALIDATE_BASE", "tv-base")
    assert resolve_validate_base_ref(tmp_path) == "tv-base"
    monkeypatch.delenv("TASKS_VALIDATE_BASE", raising=False)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="deadbeef\n", stderr=""),
    )
    assert resolve_validate_base_ref(tmp_path) == "deadbeef"
    for stdout, code in (("", 0), ("", 1)):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, stdout=stdout, code=code, **k: SimpleNamespace(
                returncode=code, stdout=stdout, stderr="err"
            ),
        )
        assert resolve_validate_base_ref(tmp_path) == "origin/main"


def test_claim_and_file_edges(tmp_path: Path):
    from agentized.tasks import append_progress, render_task_file, set_field

    def claim(status: str) -> str:
        old = render_task_file("T-261116-clm", "Claim me", status=status)
        old = old.replace("\n## Цель", "\nЦенность: people get work done\n\n## Цель", 1)
        text = set_field(set_field(old, "claim", "alice"), "статус", "in-progress")
        return append_progress(text, "claim by alice")

    for st in ("open", "queue", "in-progress"):
        assert validate_task_text(claim(st), old_status=st) == GateResult(True)
    for st in ("idea", "canceled"):
        bad = validate_task_text(claim(st), old_status=st)
        assert bad == GateResult(
            False,
            (
                MSG_ILLEGAL.format(
                    old=st,
                    new="in-progress",
                    allowed=sorted(ALLOWED_TRANSITIONS[st]),
                ),
            ),
        )

    path = tmp_path / "T-261116-eo.md"
    path.write_text(_task("open"), encoding="utf-8")
    assert validate_task_file(path, old_text="# T\n\nЦенность: x\n") == GateResult(
        False, (MSG_MISSING_STATUS,)
    )
    assert validate_task_file(path, old_text=None) == GateResult(True)
    path.write_text(_task("open", value=False), encoding="utf-8")
    assert validate_task_file(path) == GateResult(False, (MSG_MISSING_VALUE,))
    path.write_text(_task("done", extra="acceptance_note: ok"), encoding="utf-8")
    bad = validate_task_file(path, old_text=_task("open"))
    assert bad.ok is False and bad.errors[0].startswith("illegal transition open → done")


def test_git_helpers_and_shared_status_surface(tmp_path: Path, monkeypatch):
    from agentized import tasks as tasks_mod
    from agentized.status_gates import (
        ALL_STATUSES,
        CANONICAL_STATUSES,
        COLUMN_FOR_STATUS,
        FIELD_RE,
        STATUS_ALIASES,
        default_repo_root_for_tasks,
    )
    import subprocess

    assert ALL_STATUSES is tasks_mod.ALL_STATUSES
    assert CANONICAL_STATUSES is tasks_mod.CANONICAL_STATUSES
    assert STATUS_ALIASES is tasks_mod.STATUS_ALIASES
    assert FIELD_RE is tasks_mod.FIELD_RE
    assert "self-review" in ALL_STATUSES and "queued" in ALL_STATUSES
    assert FIELD_RE.match("pr: #37").group(2) == "#37"
    assert FIELD_RE.match("review_note: tip green").group(1) == "review_note"

    class FakePath:
        def resolve(self):
            return Path("/only")

        @property
        def parents(self):
            return (Path("/"),)

    class TwoParents:
        def resolve(self):
            return Path("/repo/tasks")

        @property
        def parents(self):
            return (Path("/repo"), Path("/"))

    assert default_repo_root_for_tasks(FakePath()) == Path("/only")
    assert default_repo_root_for_tasks(TwoParents()) == Path("/")
    assert CANONICAL_STATUSES[-1] == "canceled"
    assert STATUS_ALIASES == {"dropped": "canceled", "queued": "queue"}
    assert set(COLUMN_FOR_STATUS) == set(CANONICAL_STATUSES)
    assert _git_missing_path("fatal: path not in 'HEAD'")
    assert _git_missing_path("exists on disk, but not in 'abc'")
    assert not _git_missing_path("fatal: bad object")
    assert str(_git_err("rel/x", "REF", "boom")) == MSG_GIT_ERROR.format(
        rel="rel/x", ref="REF", detail="boom"
    )
    proc = SimpleNamespace(returncode=7, stdout="out-detail", stderr="")
    assert _cmd_detail(proc) == "out-detail"
    assert _cmd_detail(SimpleNamespace(returncode=9, stdout="", stderr="")) == "exit 9"

    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261116-os.md").write_text(_task("open"), encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(RuntimeError) as excinfo:
        previous_task_texts_from_git(tasks, repo_root=None, ref="HEAD")
    assert str(excinfo.value) == MSG_GIT_ERROR.format(
        rel="context/tasks", ref="HEAD", detail="boom"
    )
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    monkeypatch.delenv("TASKS_VALIDATE_BASE", raising=False)
    with pytest.raises(RuntimeError) as excinfo2:
        resolve_validate_base_ref(tmp_path)
    assert str(excinfo2.value) == "git merge-base failed: boom"

    calls: list = []

    def ok_mb(argv, **kwargs):
        assert kwargs.get("check") is False
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")

    monkeypatch.setattr(subprocess, "run", ok_mb)
    assert resolve_validate_base_ref(tmp_path) == "abc123"
    assert calls[0][:3] == ["git", "-C", str(tmp_path)]
    assert calls[0][-3:] == ["merge-base", "origin/main", "HEAD"]

    def tree_and_show(argv, **kwargs):
        assert kwargs.get("check") is False
        if "ls-tree" in argv:
            return SimpleNamespace(
                returncode=0,
                stdout="T-261116-os.md\nREADME.md\nnotes.txt\n",
                stderr="",
            )
        if "show" in argv:
            return SimpleNamespace(returncode=0, stdout=_task("open"), stderr="")
        if "merge-base" in argv:
            return SimpleNamespace(returncode=0, stdout="deadbeef\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected")

    monkeypatch.setattr(subprocess, "run", tree_and_show)
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    assert set(previous_task_texts_from_git(tasks, repo_root=tmp_path, ref="HEAD")) == {
        "T-261116-os.md"
    }
    ref, result = run_tasks_validate(tasks, repo_root=tmp_path)
    assert ref == "deadbeef" and result.ok is True

    def fail_show(argv, **kwargs):
        assert kwargs.get("check") is False
        if "ls-tree" in argv:
            return SimpleNamespace(returncode=0, stdout="T-261116-os.md\n", stderr="")
        return SimpleNamespace(returncode=128, stdout="fatal: bad object", stderr="")

    monkeypatch.setattr(subprocess, "run", fail_show)
    with pytest.raises(RuntimeError) as e3:
        previous_task_texts_from_git(tasks, repo_root=tmp_path, ref="deadbeef")
    assert str(e3.value) == MSG_GIT_ERROR.format(
        rel="context/tasks/T-261116-os.md",
        ref="deadbeef",
        detail="fatal: bad object",
    )

    def show_os(argv, **kwargs):
        if "ls-tree" in argv:
            return SimpleNamespace(returncode=0, stdout="T-261116-os.md\n", stderr="")
        raise OSError("show-boom")

    monkeypatch.setattr(subprocess, "run", show_os)
    with pytest.raises(RuntimeError) as show_exc:
        previous_task_texts_from_git(tasks, repo_root=tmp_path, ref="HEAD")
    assert str(show_exc.value) == MSG_GIT_ERROR.format(
        rel="context/tasks/T-261116-os.md", ref="HEAD", detail="show-boom"
    )
    other = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    other.mkdir(exist_ok=True)
    (other / "T-261116-out.md").write_text(_task("open"), encoding="utf-8")
    with pytest.raises(RuntimeError) as e5:
        previous_task_texts_from_git(other, repo_root=tmp_path, ref="HEAD")
    with pytest.raises(ValueError) as ve:
        other.resolve().relative_to(tmp_path.resolve())
    assert str(e5.value) == MSG_GIT_ERROR.format(rel=other.name, ref="HEAD", detail=str(ve.value))
    # resolve_validate_base_ref must see the explicit repo_root (not None)
    seen: list[Path] = []

    def capture_resolve(root, *, explicit=None):
        seen.append(root)
        return explicit or "HEAD"

    monkeypatch.setattr("agentized.status_gates.resolve_validate_base_ref", capture_resolve)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=128, stdout="", stderr="does not exist"),
    )
    assert previous_task_texts_from_git(tasks, repo_root=tmp_path, ref="HEAD") == {}
    assert seen == [tmp_path]


def test_run_validate_kwargs(tmp_path: Path, monkeypatch):
    import agentized.status_gates as sg

    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261116-rv.md").write_text(
        _task("done", extra="acceptance_note: forged"), encoding="utf-8"
    )
    calls: dict = {}

    def fake_resolve(root, *, explicit=None):
        calls["resolve"] = (root, explicit)
        return "CUSTOM-REF"

    def fake_prev(td, *, repo_root=None, ref=None):
        calls["prev"] = (td, repo_root, ref)
        return {"T-261116-rv.md": _task("open")}

    def fake_validate(td, *, previous_by_name=None, skip_stems=None):
        calls["validate"] = previous_by_name
        return GateResult(False, ("illegal transition open → done",))

    monkeypatch.setattr(sg, "resolve_validate_base_ref", fake_resolve)
    monkeypatch.setattr(sg, "previous_task_texts_from_git", fake_prev)
    monkeypatch.setattr(sg, "validate_tasks_dir", fake_validate)
    ref, result = run_tasks_validate(tasks, repo_root=tmp_path, base_ref="B")
    assert ref == "CUSTOM-REF" and result.ok is False
    assert calls["resolve"] == (tmp_path, "B")
    assert calls["prev"] == (tasks, tmp_path, "CUSTOM-REF")
    assert calls["validate"] == {"T-261116-rv.md": _task("open")}
    multi = tmp_path / "multi"
    multi.mkdir()
    (multi / "T-261116-a.md").write_text(_task("open"), encoding="utf-8")
    (multi / "T-261116-b.md").write_text(_task("open", value=False), encoding="utf-8")
    multi_res = validate_tasks_dir(
        multi,
        previous_by_name={
            "T-261116-a.md": "# T\n\nЦенность: x\n",
            "T-261116-b.md": _task("open"),
        },
    )
    assert any("T-261116-a.md" in e and "статус" in e for e in multi_res.errors)
    assert any("T-261116-b.md" in e and "Ценность" in e for e in multi_res.errors)


def test_two_commit_open_to_done_vs_base(tmp_path: Path, monkeypatch):
    import subprocess

    root = tmp_path / "repo"
    tasks = root / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261116-ci.md").write_text(_task("open"), encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    (tasks / "T-261116-ci.md").write_text(
        _task("done", extra="acceptance_note: forged"), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "bad"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("MUTATION_BASE", base)
    prev = previous_task_texts_from_git(tasks, repo_root=root)
    assert "T-261116-ci.md" in prev and "статус: open" in prev["T-261116-ci.md"]
    result = validate_tasks_dir(tasks, previous_by_name=prev)
    assert result.ok is False
    assert any("illegal transition open → done" in e for e in result.errors)
