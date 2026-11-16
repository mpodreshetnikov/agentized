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


def test_claim_transition_paths():
    from agentized.tasks import append_progress, render_task_file, set_field

    def claim_text(status: str, owner: str = "alice") -> tuple[str, str]:
        old = render_task_file(
            "T-261116-clm", "Claim me", status=status, value="people get work done"
        )
        text = set_field(old, "claim", owner)
        text = set_field(text, "статус", "in-progress")
        text = append_progress(text, f"claim by {owner}")
        return old, text

    for st in ("open", "queue", "in-progress"):
        _, text = claim_text(st)
        assert validate_task_text(
            text, old_status=st, require_value=True, check_transition=True
        ) == GateResult(True)
    _, text = claim_text("idea")
    assert validate_task_text(
        text, old_status="idea", require_value=True, check_transition=True
    ) == GateResult(
        False,
        (
            MSG_ILLEGAL.format(
                old="idea",
                new="in-progress",
                allowed=sorted(ALLOWED_TRANSITIONS["idea"]),
            ),
        ),
    )
    _, text = claim_text("canceled")
    assert validate_task_text(
        text, old_status="canceled", require_value=True, check_transition=True
    ) == GateResult(
        False,
        (
            MSG_ILLEGAL.format(
                old="canceled",
                new="in-progress",
                allowed=sorted(ALLOWED_TRANSITIONS["canceled"]),
            ),
        ),
    )


def test_validate_task_file_empty_old(tmp_path: Path):
    path = tmp_path / "T-261116-eo.md"
    path.write_text(_task("open"), encoding="utf-8")
    bad = validate_task_file(path, old_text="# T\n\nЦенность: x\n")
    assert bad == GateResult(False, (MSG_MISSING_STATUS,))
    assert validate_task_file(path, old_text=None) == GateResult(True)


def test_default_repo_root_and_git_oserror(tmp_path: Path, monkeypatch):
    from agentized.status_gates import default_repo_root_for_tasks
    import subprocess

    class FakePath:
        def resolve(self):
            return Path("/only")

        @property
        def parents(self):
            return (Path("/"),)

    assert default_repo_root_for_tasks(FakePath()) == Path("/only")

    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261116-os.md").write_text(_task("open"), encoding="utf-8")

    def boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError):
        previous_task_texts_from_git(tasks, repo_root=tmp_path, ref="HEAD")
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    monkeypatch.delenv("TASKS_VALIDATE_BASE", raising=False)
    with pytest.raises(RuntimeError):
        resolve_validate_base_ref(tmp_path)
