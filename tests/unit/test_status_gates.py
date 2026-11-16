"""Hard status gates — pass/fail per rule (AGE-22)."""
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
    MSG_ILLEGAL,
    MSG_MISSING_STATUS,
    MSG_MISSING_VALUE,
    MSG_REVIEW_EVIDENCE,
    MSG_UNKNOWN_NEW,
    MSG_UNKNOWN_OLD,
    MSG_UNKNOWN_STATUS,
    GateResult,
    extract_status,
    has_value_line,
    is_known_status,
    is_real_pr_ref,
    normalize_status,
    parse_task_fields,
    previous_task_texts_from_git,
    resolve_validate_base_ref,
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
    assert normalize_status("") == ""
    assert normalize_status(None) == ""
    assert has_value_line("Ценность: x") is True
    assert has_value_line("Ценность: _(пусто)_") is False
    assert has_value_line("value: x") is False
    assert has_value_line("") is False
    assert has_value_line(None) is False
    text = _task("in-progress")
    assert parse_task_fields(text)["статус"] == "in-progress"
    assert extract_status(text) == "in-progress"
    assert extract_status("# only title\n\nЦенность: x\n") == ""
    assert extract_status("") == ""
    assert extract_status("статус:   \n") == ""
    assert parse_task_fields("") == {}
    assert parse_task_fields(None) == {}
    bare = "# T-261116-x — X\n\nЦенность: v\n"
    assert validate_task_text(bare, check_transition=False) == GateResult(
        False, (MSG_MISSING_STATUS,)
    )
    blank = _task("open").replace("статус: open", "статус:   ")
    assert validate_task_text(blank, check_transition=False) == GateResult(
        False, (MSG_MISSING_STATUS,)
    )
    assert validate_status_requirements(bare) == GateResult(False, (MSG_MISSING_STATUS,))
    assert validate_transition("", "open") == GateResult(False, (MSG_MISSING_STATUS,))
    assert validate_transition("open", "") == GateResult(False, (MSG_MISSING_STATUS,))


def test_transition_matrix_pass_fail():
    assert validate_transition("open", "in-progress") == GateResult(True)
    assert validate_transition("in-progress", "self-review") == GateResult(True)
    bad = validate_transition("open", "done")
    assert bad == GateResult(
        False,
        (
            MSG_ILLEGAL.format(
                old="open", new="done", allowed=sorted(ALLOWED_TRANSITIONS["open"])
            ),
        ),
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
    placeholders = _task(
        "blocked", extra="blocked_reason: _(пусто)_\nblocked_deadline: _(пусто)_"
    )
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
    ) == GateResult(
        False, (MSG_BLOCKED_DEADLINE_INVALID.format(deadline="2026-13-40"),)
    )


def test_review_pr_and_done_fields():
    for st in ("self-review", "for-review"):
        assert validate_status_requirements(_task(st)) == GateResult(
            False, (MSG_REVIEW_EVIDENCE.format(st=st),)
        )
        assert validate_status_requirements(
            _task(st, extra="review_note: checklist complete")
        ) == GateResult(True)
        assert validate_status_requirements(_task(st, extra="pr: #25")) == GateResult(True)
        assert validate_status_requirements(_task(st, extra="pr: PR #25")) == GateResult(
            True
        )
        assert validate_status_requirements(
            _task(st, extra="pr: https://github.com/mpodreshetnikov/agentized/pull/25")
        ) == GateResult(True)
        assert validate_status_requirements(
            _task(st, body="See https://github.com/o/r/pull/1\n")
        ) == GateResult(False, (MSG_REVIEW_EVIDENCE.format(st=st),))
        assert validate_status_requirements(
            _task(st, extra="pr: ready-for-lead")
        ) == GateResult(
            False,
            (MSG_BAD_PR.format(pr="ready-for-lead"), MSG_REVIEW_EVIDENCE.format(st=st)),
        )
        assert validate_status_requirements(
            _task(st, extra="review_note: _(пусто)_")
        ) == GateResult(False, (MSG_REVIEW_EVIDENCE.format(st=st),))
    assert validate_status_requirements(_task("done")) == GateResult(
        False, (MSG_DONE_EVIDENCE,)
    )
    assert validate_status_requirements(
        _task("done", extra="acceptance_note: lead signed off")
    ) == GateResult(True)
    assert validate_status_requirements(
        _task("done", extra="review_note: ship it")
    ) == GateResult(False, (MSG_DONE_EVIDENCE,))
    assert validate_status_requirements(_task("done", extra="pr: #3")) == GateResult(
        False, (MSG_DONE_EVIDENCE,)
    )
    assert validate_status_requirements(
        _task("done", body="- Done — merged PR #3\n")
    ) == GateResult(False, (MSG_DONE_EVIDENCE,))
    assert is_real_pr_ref("#12") is True
    assert is_real_pr_ref("PR #12") is True
    assert is_real_pr_ref("https://github.com/o/r/pull/12") is True
    assert is_real_pr_ref("https://example.com/x") is False
    assert is_real_pr_ref("merged") is False
    assert is_real_pr_ref("") is False
    assert is_real_pr_ref("_(пусто)_") is False


def test_value_transition_file_dir(tmp_path: Path):
    text = _task("open", value=False)
    assert validate_task_text(text, check_transition=False) == GateResult(
        False, (MSG_MISSING_VALUE,)
    )
    assert validate_task_text(
        text, require_value=False, check_transition=False
    ) == GateResult(True)
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
    good_blocked = _task(
        "blocked", extra="blocked_reason: dep\nblocked_deadline: 2026-11-20"
    )
    assert validate_task_text(good_blocked, old_status="open") == GateResult(True)
    path.write_text(good_blocked, encoding="utf-8")
    assert validate_task_file(path, old_text=old) == GateResult(True)

    (tmp_path / "T-261116-aaa.md").write_text(_task("open"), encoding="utf-8")
    bbb = tmp_path / "T-261116-bbb.md"
    bbb.write_text(_task("done"), encoding="utf-8")
    assert validate_tasks_dir(tmp_path) == GateResult(
        False, (f"T-261116-bbb.md: {MSG_DONE_EVIDENCE}",)
    )
    bbb.write_text(
        _task("done", extra="acceptance_note: lead signed off"), encoding="utf-8"
    )
    assert validate_tasks_dir(tmp_path) == GateResult(True)
    (tmp_path / "T-261116-ccc.md").write_text(_task("open", value=False), encoding="utf-8")
    assert validate_tasks_dir(tmp_path) == GateResult(
        False, (f"T-261116-ccc.md: {MSG_MISSING_VALUE}",)
    )
    assert validate_task_file(
        tmp_path / "T-261116-ccc.md", require_value=False
    ) == GateResult(True)


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
    assert is_known_status("flying") is False
    assert is_known_status("") is False


def test_file_skip_transition_flags(tmp_path: Path):
    missing = tmp_path / "T-261116-nope.md"
    assert validate_task_file(missing) == GateResult(
        False, (f"missing task file {missing}",)
    )
    early = tmp_path / "T-261116-aaa.md"
    early.write_text(_task("open"), encoding="utf-8")
    later = tmp_path / "T-261116-zzz.md"
    later.write_text(_task("done"), encoding="utf-8")
    assert validate_tasks_dir(
        tmp_path, skip_stems=frozenset({"T-261116-aaa"})
    ) == GateResult(False, (f"T-261116-zzz.md: {MSG_DONE_EVIDENCE}",))
    later.write_text(
        _task("done", extra="acceptance_note: lead signed off"), encoding="utf-8"
    )
    assert validate_tasks_dir(
        tmp_path, skip_stems=frozenset({"T-261116-aaa"})
    ) == GateResult(True)
    no_val = tmp_path / "T-261116-noval.md"
    no_val.write_text(_task("open", value=False), encoding="utf-8")
    assert validate_task_file(no_val) == GateResult(False, (MSG_MISSING_VALUE,))
    assert validate_task_file(no_val, require_value=False) == GateResult(True)

    path = tmp_path / "T-261116-jump.md"
    old = _task("open")
    path.write_text(
        _task("done", extra="acceptance_note: lead signed off"), encoding="utf-8"
    )
    bad = validate_task_file(path, old_text=old)
    assert bad.ok is False
    assert bad.errors[0] == MSG_ILLEGAL.format(
        old="open", new="done", allowed=sorted(ALLOWED_TRANSITIONS["open"])
    )
    assert validate_status_requirements(_task("open"), status="blocked") == GateResult(
        False, (MSG_BLOCKED_REASON, MSG_BLOCKED_DEADLINE)
    )
    done = _task("done", extra="acceptance_note: lead signed off")
    assert validate_task_text(
        done, old_status="open", check_transition=False
    ) == GateResult(True)
    blocked_jump = validate_task_text(done, old_status="open", check_transition=True)
    assert blocked_jump.ok is False
    assert blocked_jump.errors[0] == MSG_ILLEGAL.format(
        old="open", new="done", allowed=sorted(ALLOWED_TRANSITIONS["open"])
    )
    assert validate_task_text(_task("open"), old_status=None) == GateResult(True)

    name = "T-261116-jump2.md"
    p2 = tmp_path / name
    p2.write_text(
        _task("done", extra="acceptance_note: lead signed off"), encoding="utf-8"
    )
    # previous map illegal / legal
    d = tmp_path / "prev"
    d.mkdir()
    jp = d / name
    jp.write_text(
        _task("done", extra="acceptance_note: lead signed off"), encoding="utf-8"
    )
    assert validate_tasks_dir(d) == GateResult(True)
    assert validate_tasks_dir(d, previous_by_name={name: old}).ok is False
    jp.write_text(_task("in-progress"), encoding="utf-8")
    assert validate_tasks_dir(d, previous_by_name={name: old}) == GateResult(True)
    assert validate_tasks_dir(
        d, previous_by_name={name: "# T\n\nЦенность: x\n"}
    ) == GateResult(False, (f"{name}: {MSG_MISSING_STATUS} (previous)",))
    from agentized.status_gates import NEW_PATH_FORBIDDEN_STATUSES

    fresh = tmp_path / "brand"
    fresh.mkdir()
    assert NEW_PATH_FORBIDDEN_STATUSES == frozenset({"done", "canceled"})
    (fresh / "T-261116-newdone.md").write_text(
        _task("done", extra="acceptance_note: forged"), encoding="utf-8"
    )
    (fresh / "T-261116-newcanceled.md").write_text(_task("canceled"), encoding="utf-8")
    (fresh / "T-261116-newsr.md").write_text(
        _task("self-review", extra="review_note: ok"), encoding="utf-8"
    )
    bad_new = validate_tasks_dir(fresh, previous_by_name={})
    assert any("new task cannot start as done" in e for e in bad_new.errors)
    assert any("new task cannot start as canceled" in e for e in bad_new.errors)
    assert not any("self-review" in e and "new task" in e for e in bad_new.errors)


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
    with pytest.raises(RuntimeError):
        previous_task_texts_from_git(ctx, repo_root=tmp_path / "nope", ref="HEAD")

    repo = tmp_path / "repo"
    tasks = repo / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261116-a.md").write_text(_task("open"), encoding="utf-8")
    (tasks / "T-261116-b.md").write_text(_task("open"), encoding="utf-8")

    def fake_run(argv, **kwargs):
        rel = argv[-1]
        if rel.endswith("T-261116-a.md"):
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
        if "show" in argv:
            return SimpleNamespace(
                returncode=128, stdout="", stderr="fatal: not a git repository"
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError):
        previous_task_texts_from_git(tasks, repo_root=repo, ref="HEAD")

    assert resolve_validate_base_ref(tmp_path, explicit="abc123") == "abc123"
    monkeypatch.setenv("MUTATION_BASE", "env-base")
    assert resolve_validate_base_ref(tmp_path) == "env-base"
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    monkeypatch.setenv("TASKS_VALIDATE_BASE", "tv-base")
    assert resolve_validate_base_ref(tmp_path) == "tv-base"
    monkeypatch.delenv("TASKS_VALIDATE_BASE", raising=False)

    def fake_mb(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout="deadbeef\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_mb)
    assert resolve_validate_base_ref(tmp_path) == "deadbeef"

    def fail_mb(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="err")

    monkeypatch.setattr(subprocess, "run", fail_mb)
    assert resolve_validate_base_ref(tmp_path) == "origin/main"


def test_validate_tasks_dir_require_value_false(tmp_path: Path):
    path = tmp_path / "T-261116-nv2.md"
    path.write_text(
        "# T-261116-nv2 — x\n\nстатус: open\nтеги: t\nродитель: p\nclaim: c\n\n## Цель\n\nx\n",
        encoding="utf-8",
    )
    assert validate_tasks_dir(tmp_path) == GateResult(
        False, (f'{path.name}: missing value line "Ценность: …"',)
    )
    assert validate_tasks_dir(tmp_path, require_value=False) == GateResult(True)


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
    assert validate_task_file(path, require_value=True) == GateResult(
        False, (MSG_MISSING_VALUE,)
    )
    assert validate_task_file(path, old_text=_task("idea"), require_value=True) == GateResult(
        False, (MSG_MISSING_VALUE,)
    )
    assert validate_task_file(path, old_text=_task("idea"), require_value=False) == GateResult(
        True
    )
    path.write_text(_task("done", extra="acceptance_note: ok"), encoding="utf-8")
    bad = validate_task_file(path, old_text=_task("open"), require_value=False)
    assert bad.ok is False and bad.errors[0].startswith("illegal transition open → done")

    a, b = tmp_path / "T-261116-a.md", tmp_path / "T-261116-b.md"
    a.write_text(_task("open"), encoding="utf-8")
    b.write_text(_task("open", value=False), encoding="utf-8")
    cont = validate_tasks_dir(
        tmp_path, previous_by_name={"T-261116-a.md": "# T\n\nЦенность: x\n"}
    )
    assert any("T-261116-a.md" in e and "статус" in e for e in cont.errors)
    assert any("T-261116-b.md" in e and "Ценность" in e for e in cont.errors)


def test_git_helpers_and_shared_status_surface(tmp_path: Path, monkeypatch):
    from agentized.status_gates import (
        CANONICAL_STATUSES,
        COLUMN_FOR_STATUS,
        MSG_GIT_ERROR,
        STATUS_ALIASES,
        _git_missing_path,
        default_repo_root_for_tasks,
    )
    import subprocess

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

    pr_samples = {
        None: "reject",
        "": "reject",
        "   ": "reject",
        "_placeholder": "reject",
        "_(пусто)_": "reject",
        "#12": "accept",
        "PR #12": "accept",
        "https://github.com/o/r/pull/9": "accept",
        "merged": "reject",
    }
    assert {k: ("accept" if is_real_pr_ref(k) else "reject") for k in pr_samples} == pr_samples

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
    assert COLUMN_FOR_STATUS == {
        "idea": "open",
        "open": "open",
        "queue": "queue",
        "self-review": "queue",
        "in-progress": "in-progress",
        "for-review": "for-review",
        "blocked": "blocked",
        "done": "done",
        "canceled": "canceled",
    }
    assert set(COLUMN_FOR_STATUS) == set(CANONICAL_STATUSES)

    miss = {
        "fatal: path not in 'HEAD'": "missing",
        "exists on disk, but not in 'abc'": "missing",
        "fatal: path 'x' does not exist in 'HEAD'": "missing",
        "fatal: bad object": "other",
    }
    assert {k: ("missing" if _git_missing_path(k) else "other") for k in miss} == miss

    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261116-os.md").write_text(_task("open"), encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(RuntimeError) as excinfo:
        previous_task_texts_from_git(tasks, repo_root=tmp_path, ref="HEAD")
    assert str(excinfo.value) == MSG_GIT_ERROR.format(
        rel="context/tasks/T-261116-os.md", ref="HEAD", detail="boom"
    )
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    monkeypatch.delenv("TASKS_VALIDATE_BASE", raising=False)
    with pytest.raises(RuntimeError) as excinfo2:
        resolve_validate_base_ref(tmp_path)
    assert str(excinfo2.value) == "git merge-base failed: boom"

    calls: list[list[str]] = []

    def ok_mb(argv, **kwargs):
        calls.append(list(argv))
        assert kwargs.get("capture_output") is True and kwargs.get("text") is True
        return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")

    monkeypatch.setattr(subprocess, "run", ok_mb)
    assert resolve_validate_base_ref(tmp_path) == "abc123"
    assert calls == [["git", "-C", str(tmp_path), "merge-base", "origin/main", "HEAD"]]
    for stdout in ("  \n", "", None):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, stdout=stdout, **k: SimpleNamespace(
                returncode=0, stdout=stdout, stderr=""
            ),
        )
        assert resolve_validate_base_ref(tmp_path) == "origin/main"

    (tasks / "T-261116-g1.md").write_text(_task("open"), encoding="utf-8")

    def fail_show(argv, **kwargs):
        assert argv[:4] == ["git", "-C", str(tmp_path), "show"]
        assert kwargs.get("check") is False
        return SimpleNamespace(returncode=128, stdout="", stderr="fatal: bad object")

    monkeypatch.setattr(subprocess, "run", fail_show)
    with pytest.raises(RuntimeError) as e3:
        previous_task_texts_from_git(tasks, repo_root=tmp_path, ref="deadbeef")
    assert str(e3.value) == MSG_GIT_ERROR.format(
        rel="context/tasks/T-261116-g1.md", ref="deadbeef", detail="fatal: bad object"
    )
    (tasks / "T-261116-keep.md").write_text(_task("open"), encoding="utf-8")

    def miss_then_ok(argv, **kwargs):
        rel = str(argv[-1])
        if rel.endswith("T-261116-g1.md") or rel.endswith("T-261116-os.md"):
            return SimpleNamespace(
                returncode=128, stdout="", stderr="fatal: path 'x' does not exist in 'x'"
            )
        return SimpleNamespace(returncode=0, stdout="kept\n", stderr="")

    monkeypatch.setattr(subprocess, "run", miss_then_ok)
    assert previous_task_texts_from_git(tasks, repo_root=tmp_path, ref="deadbeef") == {
        "T-261116-keep.md": "kept\n"
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=7, stdout="", stderr=""),
    )
    with pytest.raises(RuntimeError) as e4:
        previous_task_texts_from_git(tasks, repo_root=tmp_path, ref="HEAD")
    assert str(e4.value) == MSG_GIT_ERROR.format(
        rel="context/tasks/T-261116-g1.md", ref="HEAD", detail="exit 7"
    )
    monkeypatch.setenv("MUTATION_BASE", "must-read-env")
    assert resolve_validate_base_ref(tmp_path) == "must-read-env"
    root_s = str(tmp_path.resolve())
    mb_calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        assert kwargs.get("check") is False and argv[2] == root_s
        if "merge-base" in argv:
            mb_calls.append(list(argv))
            return SimpleNamespace(returncode=0, stdout="deadbeef\n", stderr="")
        if "show" in argv:
            return SimpleNamespace(returncode=0, stdout="blob\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    monkeypatch.delenv("TASKS_VALIDATE_BASE", raising=False)
    assert previous_task_texts_from_git(tasks) == {
        "T-261116-g1.md": "blob\n",
        "T-261116-keep.md": "blob\n",
        "T-261116-os.md": "blob\n",
    }
    assert mb_calls and mb_calls[0][2] == root_s
    other = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    other.mkdir(exist_ok=True)
    out = other / "T-261116-out.md"
    out.write_text(_task("open"), encoding="utf-8")
    try:
        out.resolve().relative_to(tmp_path.resolve())
    except ValueError as expected_exc:
        detail = str(expected_exc)
    else:
        raise AssertionError("expected ValueError")
    with pytest.raises(RuntimeError) as e5:
        previous_task_texts_from_git(other, repo_root=tmp_path, ref="HEAD")
    assert str(e5.value) == MSG_GIT_ERROR.format(
        rel="T-261116-out.md", ref="HEAD", detail=detail
    )


def test_two_commit_open_to_done_vs_base(tmp_path: Path):
    import os
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
    os.environ["MUTATION_BASE"] = base
    try:
        result = validate_tasks_dir(
            tasks, previous_by_name=previous_task_texts_from_git(tasks, repo_root=root)
        )
    finally:
        os.environ.pop("MUTATION_BASE", None)
    assert result.ok is False
    assert any("illegal transition open → done" in e for e in result.errors)


def test_rebuild_task_index_active(tmp_path: Path):
    from agentized.status_gates import INDEX_ACTIVE_STATUSES, rebuild_task_index_active

    def write(name: str, status: str, *, title: str, parent: str, claim: str) -> None:
        tid = name.removesuffix(".md")
        (tmp_path / name).write_text(
            f"# {tid} — {title}\n\nстатус: {status}\nтеги: t\n"
            f"родитель: {parent}\nclaim: {claim}\n\nЦенность: v\n\n## Цель\n\nGoal.\n",
            encoding="utf-8",
        )

    write("T-261116-idx.md", "queue", title="Demo", parent="AGE-22", claim="alice")
    write("T-261116-qz.md", "queue", title="Second", parent="_(пусто)_", claim="_(пусто)_")
    write("T-261116-ph.md", "open", title="Ph", parent="_x", claim="_y")
    write("T-261116-done.md", "done", title="Done", parent="_(пусто)_", claim="_(пусто)_")
    write("T-261116-ip.md", "in-progress", title="Work", parent="_(пусто)_", claim="bob")
    write("T-261116-qq.md", "queued", title="Alias", parent="_(пусто)_", claim="_(пусто)_")
    expected = (
        "# Задачи — живой индекс\n\n"
        "Генерируемый список **активной** работы. Не полный архив истории.\n\n"
        "Статусы в индексе: `open` · `queue` · `in-progress` · `self-review` · "
        "`for-review` · `blocked`.\n\n"
        "Поиск: этот индекс + grep по id / title / tags. Не обходи весь каталог "
        "`tasks/`.\n\n"
        "## open\n\n- [T-261116-ph](T-261116-ph.md) — Ph\n\n"
        "## queue\n\n"
        "- [T-261116-idx](T-261116-idx.md) — Demo (родитель: AGE-22) · claim: alice\n"
        "- [T-261116-qq](T-261116-qq.md) — Alias\n"
        "- [T-261116-qz](T-261116-qz.md) — Second\n\n"
        "## in-progress\n\n- [T-261116-ip](T-261116-ip.md) — Work · claim: bob\n\n"
        "## self-review\n\n_(пусто)_\n\n## for-review\n\n_(пусто)_\n\n"
        "## blocked\n\n_(пусто)_\n\n"
        "Новые задачи — по [`TEMPLATE.md`](TEMPLATE.md). Файлы задач лежат рядом "
        "с этим индексом; при смене статуса файл **не перемещается**.\n"
    )
    assert rebuild_task_index_active(tmp_path) == expected
    assert list(INDEX_ACTIVE_STATUSES) == [
        "open",
        "queue",
        "in-progress",
        "self-review",
        "for-review",
        "blocked",
    ]

