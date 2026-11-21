"""AGE-68 A1: mutation oracles for ``ensure_context_skeleton`` (seed/skeleton).

Tests-only; no runtime change. Target: kill the 25 whole-file survivors on
``agentized.connect.x_ensure_context_skeleton``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentized.connect import (
    MINIMAL_LEASES_INDEX_MD,
    MINIMAL_NAV_MD,
    ensure_context_skeleton,
)
from agentized.task_schema import rebuild_task_index


def test_noop_result_keys_are_literal_path(tmp_path: Path):
    """Kill ``path`` → ``XXpathXX`` / ``PATH`` on early return."""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "NAV.md").write_text("# existing\n", encoding="utf-8")
    result = ensure_context_skeleton(tmp_path, "context")
    assert result == {"created": False, "path": "context", "files": []}


def test_created_result_keys_are_literal_path(tmp_path: Path):
    """Kill ``path`` → ``XXpathXX`` / ``PATH`` on success return."""
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    assert result["path"] == "context"
    assert set(result) == {"created", "path", "files"}


def test_nested_context_rel_requires_ctx_mkdir_parents(tmp_path: Path):
    """Kill ``ctx.mkdir(parents=True)`` → False/None/omit."""
    rel = "deep/nested/context"
    result = ensure_context_skeleton(tmp_path, rel)
    assert result["created"] is True
    assert result["path"] == rel
    assert (tmp_path / rel / "NAV.md").is_file()


def test_mkdir_kwargs_parents_and_exist_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill parents/exist_ok True → False/None/omit on ctx/tasks/leases mkdir."""
    seen: dict[str, dict] = {}
    real = Path.mkdir

    def wrapped(self: Path, *args, **kwargs):
        seen[self.name] = dict(kwargs)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", wrapped)
    ensure_context_skeleton(tmp_path, "context")
    expected = {"parents": True, "exist_ok": True}
    assert len(seen) == 3
    assert seen["context"] == expected
    assert seen["tasks"] == expected
    assert seen["leases"] == expected


def test_preexisting_tasks_dir_requires_exist_ok(tmp_path: Path):
    """Kill ``exist_ok=True`` → False on tasks mkdir when dir already exists."""
    ctx = tmp_path / "context"
    (ctx / "tasks").mkdir(parents=True)
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    assert (ctx / "tasks" / "INDEX.md").is_file()


def test_preexisting_leases_dir_requires_exist_ok(tmp_path: Path):
    """Kill ``exist_ok=True`` → False on leases mkdir when dir already exists."""
    ctx = tmp_path / "context"
    (ctx / "leases").mkdir(parents=True)
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    assert (ctx / "leases" / "INDEX.md").is_file()


def test_continue_not_break_when_one_index_exists(tmp_path: Path):
    """Kill ``continue`` → ``break``: remaining targets still written."""
    ctx = tmp_path / "context"
    (ctx / "tasks").mkdir(parents=True)
    (ctx / "leases").mkdir(parents=True)
    # NAV missing → create path; pre-seed tasks INDEX so loop hits continue
    (ctx / "tasks" / "INDEX.md").write_text("# keep-tasks\n", encoding="utf-8")
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    assert (ctx / "NAV.md").is_file()
    assert (ctx / "leases" / "INDEX.md").is_file()
    assert (ctx / "tasks" / "INDEX.md").read_text(encoding="utf-8") == "# keep-tasks\n"
    assert "context/NAV.md" in result["files"]
    assert "context/leases/INDEX.md" in result["files"]
    assert "context/tasks/INDEX.md" not in result["files"]


def test_write_text_encoding_is_utf8_literal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill encoding=None / omitted / case variants (UTF-8 ignored by mutmut lexeme)."""
    seen: list[str | None] = []
    real = Path.write_text

    def wrapped(self: Path, data: str, encoding: str | None = None, **kwargs):
        seen.append(encoding)
        return real(self, data, encoding=encoding, **kwargs)

    monkeypatch.setattr(Path, "write_text", wrapped)
    ensure_context_skeleton(tmp_path, "context")
    assert seen
    assert all(enc == "utf-8" for enc in seen)


def test_seed_bodies_use_rstrip_not_lstrip_or_junk(tmp_path: Path):
    """Kill ``rstrip`` → ``lstrip`` and ``\\n`` → ``XX\\nXX``."""
    ensure_context_skeleton(tmp_path, "context")
    nav = (tmp_path / "context" / "NAV.md").read_text(encoding="utf-8")
    tasks_dir = tmp_path / "context" / "tasks"
    tasks = (tasks_dir / "INDEX.md").read_text(encoding="utf-8")
    leases = (tmp_path / "context" / "leases" / "INDEX.md").read_text(encoding="utf-8")
    assert nav == MINIMAL_NAV_MD.rstrip() + "\n"
    assert tasks == rebuild_task_index(tasks_dir).rstrip() + "\n"
    assert leases == MINIMAL_LEASES_INDEX_MD.rstrip() + "\n"


def test_prepare_bridges_before_connect_noops_local_skeleton(tmp_path: Path):
    """Bridges first → NAV exists → connect skeleton no-op (no local registry dirs)."""
    import json
    import subprocess

    from agentized.connect import connect
    from agentized.context_layout import prepare_connect_layout

    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    subprocess.run(["git", "init"], cwd=ext, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=code, check=True, capture_output=True)
    ctx = code / "context"
    ctx.mkdir()
    (ctx / "context.json").write_text(
        json.dumps({"placement": "external", "external": {"path": str(ext), "remote": "r"}}) + "\n",
        encoding="utf-8",
    )
    layout = prepare_connect_layout(code, bridges=True)
    assert layout.is_external
    assert (ctx / "NAV.md").is_symlink()
    result = connect(code, context_rel="context", harnesses=["cursor"])
    assert result["skeleton"]["created"] is False
    assert (ctx / "tasks").is_symlink()
    assert (ctx / "NAV.md").is_symlink()
    assert (ctx / "quality.json").exists()


def test_skeleton_tasks_index_passes_tip_hygiene(tmp_path: Path, monkeypatch):
    """connect skeleton INDEX == rebuild → tasks-validate tip hygiene INDEX ok."""
    import agentized.status_gates as sg
    from agentized.status_gates import GateResult, run_tasks_validate

    ensure_context_skeleton(tmp_path, "context")
    tasks = tmp_path / "context" / "tasks"
    monkeypatch.setattr(sg, "resolve_validate_base_ref", lambda *a, **k: "BASE")
    monkeypatch.setattr(sg, "previous_task_texts_from_git", lambda *a, **k: {})
    monkeypatch.setattr(sg, "validate_tasks_dir", lambda *a, **k: GateResult(True))
    # No PR (push/local): INDEX freshness only.
    monkeypatch.delenv("GITHUB_REF", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    for key in ("AGENTIZED_PR", "TIP_HYGIENE_PR", "GITHUB_PR_NUMBER"):
        monkeypatch.delenv(key, raising=False)
    ref, result = run_tasks_validate(tasks, repo_root=tmp_path)
    assert ref == "BASE" and result == GateResult(True)
