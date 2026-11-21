"""IO tests for AGE-28 spec_approval_check (mutation-covered)."""
from __future__ import annotations

from pathlib import Path

from agentized.spec_approval_defaults import checked_message, default_spec_approval
from agentized.spec_approval_io import (
    _git_blame_emails,
    _human_participants,
    _resolve_approval_heading,
    approval_committed_by_non_owner,
    ensure_default_in_config,
    load_spec_approval,
    spec_approval_check,
)
from agentized.tasks import render_task_file


def _write_task(
    tasks: Path,
    task_id: str,
    *,
    status: str,
    tags: str,
    claim: str,
    extra: str = "",
) -> None:
    body = render_task_file(task_id, "t", status=status, tags=tags, claim=claim)
    if extra:
        body = body.rstrip() + "\n\n" + extra + "\n"
    (tasks / f"{task_id}.md").write_text(body, encoding="utf-8")


def test_resolve_approval_heading():
    assert _resolve_approval_heading(None) == "## Approval"
    assert _resolve_approval_heading("") == "## Approval"
    assert _resolve_approval_heading("   ") == "## Approval"
    assert _resolve_approval_heading("## Signoff") == "## Signoff"
    assert _resolve_approval_heading("  ## Signoff  ") == "## Signoff"


def test_human_participants_edges(tmp_path: Path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "process-control.json").write_text('{"version":1}\n', encoding="utf-8")
    assert _human_participants(tmp_path, "context") == []

    (ctx / "process-control.json").write_text(
        '{"merge_policy": "x"}\n', encoding="utf-8"
    )
    assert _human_participants(tmp_path, "context") == []

    (ctx / "process-control.json").write_text(
        '{"merge_policy": {"human_participants": "bob"}}\n', encoding="utf-8"
    )
    assert _human_participants(tmp_path, "context") == []

    (ctx / "process-control.json").write_text(
        '{"merge_policy": {"human_participants": [" bob@x.com ", "", "  "]}}\n',
        encoding="utf-8",
    )
    assert _human_participants(tmp_path, "context") == ["bob@x.com"]


def test_git_blame_and_non_owner(tmp_path: Path, monkeypatch):
    from agentized.spec_approval_io import _blame_line_args

    path = tmp_path / "t.md"
    path.write_text(
        "# t\n\n## Spec\n\nPlan.\n\n## Approval\n\napproved-by: bob@example.com\n",
        encoding="utf-8",
    )
    assert _blame_line_args(path, 8) == [
        "git",
        "blame",
        "-L",
        "8,8",
        "--porcelain",
        str(path),
    ]
    assert _blame_line_args(path, 1) == [
        "git",
        "blame",
        "-L",
        "1,1",
        "--porcelain",
        str(path),
    ]

    calls: list[tuple[list[str], dict]] = []

    class Fail:
        returncode = 1
        stdout = ""

    def fail_run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        return Fail()

    monkeypatch.setattr("agentized.spec_approval_io.subprocess.run", fail_run)
    assert _git_blame_emails(tmp_path, path, 1) == set()
    assert calls[-1][0] == _blame_line_args(path, 1)
    assert calls[-1][1] == {
        "cwd": str(tmp_path),
        "capture_output": True,
        "text": True,
    }
    assert approval_committed_by_non_owner(tmp_path, path, "alice") is False

    class Ok:
        returncode = 0
        stdout = (
            "abc\n"
            "author-mail <alice@example.com>\n"
            "author-mail <not.committed.yet>\n"
            "author-mail bob\n"
            "author-mail <bob@example.com>\n"
            "author-mail <charlie@example.com> trailing\n"
        )

    def ok_run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        return Ok()

    monkeypatch.setattr("agentized.spec_approval_io.subprocess.run", ok_run)
    assert _git_blame_emails(tmp_path, path, 8) == {
        "alice@example.com",
        "bob@example.com",
    }
    assert calls[-1][0] == _blame_line_args(path, 8)
    assert calls[-1][1]["cwd"] == str(tmp_path)
    assert calls[-1][1]["capture_output"] is True
    assert calls[-1][1]["text"] is True

    # angle-local without @ must be ignored (kills `@ in mail or …` mutant)
    class NoAt:
        returncode = 0
        stdout = "author-mail <bob>\nauthor-mail <not.committed.yet>\n"

    monkeypatch.setattr(
        "agentized.spec_approval_io.subprocess.run", lambda *a, **k: NoAt()
    )
    assert _git_blame_emails(tmp_path, path, 1) == set()

    from agentized.spec_approval_io import _git_blame_emails as real_blame

    blame_calls: list[tuple] = []

    def capture_blame(root, task_path, line_no):
        blame_calls.append((root, task_path, line_no))
        return {"bob@example.com"}

    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails", capture_blame
    )
    assert approval_committed_by_non_owner(tmp_path, path, "alice") is True
    assert blame_calls == [(tmp_path, path, 9)]
    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails", real_blame
    )

    class OwnerOnly:
        returncode = 0
        stdout = "author-mail <alice@example.com>\n"

    monkeypatch.setattr(
        "agentized.spec_approval_io.subprocess.run", lambda *a, **k: OwnerOnly()
    )
    assert (
        approval_committed_by_non_owner(
            tmp_path, path, "Alice <alice@example.com>"
        )
        is False
    )
    assert approval_committed_by_non_owner(tmp_path, path, "alice") is False
    assert approval_committed_by_non_owner(tmp_path, Path("/no/such"), "alice") is False

    # Spec approved-by must not leak; only Approval-section lines count
    stray = tmp_path / "stray.md"
    stray.write_text(
        "# t\n## Spec\napproved-by: bob@example.com\n"
        "## Approval\napproved-by: alice\n",
        encoding="utf-8",
    )
    blame_lines: list[int] = []

    def capture_line(root, task_path, line_no):
        blame_lines.append(line_no)
        return (
            {"bob@example.com"} if line_no == 3 else {"alice@example.com"}
        )

    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails", capture_line
    )
    assert (
        approval_committed_by_non_owner(
            tmp_path, stray, "Alice <alice@example.com>"
        )
        is False
    )
    assert blame_lines == [5]

    custom = tmp_path / "custom.md"
    custom.write_text(
        "# t\n\n## Signoff\napproved-by: bob@example.com\n", encoding="utf-8"
    )
    blame_lines.clear()

    def bob_blame(root, task_path, line_no):
        blame_lines.append(line_no)
        return {"bob@example.com"}

    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails", bob_blame
    )
    assert (
        approval_committed_by_non_owner(
            tmp_path, custom, "alice", approval_heading="## Signoff"
        )
        is True
    )
    assert blame_lines == [4]
    assert approval_committed_by_non_owner(tmp_path, custom, "alice") is False
    missing = tmp_path / "missing.md"
    missing.write_text("# t\n## Spec\nok\n", encoding="utf-8")
    assert approval_committed_by_non_owner(tmp_path, missing, "alice") is False

    bounded = tmp_path / "bounded.md"
    bounded.write_text(
        "# t\n## Approval\napproved-by: alice\n## Other\n"
        "approved-by: bob@example.com\n",
        encoding="utf-8",
    )
    blame_lines.clear()

    def section_blame(root, task_path, line_no):
        blame_lines.append(line_no)
        return {"alice@example.com"} if line_no == 3 else {"bob@example.com"}

    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails", section_blame
    )
    assert (
        approval_committed_by_non_owner(
            tmp_path, bounded, "Alice <alice@example.com>"
        )
        is False
    )
    assert blame_lines == [3]

    tight = tmp_path / "tight.md"
    tight.write_text(
        "# t\n## Approval\napproved-by: bob@example.com\n", encoding="utf-8"
    )
    blame_lines.clear()
    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails", bob_blame
    )
    assert approval_committed_by_non_owner(tmp_path, tight, "alice") is True
    assert blame_lines == [3]
    assert (
        approval_committed_by_non_owner(
            tmp_path, tight, "alice", approval_heading=""
        )
        is True
    )
    assert (
        approval_committed_by_non_owner(
            tmp_path, tight, "alice", approval_heading=None  # type: ignore[arg-type]
        )
        is True
    )


def test_spec_approval_check_disabled_and_enforced(tmp_path: Path, monkeypatch):
    root = tmp_path
    ctx = root / "context"
    tasks = ctx / "tasks"
    tasks.mkdir(parents=True)
    (ctx / "process-control.json").write_text(
        '{"version":1,"spec_approval":{"enabled":false},'
        '"merge_policy":{"human_participants":["bob@example.com"]}}\n',
        encoding="utf-8",
    )
    _write_task(
        tasks,
        "T-260101-aaaa",
        status="in-progress",
        tags="complex",
        claim="alice",
    )
    disabled = spec_approval_check(root)
    assert disabled == {
        "ok": True,
        "mode": "disabled",
        "message": "",
        "failures": [],
        "checked": 0,
    }

    policy = default_spec_approval()
    policy["enabled"] = True
    monkeypatch.setattr(
        "agentized.spec_approval_io.approval_committed_by_non_owner",
        lambda *a, **k: False,
    )
    refused = spec_approval_check(root, policy=policy)
    assert refused["ok"] is False
    assert refused["mode"] == "refuse"
    assert refused["checked"] == 1
    assert len(refused["failures"]) == 1

    _write_task(
        tasks,
        "T-260101-bbbb",
        status="in-progress",
        tags="complex",
        claim="alice",
        extra="## Spec\n\nDo it.\n\n## Approval\n\napproved-by: bob@example.com\n",
    )
    _write_task(
        tasks,
        "T-260101-eeee",
        status="done",
        tags="complex",
        claim="alice",
        extra="## Spec\n\nDone plan.\n\n## Approval\n\napproved-by: bob@example.com\n",
    )
    _write_task(
        tasks,
        "T-260101-cccc",
        status="open",
        tags="complex",
        claim="alice",
    )
    _write_task(
        tasks,
        "T-260101-dddd",
        status="in-progress",
        tags="simple",
        claim="alice",
    )
    still = spec_approval_check(root, policy=policy)
    assert still["ok"] is False
    # aaaa fail + bbbb ok; done/open/simple exempt
    assert still["checked"] == 2
    # second failing complex task so FAILURE_JOIN is exercised
    _write_task(
        tasks,
        "T-260101-gggg",
        status="in-progress",
        tags="complex",
        claim="alice",
    )
    multi = spec_approval_check(root, policy=policy)
    assert multi["ok"] is False
    assert "; " in multi["message"]
    assert "None" not in multi["message"]
    (tasks / "T-260101-gggg.md").unlink()

    (tasks / "T-260101-aaaa.md").unlink()
    _write_task(
        tasks,
        "T-260101-ffff",
        status="blocked",
        tags="complex",
        claim="alice",
        extra="## Spec\n\nBlocked plan.\n\n## Approval\n\napproved-by: bob@example.com\n",
    )
    ok = spec_approval_check(root, policy=policy)
    assert ok["ok"] is True
    assert ok["mode"] == "ok"
    assert ok["checked"] == 2
    assert ok["failures"] == []
    assert ok["message"] == checked_message(2)

    # non-default context_rel must be passed through (kills dropped-arg mutants)
    alt = root / "altctx"
    (alt / "tasks").mkdir(parents=True)
    (alt / "process-control.json").write_text(
        '{"version":1,"spec_approval":{"enabled":true},'
        '"merge_policy":{"human_participants":["carol@alt.example"]}}\n',
        encoding="utf-8",
    )
    assert load_spec_approval(root, "altctx")["enabled"] is True
    assert load_spec_approval(root, "context")["enabled"] is False
    assert _human_participants(root, "altctx") == ["carol@alt.example"]
    assert _human_participants(root, "context") == ["bob@example.com"]
    alt_on = spec_approval_check(root, context_rel="altctx")
    assert alt_on["mode"] != "disabled"

    # non-owner path can pass without allowlist match; args must be exact
    _write_task(
        tasks,
        "T-260101-ffff",
        status="blocked",
        tags="complex",
        claim="alice",
        extra="## Spec\n\nReal.\n\n## Approval\n\napproved-by: alice\n",
    )
    non_owner_calls: list[tuple] = []
    eval_claims: list[object] = []

    def spy_non_owner(root_arg, task_path, claim, approval_heading=None):
        non_owner_calls.append((root_arg, task_path, claim, approval_heading))
        return True

    real_eval = __import__(
        "agentized.spec_approval", fromlist=["evaluate_task_spec"]
    ).evaluate_task_spec

    def spy_eval(**kwargs):
        eval_claims.append(kwargs.get("claim"))
        return real_eval(**kwargs)

    monkeypatch.setattr(
        "agentized.spec_approval_io.approval_committed_by_non_owner",
        spy_non_owner,
    )
    monkeypatch.setattr(
        "agentized.spec_approval_io.evaluate_task_spec",
        spy_eval,
    )
    via_git = spec_approval_check(root, policy=policy)
    assert via_git["ok"] is True
    assert non_owner_calls
    for root_arg, task_path, claim, heading in non_owner_calls:
        assert root_arg is root
        assert task_path is not None
        assert claim is not None
        assert heading == "## Approval"
    assert "alice" in eval_claims

    loaded = load_spec_approval(root)
    assert loaded["enabled"] is False
    merged = ensure_default_in_config({"version": 1})
    assert merged["spec_approval"]["enabled"] is False
    keep = ensure_default_in_config({"spec_approval": {"enabled": True}})
    assert keep["spec_approval"]["enabled"] is True


def test_blocked_lane_is_checked(tmp_path: Path, monkeypatch):
    root = tmp_path
    ctx = root / "context"
    tasks = ctx / "tasks"
    tasks.mkdir(parents=True)
    (ctx / "process-control.json").write_text(
        '{"version":1,"spec_approval":{"enabled":true},'
        '"merge_policy":{"human_participants":["bob@example.com"]}}\n',
        encoding="utf-8",
    )
    _write_task(
        tasks,
        "T-260101-ffff",
        status="blocked",
        tags="complex",
        claim="alice",
    )
    monkeypatch.setattr(
        "agentized.spec_approval_io.approval_committed_by_non_owner",
        lambda *a, **k: False,
    )
    result = spec_approval_check(root)
    assert result["ok"] is False
    assert result["checked"] == 1


def test_custom_approval_heading_passed_to_blame(tmp_path: Path, monkeypatch):
    root = tmp_path
    ctx = root / "context"
    tasks = ctx / "tasks"
    tasks.mkdir(parents=True)
    (ctx / "process-control.json").write_text(
        '{"version":1,"spec_approval":{"enabled":true,'
        '"approval_heading":"## Signoff"},'
        '"merge_policy":{"human_participants":["bob@example.com"]}}\n',
        encoding="utf-8",
    )
    _write_task(
        tasks,
        "T-260101-hhhh",
        status="in-progress",
        tags="complex",
        claim="alice",
        extra="## Spec\n\nPlan.\n\n## Signoff\n\napproved-by: bob@example.com\n",
    )
    seen: list[str] = []

    def spy(root_arg, task_path, claim, approval_heading=None):
        seen.append(approval_heading)
        return False

    monkeypatch.setattr(
        "agentized.spec_approval_io.approval_committed_by_non_owner", spy
    )
    out = spec_approval_check(root)
    assert out["ok"] is True
    assert seen == ["## Signoff"]
