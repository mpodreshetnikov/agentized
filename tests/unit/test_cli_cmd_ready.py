"""CLI cmd_ready tip hygiene (AGE-76) — outside mutmut module selection."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

pytest.importorskip("agentized_cli")


def _task_body(task_id: str, *, status: str, claim: str) -> str:
    return (
        f"# {task_id} — ready demo\n\n"
        f"статус: {status}\n"
        "теги: age-76\n"
        "родитель: _(пусто)_\n"
        f"claim: {claim}\n\n"
        "Ценность: ready CLI flips tip hygiene\n\n"
        "## Цель\n\nDemo.\n\n"
        "## Progress\n\n_(append-only)_\n"
        f"- 2026-11-21 10:00 UTC: claim by {claim}\n\n"
        "## Decision Log\n\n_(append-only)_\n"
    )


def test_cmd_ready_explicit_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from agentized_cli import cmd_ready

    repo = tmp_path / "repo"
    tasks = repo / "context" / "tasks"
    tasks.mkdir(parents=True)
    task_id = "T-261121-rdy1"
    path = tasks / f"{task_id}.md"
    path.write_text(_task_body(task_id, status="in-progress", claim="worker"), encoding="utf-8")
    (tasks / "INDEX.md").write_text("# stale\n", encoding="utf-8")
    monkeypatch.setattr("agentized_cli.find_repo_root", lambda: repo)

    args = argparse.Namespace(
        task_id=task_id,
        owner=None,
        pr="https://github.com/o/r/pull/76",
        review_note="tip ready",
        context="context",
    )
    assert cmd_ready(args) == 0
    text = path.read_text(encoding="utf-8")
    assert "статус: self-review" in text
    assert "claim: _(пусто)_" in text
    assert "pr: https://github.com/o/r/pull/76" in text
    assert "review_note: tip ready" in text
    assert "статус → self-review" in text
    index = (tasks / "INDEX.md").read_text(encoding="utf-8")
    assert "# Задачи — живой индекс" in index
    assert task_id not in index


def test_cmd_ready_auto_owner_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from agentized_cli import cmd_ready

    repo = tmp_path / "repo"
    tasks = repo / "context" / "tasks"
    tasks.mkdir(parents=True)
    a = "T-261121-rdya"
    b = "T-261121-rdyb"
    (tasks / f"{a}.md").write_text(
        _task_body(a, status="in-progress", claim="alice"), encoding="utf-8"
    )
    (tasks / f"{b}.md").write_text(
        _task_body(b, status="in-progress", claim="bob"), encoding="utf-8"
    )
    monkeypatch.setattr("agentized_cli.find_repo_root", lambda: repo)

    assert (
        cmd_ready(
            argparse.Namespace(
                task_id=None, owner=None, pr=None, review_note=None, context="context"
            )
        )
        == 1
    )
    assert (
        cmd_ready(
            argparse.Namespace(
                task_id=None,
                owner="alice",
                pr="#1",
                review_note="n",
                context="context",
            )
        )
        == 0
    )
    text = (tasks / f"{a}.md").read_text(encoding="utf-8")
    assert "статус: self-review" in text and "claim: _(пусто)_" in text
    assert (
        cmd_ready(
            argparse.Namespace(
                task_id="T-261121-nope",
                owner=None,
                pr=None,
                review_note=None,
                context="context",
            )
        )
        == 1
    )
