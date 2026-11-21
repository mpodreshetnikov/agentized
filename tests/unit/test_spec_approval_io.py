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

SPEC_OK = "## Spec\n\nDo it.\n\n## Approval\n\napproved-by: bob@example.com\n"
SPEC_DONE = "## Spec\n\nDone plan.\n\n## Approval\n\napproved-by: bob@example.com\n"
SPEC_BLK = "## Spec\n\nBlocked plan.\n\n## Approval\n\napproved-by: bob@example.com\n"
SPEC_OWN = "## Spec\n\nReal.\n\n## Approval\n\napproved-by: alice\n"
SPEC_SO = "## Spec\n\nPlan.\n\n## Signoff\n\napproved-by: bob@example.com\n"


def _wt(tasks: Path, tid: str, st="in-progress", tags="complex", claim="alice", extra="") -> None:
    body = render_task_file(tid, "t", status=st, tags=tags, claim=claim)
    if extra:
        body = body.rstrip() + "\n\n" + extra + "\n"
    (tasks / f"{tid}.md").write_text(body, encoding="utf-8")


def test_resolve_and_participants(tmp_path: Path):
    assert _resolve_approval_heading(None) == "## Approval"
    assert _resolve_approval_heading("") == "## Approval"
    assert _resolve_approval_heading("   ") == "## Approval"
    assert _resolve_approval_heading("## Signoff") == "## Signoff"
    assert _resolve_approval_heading("  ## Signoff  ") == "## Signoff"
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "process-control.json").write_text('{"version":1}\n', encoding="utf-8")
    assert _human_participants(tmp_path, "context") == []
    (ctx / "process-control.json").write_text('{"merge_policy": "x"}\n', encoding="utf-8")
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
    from agentized import spec_approval_io as io_mod
    from agentized.spec_approval_io import _blame_line_args

    real_blame = io_mod._git_blame_emails
    path = tmp_path / "t.md"
    path.write_text(
        "# t\n\n## Spec\n\nPlan.\n\n## Approval\n\napproved-by: bob@example.com\n",
        encoding="utf-8",
    )
    assert _blame_line_args(path, 8) == ["git", "blame", "-L", "8,8", "--porcelain", str(path)]
    calls: list = []

    class Fail:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(
        "agentized.spec_approval_io.subprocess.run",
        lambda cmd, **kw: calls.append((list(cmd), dict(kw))) or Fail(),
    )
    assert _git_blame_emails(tmp_path, path, 1) == set()
    assert calls[-1][0] == _blame_line_args(path, 1)
    assert calls[-1][1] == {"cwd": str(tmp_path), "capture_output": True, "text": True}
    assert approval_committed_by_non_owner(tmp_path, path, "alice") is False

    class Ok:
        returncode = 0
        stdout = (
            "abc\nauthor-mail <alice@example.com>\nauthor-mail <not.committed.yet>\n"
            "author-mail bob\nauthor-mail <bob@example.com>\n"
            "author-mail <charlie@example.com> trailing\n"
        )

    monkeypatch.setattr(
        "agentized.spec_approval_io.subprocess.run",
        lambda cmd, **kw: calls.append((list(cmd), dict(kw))) or Ok(),
    )
    assert _git_blame_emails(tmp_path, path, 8) == {"alice@example.com", "bob@example.com"}
    assert calls[-1][0] == _blame_line_args(path, 8)

    class NoAt:
        returncode = 0
        stdout = "author-mail <bob>\nauthor-mail <not.committed.yet>\n"

    monkeypatch.setattr("agentized.spec_approval_io.subprocess.run", lambda *a, **k: NoAt())
    assert _git_blame_emails(tmp_path, path, 1) == set()

    blame_calls: list = []
    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails",
        lambda r, p, n: blame_calls.append((r, p, n)) or {"bob@example.com"},
    )
    assert approval_committed_by_non_owner(tmp_path, path, "alice") is True
    assert blame_calls == [(tmp_path, path, 9)]

    class OwnerOnly:
        returncode = 0
        stdout = "author-mail <alice@example.com>\n"

    monkeypatch.setattr("agentized.spec_approval_io.subprocess.run", lambda *a, **k: OwnerOnly())
    monkeypatch.setattr("agentized.spec_approval_io._git_blame_emails", real_blame)
    assert approval_committed_by_non_owner(tmp_path, path, "Alice <alice@example.com>") is False
    assert approval_committed_by_non_owner(tmp_path, path, "alice") is False
    assert approval_committed_by_non_owner(tmp_path, Path("/no/such"), "alice") is False

    stray = tmp_path / "stray.md"
    stray.write_text(
        "# t\n## Spec\napproved-by: bob@example.com\n## Approval\napproved-by: alice\n",
        encoding="utf-8",
    )
    lines: list[int] = []
    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails",
        lambda r, p, n: (
            lines.append(n) or ({"bob@example.com"} if n == 3 else {"alice@example.com"})
        ),
    )
    assert approval_committed_by_non_owner(tmp_path, stray, "Alice <alice@example.com>") is False
    assert lines == [5]

    custom = tmp_path / "custom.md"
    custom.write_text("# t\n\n## Signoff\napproved-by: bob@example.com\n", encoding="utf-8")
    lines.clear()
    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails",
        lambda r, p, n: lines.append(n) or {"bob@example.com"},
    )
    assert approval_committed_by_non_owner(tmp_path, custom, "alice", "## Signoff") is True
    assert lines == [4]
    assert approval_committed_by_non_owner(tmp_path, custom, "alice") is False
    missing = tmp_path / "missing.md"
    missing.write_text("# t\n## Spec\nok\n", encoding="utf-8")
    assert approval_committed_by_non_owner(tmp_path, missing, "alice") is False

    bounded = tmp_path / "bounded.md"
    bounded.write_text(
        "# t\n## Approval\napproved-by: alice\n## Other\napproved-by: bob@example.com\n",
        encoding="utf-8",
    )
    lines.clear()
    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails",
        lambda r, p, n: (
            lines.append(n) or ({"alice@example.com"} if n == 3 else {"bob@example.com"})
        ),
    )
    assert approval_committed_by_non_owner(tmp_path, bounded, "Alice <alice@example.com>") is False
    assert lines == [3]

    tight = tmp_path / "tight.md"
    tight.write_text("# t\n## Approval\napproved-by: bob@example.com\n", encoding="utf-8")
    lines.clear()
    monkeypatch.setattr(
        "agentized.spec_approval_io._git_blame_emails",
        lambda r, p, n: lines.append(n) or {"bob@example.com"},
    )
    assert approval_committed_by_non_owner(tmp_path, tight, "alice") is True
    assert lines == [3]
    assert approval_committed_by_non_owner(tmp_path, tight, "alice", "") is True
    assert approval_committed_by_non_owner(tmp_path, tight, "alice", None) is True  # type: ignore[arg-type]


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
    _wt(tasks, "T-260101-aaaa")
    assert spec_approval_check(root) == {
        "ok": True,
        "mode": "disabled",
        "message": "",
        "failures": [],
        "checked": 0,
    }
    policy = default_spec_approval()
    policy["enabled"] = True
    monkeypatch.setattr(
        "agentized.spec_approval_io.approval_committed_by_non_owner", lambda *a, **k: False
    )
    refused = spec_approval_check(root, policy=policy)
    assert refused["ok"] is False and refused["mode"] == "refuse" and refused["checked"] == 1

    _wt(tasks, "T-260101-bbbb", extra=SPEC_OK)
    _wt(tasks, "T-260101-eeee", st="done", extra=SPEC_DONE)
    _wt(tasks, "T-260101-cccc", st="open")
    _wt(tasks, "T-260101-dddd", tags="simple")
    still = spec_approval_check(root, policy=policy)
    assert still["ok"] is False and still["checked"] == 2
    _wt(tasks, "T-260101-gggg")
    multi = spec_approval_check(root, policy=policy)
    assert multi["ok"] is False and "; " in multi["message"] and "None" not in multi["message"]
    (tasks / "T-260101-gggg.md").unlink()
    (tasks / "T-260101-aaaa.md").unlink()
    _wt(tasks, "T-260101-ffff", st="blocked", extra=SPEC_BLK)
    ok = spec_approval_check(root, policy=policy)
    assert ok == {
        "ok": True,
        "mode": "ok",
        "checked": 2,
        "failures": [],
        "message": checked_message(2),
    }

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
    assert spec_approval_check(root, context_rel="altctx")["mode"] != "disabled"

    _wt(tasks, "T-260101-ffff", st="blocked", extra=SPEC_OWN)
    non_owner_calls: list = []
    eval_claims: list = []
    real_eval = __import__(
        "agentized.spec_approval", fromlist=["evaluate_task_spec"]
    ).evaluate_task_spec

    def spy_non_owner(root_arg, task_path, claim, approval_heading=None):
        non_owner_calls.append((root_arg, task_path, claim, approval_heading))
        return True

    def spy_eval(**kwargs):
        eval_claims.append(kwargs.get("claim"))
        return real_eval(**kwargs)

    monkeypatch.setattr("agentized.spec_approval_io.approval_committed_by_non_owner", spy_non_owner)
    monkeypatch.setattr("agentized.spec_approval_io.evaluate_task_spec", spy_eval)
    assert spec_approval_check(root, policy=policy)["ok"] is True
    assert non_owner_calls
    for root_arg, task_path, claim, heading in non_owner_calls:
        assert root_arg is root
        assert task_path is not None and task_path.name.endswith(".md")
        assert claim == "alice"
        assert heading == "## Approval"
    assert "alice" in eval_claims
    assert load_spec_approval(root)["enabled"] is False
    assert ensure_default_in_config({"version": 1})["spec_approval"]["enabled"] is False
    assert (
        ensure_default_in_config({"spec_approval": {"enabled": True}})["spec_approval"]["enabled"]
        is True
    )

    (ctx / "process-control.json").write_text(
        '{"version":1,"spec_approval":{"enabled":true},'
        '"merge_policy":{"human_participants":["bob@example.com"]}}\n',
        encoding="utf-8",
    )
    for leftover in ("T-260101-bbbb.md", "T-260101-dddd.md", "T-260101-eeee.md"):
        p = tasks / leftover
        if p.exists():
            p.unlink()
    _wt(tasks, "T-260101-ffff", st="blocked")
    monkeypatch.setattr(
        "agentized.spec_approval_io.approval_committed_by_non_owner", lambda *a, **k: False
    )
    monkeypatch.setattr("agentized.spec_approval_io.evaluate_task_spec", real_eval)
    blocked = spec_approval_check(root)
    assert blocked["ok"] is False and blocked["checked"] == 1

    (ctx / "process-control.json").write_text(
        '{"version":1,"spec_approval":{"enabled":true,"approval_heading":"## Signoff"},'
        '"merge_policy":{"human_participants":["bob@example.com"]}}\n',
        encoding="utf-8",
    )
    (tasks / "T-260101-ffff.md").unlink()
    _wt(tasks, "T-260101-hhhh", extra=SPEC_SO)
    seen: list[str] = []

    def spy_heading(r, p, c, approval_heading=None):
        seen.append(approval_heading)
        return False

    monkeypatch.setattr("agentized.spec_approval_io.approval_committed_by_non_owner", spy_heading)
    assert spec_approval_check(root)["ok"] is True
    assert seen == ["## Signoff"]
