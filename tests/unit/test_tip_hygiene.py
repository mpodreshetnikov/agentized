"""AGE-76 tip hygiene hard gate + ready idempotence."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agentized import tip_hygiene as th
from agentized.status_gates import TEXT_ENCODING, GateResult, run_tasks_validate
from agentized.task_schema import PLACEHOLDER_CLAIM, last_progress_entry, rebuild_task_index
from agentized.tip_hygiene import (
    CLAIM_EMPTY,
    CLAIM_RELEASED,
    ENV_PR_KEYS,
    MSG_READY_MISSING,
    MSG_READY_NOTE,
    MSG_READY_STATUS,
    MSG_TIP_CLAIM,
    MSG_TIP_INDEX,
    MSG_TIP_NO_LINKED,
    MSG_TIP_PR_CONFLICT,
    MSG_TIP_PR_REQUIRED,
    MSG_TIP_STATUS,
    MSG_TIP_UNREADABLE,
    READY_PROGRESS,
    TIP_OK_STATUSES,
    apply_ready,
    claim_is_held,
    extract_pr_number,
    resolve_pr,
    resolve_pr_number,
    task_points_at_pr,
    validate_index_freshness,
    validate_pr_linked_tasks,
    validate_tip_hygiene,
    write_ready,
)


def _task(
    status: str,
    *,
    claim: str = CLAIM_EMPTY,
    extra: str = "",
    value: bool = True,
    task_id: str = "T-261121-tip",
) -> str:
    lines = [
        f"# {task_id} — Tip demo",
        "",
        f"статус: {status}",
        "теги: tip",
        "родитель: _(пусто)_",
        f"claim: {claim}",
    ]
    if extra:
        lines.append(extra.rstrip())
    lines.append("")
    if value:
        lines.extend(["Ценность: tip hygiene blocks dirty PR tips", ""])
    lines.extend(["## Цель", "", "Goal.", "", "## Progress", "", "_(append-only)_", ""])
    return "\n".join(lines) + "\n"


def _write_index(tasks: Path) -> None:
    (tasks / "INDEX.md").write_text(rebuild_task_index(tasks), encoding="utf-8")


def test_extract_and_resolve_pr():
    assert extract_pr_number(None) is extract_pr_number("") is None
    assert extract_pr_number("nope") is None
    assert extract_pr_number("#52") == 52
    assert extract_pr_number("PR #7") == 7
    assert extract_pr_number("1") == 1
    assert extract_pr_number("https://github.com/o/r/pull/46") == 46

    assert resolve_pr(explicit=None, env={}).pr_number is None
    assert resolve_pr(explicit=12, env={}).pr_number == 12
    assert resolve_pr(explicit="#0", env={}).pr_number is None
    assert resolve_pr(env={"AGENTIZED_PR": "41"}).pr_number == 41
    assert resolve_pr(env={"GITHUB_REF": "refs/pull/52/merge"}).pr_number == 52
    assert resolve_pr(env={"GITHUB_REF": "refs/heads/main"}).pr_number is None
    assert resolve_pr(env={"GITHUB_REF": "   "}).pr_number is None
    assert resolve_pr(env={"AGENTIZED_PR": "  ", "TIP_HYGIENE_PR": "nope", "GITHUB_PR_NUMBER": "8"}).pr_number == 8

    # GitHub wins; agreeing override OK.
    ok = resolve_pr(explicit=55, env={"GITHUB_REF": "refs/pull/55/merge", "AGENTIZED_PR": "55"})
    assert ok == th.PrResolution(55)

    # Dodge blocked: AGENTIZED_PR disagrees with GITHUB_REF.
    bad = resolve_pr(env={"GITHUB_REF": "refs/pull/55/merge", "AGENTIZED_PR": "9999"})
    assert bad.pr_number is None
    assert MSG_TIP_PR_CONFLICT.format(github=55, override=9999) in bad.errors

    bad_pr = resolve_pr(explicit=7, env={"GITHUB_REF": "refs/pull/55/merge"})
    assert MSG_TIP_PR_CONFLICT.format(github=55, override=7) in bad_pr.errors

    # pull_request without number → required.
    need = resolve_pr(env={"GITHUB_EVENT_NAME": "pull_request"})
    assert need.pr_number is None
    assert MSG_TIP_PR_REQUIRED in need.errors

    # push/local: no number OK.
    push = resolve_pr(env={"GITHUB_EVENT_NAME": "push"})
    assert push == th.PrResolution(None)

    assert resolve_pr_number(env={"GITHUB_REF": "refs/pull/3/head"}) == 3
    assert ENV_PR_KEYS == ("AGENTIZED_PR", "TIP_HYGIENE_PR", "GITHUB_PR_NUMBER")
    assert TIP_OK_STATUSES == frozenset({"self-review", "done"})


def test_claim_released_only_empty_or_pustoe():
    assert CLAIM_RELEASED == frozenset({"", CLAIM_EMPTY})
    assert [claim_is_held(c) for c in (None, "", CLAIM_EMPTY, PLACEHOLDER_CLAIM, "worker")] == [
        False,
        False,
        False,
        True,
        True,
    ]
    assert [
        task_points_at_pr(None, 1),
        task_points_at_pr("#2", 2),
        task_points_at_pr("#2", 3),
    ] == [False, True, False]


def test_index_and_linked_tasks(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T-261121-a.md").write_text(_task("open", task_id="T-261121-a"), encoding="utf-8")
    assert validate_index_freshness(tasks) == GateResult(False, (MSG_TIP_INDEX,))
    _write_index(tasks)
    assert validate_index_freshness(tasks) == GateResult(True)

    # No matching pr → FAIL.
    none = validate_pr_linked_tasks(tasks, 76)
    assert none == GateResult(False, (MSG_TIP_NO_LINKED.format(pr=76),))

    (tasks / "T-261121-ok.md").write_text(
        _task("self-review", extra="pr: #76\nreview_note: green", task_id="T-261121-ok"),
        encoding="utf-8",
    )
    assert validate_pr_linked_tasks(tasks, 76) == GateResult(True)

    (tasks / "T-261121-dirty.md").write_text(
        _task("in-progress", claim="w", extra="pr: #76", task_id="T-261121-dirty"),
        encoding="utf-8",
    )
    dirty = validate_pr_linked_tasks(tasks, 76)
    assert MSG_TIP_STATUS.format(name="T-261121-dirty.md", pr=76, st="in-progress") in dirty.errors
    assert MSG_TIP_CLAIM.format(name="T-261121-dirty.md", pr=76, claim="w") in dirty.errors

    # Template claim placeholder is held.
    (tasks / "T-261121-ph.md").write_text(
        _task(
            "self-review",
            claim=PLACEHOLDER_CLAIM,
            extra="pr: #76\nreview_note: x",
            task_id="T-261121-ph",
        ),
        encoding="utf-8",
    )
    ph = validate_pr_linked_tasks(tasks, 76)
    assert MSG_TIP_CLAIM.format(name="T-261121-ph.md", pr=76, claim=PLACEHOLDER_CLAIM) in ph.errors


def test_continue_and_utf8_errors(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T-261121-aaa.md").write_bytes(b"\xff\xfe not-utf8 \x80")
    (tasks / "T-261121-zzz.md").write_text(
        _task("in-progress", claim="c", extra="pr: #3", task_id="T-261121-zzz"),
        encoding="utf-8",
    )
    res = validate_pr_linked_tasks(tasks, 3)
    unread = [e for e in res.errors if e.startswith("T-261121-aaa.md:")][0]
    assert unread.startswith("T-261121-aaa.md: tip hygiene: unreadable task file: ")
    assert "None" not in unread
    assert MSG_TIP_STATUS.format(name="T-261121-zzz.md", pr=3, st="in-progress") in res.errors

    # Non-matching first file continues into later match.
    tasks2 = tmp_path / "tasks2"
    tasks2.mkdir()
    (tasks2 / "T-261121-aaa.md").write_text(
        _task("in-progress", claim="x", extra="pr: #1", task_id="T-261121-aaa"),
        encoding="utf-8",
    )
    (tasks2 / "T-261121-zzz.md").write_text(
        _task("self-review", extra="pr: #3\nreview_note: ok", task_id="T-261121-zzz"),
        encoding="utf-8",
    )
    assert validate_pr_linked_tasks(tasks2, 3) == GateResult(True)

    # Bad UTF-8 INDEX → gate error, not traceback.
    tasks3 = tmp_path / "tasks3"
    tasks3.mkdir()
    (tasks3 / "T-261121-a.md").write_text(_task("open", task_id="T-261121-a"), encoding="utf-8")
    (tasks3 / "INDEX.md").write_bytes(b"\xff\xfe")
    assert validate_index_freshness(tasks3) == GateResult(False, (MSG_TIP_INDEX,))


def test_validate_tip_hygiene_pull_request_and_conflict(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T-261121-x.md").write_text(
        _task("self-review", extra="pr: #9\nreview_note: ok", task_id="T-261121-x"),
        encoding="utf-8",
    )
    _write_index(tasks)

    conflict = validate_tip_hygiene(
        tasks,
        env={"GITHUB_REF": "refs/pull/9/merge", "AGENTIZED_PR": "9999"},
    )
    assert MSG_TIP_PR_CONFLICT.format(github=9, override=9999) in conflict.errors

    need = validate_tip_hygiene(tasks, env={"GITHUB_EVENT_NAME": "pull_request"})
    assert MSG_TIP_PR_REQUIRED in need.errors

    good = validate_tip_hygiene(tasks, env={"GITHUB_REF": "refs/pull/9/merge"})
    assert good == GateResult(True)

    # Local/push without PR: INDEX only.
    local = validate_tip_hygiene(tasks, env={"GITHUB_EVENT_NAME": "push"})
    assert local == GateResult(True)

    skip_idx = validate_tip_hygiene(
        tasks, pr=9, env={}, check_index=False
    )
    assert skip_idx == GateResult(True)


def test_apply_ready_rules_and_idempotent(tmp_path: Path, monkeypatch):
    with pytest.raises(ValueError, match="ready refuses status"):
        apply_ready(_task("done", extra="acceptance_note: x"), review_note="n")
    with pytest.raises(ValueError, match="ready refuses status"):
        apply_ready(_task("idea"), review_note="n")
    with pytest.raises(ValueError, match="ready refuses status"):
        apply_ready(
            _task("blocked", extra="blocked_reason: x\nblocked_deadline: 2099-01-01"),
            review_note="n",
        )
    with pytest.raises(ValueError, match=MSG_READY_NOTE):
        apply_ready(_task("in-progress"), review_note="")

    src = _task("in-progress", claim="worker")
    once = apply_ready(src, review_note="ready note", pr="#76")
    assert "статус: self-review" in once
    assert f"claim: {CLAIM_EMPTY}" in once
    assert last_progress_entry(once) == READY_PROGRESS
    no_pr = apply_ready(_task("in-progress"), review_note="n", pr="   ")
    assert "pr:" not in no_pr.split("## Цель")[0]

    # Idempotent: second apply returns identical text.
    twice = apply_ready(once, review_note="ignored", pr="#999")
    assert twice == once

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    tid = "T-261121-rdy"
    path = tasks / f"{tid}.md"
    path.write_text(_task("in-progress", claim="owner", task_id=tid), encoding="utf-8")
    out, changed = write_ready(tasks, tid, review_note="ready note", pr="#5")
    assert changed is True and out == path
    body = path.read_text(encoding="utf-8")
    assert f"claim: {CLAIM_EMPTY}" in body
    mtime = path.stat().st_mtime_ns
    index_before = (tasks / "INDEX.md").read_bytes()

    out2, changed2 = write_ready(tasks, tid, review_note="other note", pr="#9")
    assert changed2 is False and out2 == path
    assert path.read_text(encoding="utf-8") == body
    assert path.stat().st_mtime_ns == mtime
    assert (tasks / "INDEX.md").read_bytes() == index_before

    with pytest.raises(FileNotFoundError, match=MSG_READY_MISSING.format(task_id="T-missing")):
        write_ready(tasks, "T-missing", review_note="x")

    # Bad UTF-8 → ValueError gate message, not raw traceback type.
    bad = tasks / "T-261121-bin.md"
    bad.write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="unreadable task file"):
        write_ready(tasks, "T-261121-bin", review_note="n")

    def boom(path: Path) -> str:
        raise OSError("denied")

    monkeypatch.setattr(th, "_read_text", boom)
    with pytest.raises(ValueError, match="unreadable task file"):
        write_ready(tasks, tid, review_note="n")


def test_read_write_helpers_use_text_encoding(tmp_path: Path):
    path = tmp_path / "x.md"
    payload = "статус: open\nЦенность: кириллица\n"
    th._write_text(path, payload)
    assert path.read_bytes() == payload.encode(TEXT_ENCODING)
    assert th._read_text(path) == payload


def test_run_tasks_validate_merges_tip(tmp_path: Path, monkeypatch):
    import agentized.status_gates as sg

    # Isolate from Actions GITHUB_REF on this PR.
    monkeypatch.delenv("GITHUB_REF", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("AGENTIZED_PR", raising=False)
    monkeypatch.delenv("TIP_HYGIENE_PR", raising=False)
    monkeypatch.delenv("GITHUB_PR_NUMBER", raising=False)

    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261121-v.md").write_text(
        _task("in-progress", claim="c", extra="pr: #22", task_id="T-261121-v"),
        encoding="utf-8",
    )
    (tasks / "INDEX.md").write_text("stale\n", encoding="utf-8")

    monkeypatch.setattr(sg, "resolve_validate_base_ref", lambda *a, **k: "BASE")
    monkeypatch.setattr(sg, "previous_task_texts_from_git", lambda *a, **k: {})
    monkeypatch.setattr(sg, "validate_tasks_dir", lambda *a, **k: GateResult(True))

    ref_i, idx_fail = run_tasks_validate(tasks, repo_root=tmp_path)
    assert ref_i == "BASE" and MSG_TIP_INDEX in idx_fail.errors

    _write_index(tasks)
    ref, result = run_tasks_validate(tasks, repo_root=tmp_path, pr=22)
    assert ref == "BASE" and result.ok is False
    assert MSG_TIP_STATUS.format(name="T-261121-v.md", pr=22, st="in-progress") in result.errors

    (tasks / "T-261121-v.md").write_text(
        _task("self-review", extra="pr: #22\nreview_note: tip", task_id="T-261121-v"),
        encoding="utf-8",
    )
    _write_index(tasks)
    ref3, clean = run_tasks_validate(tasks, repo_root=tmp_path, pr="22")
    assert ref3 == "BASE" and clean == GateResult(True)


def test_cli_ready_and_validate(tmp_path: Path, monkeypatch, capsys):
    pytest.importorskip("agentized_cli")
    import agentized_cli as cli

    repo = tmp_path
    ctx = repo / "context" / "tasks"
    ctx.mkdir(parents=True)
    tid = "T-261121-cli"
    (ctx / f"{tid}.md").write_text(_task("in-progress", claim="w", task_id=tid), encoding="utf-8")
    _write_index(ctx)
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo)

    rc = cli.cmd_ready(SimpleNamespace(task_id=tid, review_note="CLI ready", pr="#5", context=None))
    assert rc == 0
    assert "self-review" in (ctx / f"{tid}.md").read_text(encoding="utf-8")
    rc2 = cli.cmd_ready(SimpleNamespace(task_id=tid, review_note="again", pr="#9", context=None))
    assert rc2 == 0
    assert "no-op" in capsys.readouterr().out

    # Refuse non-in-progress via CLI.
    done_id = "T-261121-done"
    (ctx / f"{done_id}.md").write_text(
        _task("done", extra="acceptance_note: x", task_id=done_id), encoding="utf-8"
    )
    bad = cli.cmd_ready(SimpleNamespace(task_id=done_id, review_note="n", pr=None, context=None))
    assert bad == 1
    assert "ready FAIL" in capsys.readouterr().err

    monkeypatch.setattr(
        cli,
        "run_tasks_validate",
        lambda *a, **k: ("R", GateResult(False, ("tip boom",))),
    )
    tv = cli.cmd_tasks_validate(SimpleNamespace(context=None, base=None, pr="5"))
    assert tv == 1
    assert "tip boom" in capsys.readouterr().err
