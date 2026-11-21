"""AGE-76 tip hygiene: PR-linked tasks + INDEX freshness + ready flip."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agentized.status_gates import TEXT_ENCODING, GateResult, run_tasks_validate
from agentized.task_schema import PLACEHOLDER_CLAIM, last_progress_entry, rebuild_task_index
from agentized import tip_hygiene as th
from agentized.tip_hygiene import (
    ENV_PR_KEYS,
    MSG_READY_MISSING,
    MSG_READY_NOTE,
    MSG_TIP_CLAIM,
    MSG_TIP_INDEX,
    MSG_TIP_STATUS,
    MSG_TIP_UNREADABLE,
    READY_PROGRESS,
    TIP_OK_STATUSES,
    apply_ready,
    claim_is_held,
    extract_pr_number,
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
    claim: str = "_(пусто)_",
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


def test_extract_and_resolve_pr_number(monkeypatch):
    assert extract_pr_number(None) is extract_pr_number("") is extract_pr_number("  ") is None
    assert extract_pr_number("nope") is None
    assert extract_pr_number("#52") == 52
    assert extract_pr_number("PR #7") == 7
    assert extract_pr_number("pr#9") == 9
    assert extract_pr_number("https://github.com/mpodreshetnikov/agentized/pull/46") == 46
    assert extract_pr_number("https://github.com/mpodreshetnikov/agentized/pull/46?x=1") == 46
    # Isolate from CI GITHUB_REF (refs/pull/N/merge) — empty env, not os.environ.
    assert resolve_pr_number(explicit=None, env={}) is None
    assert resolve_pr_number(explicit=0) is None
    assert resolve_pr_number(explicit=-3) is None
    assert resolve_pr_number(explicit=1) == 1
    assert resolve_pr_number(explicit=12) == 12
    assert resolve_pr_number(explicit="#99") == 99
    assert resolve_pr_number(explicit="#0") is None
    assert resolve_pr_number(explicit="PR #3") == 3
    assert resolve_pr_number(explicit="1") == 1
    assert resolve_pr_number(explicit="77") == 77
    assert resolve_pr_number(explicit="  12  ") == 12
    assert resolve_pr_number(explicit="bad") is None
    assert resolve_pr_number(env={}) is None
    assert resolve_pr_number(env={"AGENTIZED_PR": "41"}) == 41
    assert resolve_pr_number(env={"AGENTIZED_PR": "1"}) == 1
    assert resolve_pr_number(env={"AGENTIZED_PR": "  ", "TIP_HYGIENE_PR": "44"}) == 44
    assert resolve_pr_number(env={"TIP_HYGIENE_PR": "#8"}) == 8
    assert resolve_pr_number(env={"GITHUB_PR_NUMBER": "15"}) == 15
    assert extract_pr_number("1") == 1
    assert extract_pr_number("01") == 1
    assert resolve_pr_number(env={"GITHUB_REF": "refs/pull/52/merge"}) == 52
    assert resolve_pr_number(env={"GITHUB_REF": "refs/pull/1/head"}) == 1
    assert resolve_pr_number(env={"GITHUB_REF": "refs/pull/0/merge"}) is None
    assert resolve_pr_number(env={"GITHUB_REF": "refs/heads/main"}) is None
    assert resolve_pr_number(env={"GITHUB_REF": ""}) is None
    assert resolve_pr_number(explicit=5, env={"AGENTIZED_PR": "9"}) == 5
    assert resolve_pr_number(env={"AGENTIZED_PR": "", "GITHUB_REF": "refs/pull/2/head"}) == 2
    assert (
        resolve_pr_number(
            env={"AGENTIZED_PR": "nope", "TIP_HYGIENE_PR": "0", "GITHUB_PR_NUMBER": "6"}
        )
        == 6
    )
    # Non-digit PR-shaped env must keep original text (not force #prefix).
    assert resolve_pr_number(env={"AGENTIZED_PR": "PR #88"}) == 88
    assert ENV_PR_KEYS == ("AGENTIZED_PR", "TIP_HYGIENE_PR", "GITHUB_PR_NUMBER")
    assert TIP_OK_STATUSES == frozenset({"self-review", "done"})
    # os.environ path (env=None)
    monkeypatch.setenv("AGENTIZED_PR", "33")
    monkeypatch.delenv("TIP_HYGIENE_PR", raising=False)
    monkeypatch.delenv("GITHUB_PR_NUMBER", raising=False)
    monkeypatch.delenv("GITHUB_REF", raising=False)
    assert resolve_pr_number() == 33
    # Missing keys must not invent placeholder values.
    seen: list[str] = []
    monkeypatch.setattr(th, "extract_pr_number", lambda v: seen.append(v) or None)
    assert resolve_pr_number(env={"GITHUB_REF": "refs/heads/x"}) is None
    assert seen == []


def test_claim_and_pr_match():
    claims = (None, "", "_(пусто)_", PLACEHOLDER_CLAIM, "worker", "  agent-x  ")
    assert [claim_is_held(c) for c in claims] == [False, False, False, False, True, True]
    assert [
        task_points_at_pr(None, 1),
        task_points_at_pr("#2", 2),
        task_points_at_pr("#2", 3),
        task_points_at_pr("https://github.com/o/r/pull/10", 10),
    ] == [False, True, False, True]


def test_index_freshness(tmp_path: Path, monkeypatch):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T-261121-a.md").write_text(_task("open"), encoding="utf-8")
    assert validate_index_freshness(tasks) == GateResult(False, (MSG_TIP_INDEX,))
    (tasks / "INDEX.md").write_text("stale\n", encoding="utf-8")
    assert validate_index_freshness(tasks) == GateResult(False, (MSG_TIP_INDEX,))
    (tasks / "INDEX.md").write_text(rebuild_task_index(tasks), encoding="utf-8")
    assert validate_index_freshness(tasks) == GateResult(True)
    real = th._read_text

    def boom(path: Path) -> str:
        if path.name == "INDEX.md":
            raise OSError("busy")
        return real(path)

    monkeypatch.setattr(th, "_read_text", boom)
    assert validate_index_freshness(tasks) == GateResult(False, (MSG_TIP_INDEX,))
    monkeypatch.setattr(th, "_read_text", real)
    (tasks / "INDEX.md").unlink()
    assert validate_index_freshness(tasks) == GateResult(False, (MSG_TIP_INDEX,))


def test_pr_linked_tasks_status_and_claim(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T-261121-ok.md").write_text(
        _task("self-review", extra="pr: #76\nreview_note: green", task_id="T-261121-ok"),
        encoding="utf-8",
    )
    (tasks / "T-261121-other.md").write_text(
        _task("in-progress", claim="x", extra="pr: #1", task_id="T-261121-other"),
        encoding="utf-8",
    )
    assert validate_pr_linked_tasks(tasks, 76) == GateResult(True)

    (tasks / "T-261121-dirty.md").write_text(
        _task("in-progress", claim="tip-worker", extra="pr: #76", task_id="T-261121-dirty"),
        encoding="utf-8",
    )
    bad = validate_pr_linked_tasks(tasks, 76)
    assert bad.ok is False
    assert MSG_TIP_STATUS.format(name="T-261121-dirty.md", pr=76, st="in-progress") in bad.errors
    assert MSG_TIP_CLAIM.format(name="T-261121-dirty.md", pr=76, claim="tip-worker") in bad.errors

    (tasks / "T-261121-done.md").write_text(
        _task(
            "done",
            claim="still-held",
            extra="pr: PR #76\nacceptance_note: landed",
            task_id="T-261121-done",
        ),
        encoding="utf-8",
    )
    done_bad = validate_pr_linked_tasks(tasks, 76)
    assert (
        MSG_TIP_CLAIM.format(name="T-261121-done.md", pr=76, claim="still-held") in done_bad.errors
    )
    assert not any("T-261121-done.md" in e and "must be self-review" in e for e in done_bad.errors)

    # Empty claim on self-review must pass (placeholder / missing).
    (tasks / "T-261121-empty.md").write_text(
        _task("self-review", claim="", extra="pr: #76\nreview_note: ok", task_id="T-261121-empty"),
        encoding="utf-8",
    )
    # Missing claim key entirely
    bare = _task("self-review", extra="pr: #76\nreview_note: ok", task_id="T-261121-bare")
    bare = "\n".join(ln for ln in bare.splitlines() if not ln.startswith("claim:")) + "\n"
    (tasks / "T-261121-bare.md").write_text(bare, encoding="utf-8")
    clean = validate_pr_linked_tasks(tasks, 76)
    assert not any("T-261121-empty.md" in e or "T-261121-bare.md" in e for e in clean.errors)


def test_continue_not_break_on_unreadable(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T-261121-aaa.md").write_bytes(b"\xff\xfe not-utf8 \x80")
    (tasks / "T-261121-zzz.md").write_text(
        _task("in-progress", claim="c", extra="pr: #3", task_id="T-261121-zzz"),
        encoding="utf-8",
    )
    res = validate_pr_linked_tasks(tasks, 3)
    assert any("T-261121-aaa.md" in e and "unreadable" in e for e in res.errors)
    assert MSG_TIP_STATUS.format(name="T-261121-zzz.md", pr=3, st="in-progress") in res.errors
    assert MSG_TIP_CLAIM.format(name="T-261121-zzz.md", pr=3, claim="c") in res.errors
    unread = [e for e in res.errors if e.startswith("T-261121-aaa.md:")][0]
    assert unread.startswith("T-261121-aaa.md: tip hygiene: unreadable task file: ")
    assert "None" not in unread
    assert "utf-8" in unread or "UTF" in unread or "codec" in unread

    # Non-matching first file must continue (not break) into a later match.
    tasks2 = tmp_path / "tasks2"
    tasks2.mkdir()
    (tasks2 / "T-261121-aaa.md").write_text(
        _task("in-progress", claim="x", extra="pr: #1", task_id="T-261121-aaa"),
        encoding="utf-8",
    )
    (tasks2 / "T-261121-zzz.md").write_text(
        _task("in-progress", claim="c", extra="pr: #3", task_id="T-261121-zzz"),
        encoding="utf-8",
    )
    res2 = validate_pr_linked_tasks(tasks2, 3)
    assert MSG_TIP_STATUS.format(name="T-261121-zzz.md", pr=3, st="in-progress") in res2.errors


def test_validate_tip_hygiene_combines(tmp_path: Path, monkeypatch):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T-261121-x.md").write_text(
        _task("in-progress", claim="w", extra="pr: #9", task_id="T-261121-x"),
        encoding="utf-8",
    )
    (tasks / "INDEX.md").write_text("wrong\n", encoding="utf-8")
    both = validate_tip_hygiene(tasks, pr_number=9)
    assert MSG_TIP_INDEX in both.errors
    assert any("T-261121-x.md" in e for e in both.errors)

    skip_idx = validate_tip_hygiene(tasks, pr_number=9, check_index=False)
    assert MSG_TIP_INDEX not in skip_idx.errors
    assert skip_idx.ok is False

    none_pr = validate_tip_hygiene(tasks, pr_number=None, check_index=False)
    assert none_pr == GateResult(True)

    called: list[int] = []
    monkeypatch.setattr(
        th,
        "validate_pr_linked_tasks",
        lambda d, n: called.append(n) or GateResult(True),
    )
    assert validate_tip_hygiene(tasks, pr_number=0, check_index=False) == GateResult(True)
    assert called == []
    assert validate_tip_hygiene(tasks, pr_number=1, check_index=False) == GateResult(True)
    assert called == [1]

    (tasks / "T-261121-x.md").write_text(
        _task("self-review", extra="pr: #9\nreview_note: ok", task_id="T-261121-x"),
        encoding="utf-8",
    )
    monkeypatch.setattr(th, "validate_pr_linked_tasks", validate_pr_linked_tasks)
    (tasks / "INDEX.md").write_text(rebuild_task_index(tasks), encoding="utf-8")
    assert validate_tip_hygiene(tasks, pr_number=9) == GateResult(True)


def test_apply_ready_and_write(tmp_path: Path):
    with pytest.raises(ValueError, match=MSG_READY_NOTE):
        apply_ready(_task("in-progress", claim="w"), review_note="")
    with pytest.raises(ValueError, match=MSG_READY_NOTE):
        apply_ready(_task("in-progress", claim="w"), review_note="_(пусто)_")

    text = apply_ready(
        _task("in-progress", claim="tip-hygiene-worker"),
        review_note="Tip abc123 CI green; never merge.",
        pr="#76",
    )
    assert "статус: self-review" in text
    assert f"claim: {PLACEHOLDER_CLAIM}" in text
    assert "review_note: Tip abc123 CI green; never merge." in text
    assert "pr: #76" in text
    assert "статус → self-review" in text
    assert last_progress_entry(text) == READY_PROGRESS

    no_pr = apply_ready(
        _task("in-progress", claim="w"),
        review_note="note without pr field",
        pr="   ",
    )
    assert "pr:" not in no_pr.split("## Цель")[0]

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    tid = "T-261121-rdy"
    (tasks / f"{tid}.md").write_text(
        _task("in-progress", claim="owner", task_id=tid),
        encoding="utf-8",
    )
    out = write_ready(tasks, tid, review_note="ready note", pr="https://github.com/o/r/pull/3")
    assert out.name == f"{tid}.md"
    body = out.read_text(encoding="utf-8")
    assert "статус: self-review" in body
    assert "pr: https://github.com/o/r/pull/3" in body
    assert f"claim: {PLACEHOLDER_CLAIM}" in body
    assert last_progress_entry(body) == READY_PROGRESS
    assert (tasks / "INDEX.md").read_text(encoding="utf-8") == rebuild_task_index(tasks)

    with pytest.raises(FileNotFoundError, match=MSG_READY_MISSING.format(task_id="T-missing")):
        write_ready(tasks, "T-missing", review_note="x")


def test_read_write_helpers_use_text_encoding(tmp_path: Path):
    path = tmp_path / "x.md"
    payload = "статус: open\nЦенность: кириллица\n"
    th._write_text(path, payload)
    assert path.read_bytes() == payload.encode(TEXT_ENCODING)
    assert th._read_text(path) == payload
    assert TEXT_ENCODING == "utf-8"


def test_run_tasks_validate_merges_tip(tmp_path: Path, monkeypatch):
    import agentized.status_gates as sg

    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261121-v.md").write_text(
        _task("in-progress", claim="c", extra="pr: #22", task_id="T-261121-v"),
        encoding="utf-8",
    )
    (tasks / "INDEX.md").write_text("stale-index\n", encoding="utf-8")

    monkeypatch.setattr(sg, "resolve_validate_base_ref", lambda *a, **k: "BASE")
    monkeypatch.setattr(sg, "previous_task_texts_from_git", lambda *a, **k: {})
    monkeypatch.setattr(sg, "validate_tasks_dir", lambda *a, **k: GateResult(True))

    # Stale INDEX alone must fail tip hygiene via check_index=True default.
    ref_i, idx_fail = run_tasks_validate(tasks, repo_root=tmp_path, tip_hygiene=True)
    assert ref_i == "BASE" and MSG_TIP_INDEX in idx_fail.errors

    (tasks / "INDEX.md").write_text(rebuild_task_index(tasks), encoding="utf-8")
    ref, result = run_tasks_validate(tasks, repo_root=tmp_path, pr=22)
    assert ref == "BASE" and result.ok is False
    assert MSG_TIP_STATUS.format(name="T-261121-v.md", pr=22, st="in-progress") in result.errors
    assert MSG_TIP_CLAIM.format(name="T-261121-v.md", pr=22, claim="c") in result.errors

    ref2, ok = run_tasks_validate(tasks, repo_root=tmp_path, tip_hygiene=False)
    assert ref2 == "BASE" and ok == GateResult(True)

    (tasks / "T-261121-v.md").write_text(
        _task("self-review", extra="pr: #22\nreview_note: tip", task_id="T-261121-v"),
        encoding="utf-8",
    )
    (tasks / "INDEX.md").write_text(rebuild_task_index(tasks), encoding="utf-8")
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
    (ctx / "INDEX.md").write_text(rebuild_task_index(ctx), encoding="utf-8")
    monkeypatch.setattr(cli, "find_repo_root", lambda: repo)

    rc = cli.cmd_ready(SimpleNamespace(task_id=tid, review_note="CLI ready", pr="#5", context=None))
    assert rc == 0
    body = (ctx / f"{tid}.md").read_text(encoding="utf-8")
    assert "статус: self-review" in body and "pr: #5" in body
    claim_line = [
        ln.split(":", 1)[1].strip() for ln in body.splitlines() if ln.startswith("claim:")
    ][0]
    assert [claim_is_held(claim_line)] == [False]

    monkeypatch.setattr(
        cli,
        "run_tasks_validate",
        lambda *a, **k: ("R", GateResult(False, ("tip boom",))),
    )
    bad = cli.cmd_tasks_validate(
        SimpleNamespace(context=None, base=None, pr="5", no_tip_hygiene=False)
    )
    assert bad == 1
    err = capsys.readouterr().err
    assert "tasks-validate FAIL" in err and "tip boom" in err
