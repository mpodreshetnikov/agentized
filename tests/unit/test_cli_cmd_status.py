"""CLI cmd_status Progress dedupe (outside mutmut module selection — needs agentized_cli)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

pytest.importorskip("agentized_cli")


def test_cmd_status_done_twice_one_progress_line_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """agentized status <id> done ×2 → exactly one ``статус → done`` + INDEX rebuilt."""
    from agentized_cli import cmd_status

    repo = tmp_path / "repo"
    tasks = repo / "context" / "tasks"
    tasks.mkdir(parents=True)
    task_id = "T-261121-scratch"
    task_path = tasks / f"{task_id}.md"
    task_path.write_text(
        f"# {task_id} — scratch\n\n"
        "статус: in-progress\n"
        "теги:\n"
        "родитель: _(пусто)_\n"
        "claim: test\n\n"
        "## Progress\n\n_(append-only)_\n"
        "- 2026-11-21 09:00 UTC: claim by test\n\n"
        "## Decision Log\n\n_(append-only)_\n",
        encoding="utf-8",
    )
    (tasks / "INDEX.md").write_text("# stale INDEX\n", encoding="utf-8")

    monkeypatch.setattr("agentized_cli.find_repo_root", lambda: repo)
    args = argparse.Namespace(task_id=task_id, status="done", context="context")

    assert cmd_status(args) == 0
    assert cmd_status(args) == 0

    text = task_path.read_text(encoding="utf-8")
    assert text.count("статус → done") == 1
    assert "статус: done" in text

    index = (tasks / "INDEX.md").read_text(encoding="utf-8")
    assert index != "# stale INDEX\n"
    assert "# Задачи — живой индекс" in index
    assert "Генерируемый" in index
    # done is outside CLAIM_STATUSES buckets; rebuild still rewrites INDEX
    assert "# stale" not in index
