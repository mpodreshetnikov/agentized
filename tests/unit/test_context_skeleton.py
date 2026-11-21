from __future__ import annotations

import subprocess
from pathlib import Path

from agentized.connect import connect, ensure_context_skeleton
from agentized.context_skeleton import MINIMAL_NAV_MD, ensure_context_skeleton as skeleton_fn
from agentized.leases import rebuild_lease_index
from agentized.tasks import rebuild_task_index


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_ensure_skeleton_index_seeds_match_generators(tmp_path: Path):
    result = skeleton_fn(tmp_path, "context")
    assert result["created"] is True
    assert result["path"] == "context"
    tasks_dir = tmp_path / "context" / "tasks"
    leases_dir = tmp_path / "context" / "leases"
    assert (tasks_dir / "INDEX.md").read_text(encoding="utf-8") == rebuild_task_index(tasks_dir)
    assert (leases_dir / "INDEX.md").read_text(encoding="utf-8") == rebuild_lease_index(leases_dir)
    assert "skeleton" not in (tasks_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "skeleton" not in (leases_dir / "INDEX.md").read_text(encoding="utf-8")
    assert (tmp_path / "context" / "NAV.md").read_text(encoding="utf-8") == (
        MINIMAL_NAV_MD.rstrip() + "\n"
    )
    assert set(result["files"]) >= {
        "context/NAV.md",
        "context/tasks/INDEX.md",
        "context/leases/INDEX.md",
    }
    assert ensure_context_skeleton is skeleton_fn


def test_ensure_skeleton_preserves_existing_index_files(tmp_path: Path):
    ctx = tmp_path / "ctx"
    (ctx / "tasks").mkdir(parents=True)
    (ctx / "leases").mkdir(parents=True)
    (ctx / "tasks" / "INDEX.md").write_text("# keep-tasks\n", encoding="utf-8")
    result = skeleton_fn(tmp_path, "ctx")
    assert result["created"] is True
    assert (ctx / "tasks" / "INDEX.md").read_text(encoding="utf-8") == "# keep-tasks\n"
    assert (ctx / "leases" / "INDEX.md").read_text(encoding="utf-8") == rebuild_lease_index(
        ctx / "leases"
    )
    assert "ctx/tasks/INDEX.md" not in result["files"]
    assert "ctx/leases/INDEX.md" in result["files"]


def test_ensure_skeleton_noop_when_nav_exists(tmp_path: Path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "NAV.md").write_text("# custom\n", encoding="utf-8")
    assert skeleton_fn(tmp_path, "context") == {
        "created": False,
        "path": "context",
        "files": [],
    }
    assert not (ctx / "tasks").exists()


def test_connect_then_index_leaves_tree_unchanged(tmp_path: Path, monkeypatch):
    """connect tmp → index rewrite → full tree byte-identical (AGE-68)."""
    import agentized_cli as cli

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "find_repo_root", lambda: tmp_path)

    connect(tmp_path, context_rel="context", harnesses=["cursor"], coverage_pct=80)
    before = _snapshot(tmp_path)

    class _Args:
        context = "context"
        print = False

    assert cli.cmd_index(_Args()) == 0
    assert _snapshot(tmp_path) == before
