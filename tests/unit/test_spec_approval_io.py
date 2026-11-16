"""IO tests for AGE-28 spec_approval_check (outside mutation gate)."""
from __future__ import annotations

from pathlib import Path

from agentized.spec_approval_defaults import default_spec_approval
from agentized.spec_approval_io import load_spec_approval, spec_approval_check
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


def test_spec_approval_check_disabled_and_enforced(tmp_path: Path):
    root = tmp_path
    ctx = root / "context"
    tasks = ctx / "tasks"
    tasks.mkdir(parents=True)
    (ctx / "process-control.json").write_text(
        '{"version":1,"spec_approval":{"enabled":false}}\n',
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
    assert disabled["ok"] is True
    assert disabled["mode"] == "disabled"
    assert disabled["checked"] == 0

    policy = default_spec_approval()
    policy["enabled"] = True
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
        extra="## Spec\n\nDo it.\n\n## Approval\n\napproved-by: bob\n",
    )
    # open / non-complex ignored
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
    # still fails on aaaa
    still = spec_approval_check(root, policy=policy)
    assert still["ok"] is False
    assert still["checked"] == 2

    (tasks / "T-260101-aaaa.md").unlink()
    ok = spec_approval_check(root, policy=policy)
    assert ok["ok"] is True
    assert ok["mode"] == "ok"
    assert ok["checked"] == 1
    assert ok["failures"] == []
    assert "checked 1" in ok["message"]

    loaded = load_spec_approval(root)
    assert loaded["enabled"] is False
