from __future__ import annotations

import subprocess
from pathlib import Path

from agentized.connect import connect, ensure_context_skeleton
from agentized.leases import rebuild_lease_index
from agentized.tasks import rebuild_task_index


def test_ensure_skeleton_creates_minimal_layout(tmp_path: Path):
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    assert (tmp_path / "context" / "NAV.md").is_file()
    assert (tmp_path / "context" / "tasks" / "INDEX.md").is_file()
    assert (tmp_path / "context" / "leases" / "INDEX.md").is_file()
    assert "context/NAV.md" in result["files"]
    assert (tmp_path / "context" / "tasks" / "INDEX.md").read_text(
        encoding="utf-8"
    ) == rebuild_task_index(tmp_path / "context" / "tasks")
    assert (tmp_path / "context" / "leases" / "INDEX.md").read_text(
        encoding="utf-8"
    ) == rebuild_lease_index(tmp_path / "context" / "leases")


def test_ensure_skeleton_does_not_overwrite_existing_nav(tmp_path: Path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    nav = ctx / "NAV.md"
    nav.write_text("# custom user NAV\nkeep-me\n", encoding="utf-8")
    (ctx / "tasks").mkdir()
    (ctx / "tasks" / "INDEX.md").write_text("# custom tasks\n", encoding="utf-8")

    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is False
    assert result["files"] == []
    assert "keep-me" in nav.read_text(encoding="utf-8")
    assert "# custom tasks" in (ctx / "tasks" / "INDEX.md").read_text(encoding="utf-8")
    # leases not invented when NAV already marks Context as present
    assert not (ctx / "leases" / "INDEX.md").exists()


def test_connect_clean_git_init_creates_skeleton(tmp_path: Path, monkeypatch):
    """Regression: clean git init with no context/ — connect succeeds + skeleton."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)

    assert not (tmp_path / "context").exists()
    result = connect(tmp_path, context_rel="context", harnesses=["cursor"], coverage_pct=80)

    assert result["skeleton"]["created"] is True
    assert (tmp_path / "context" / "NAV.md").is_file()
    assert (tmp_path / "context" / "tasks" / "INDEX.md").is_file()
    assert (tmp_path / "context" / "leases" / "INDEX.md").is_file()
    assert "AGENTIZED:BEGIN" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert (tmp_path / "context" / "skills" / "navigate" / "SKILL.md").is_file()
    assert (tmp_path / ".cursor" / "hooks.json").is_file()

    # second connect must not overwrite user NAV
    nav = tmp_path / "context" / "NAV.md"
    nav.write_text("# edited NAV\nuser-edit\n", encoding="utf-8")
    again = connect(tmp_path, context_rel="context", harnesses=["cursor"])
    assert again["skeleton"]["created"] is False
    assert "user-edit" in nav.read_text(encoding="utf-8")
