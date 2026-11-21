"""Mutation oracles for context_skeleton (AGE-68)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentized.context_skeleton import ensure_context_skeleton


def test_nested_context_rel_requires_parents_true(tmp_path: Path):
    """Kill parents=True → False/None/omit on ctx.mkdir."""
    rel = "deep/nested/context"
    result = ensure_context_skeleton(tmp_path, rel)
    assert result["created"] is True
    assert (tmp_path / rel / "NAV.md").is_file()
    assert result["path"] == rel


def test_rebuild_uses_real_tasks_and_leases_dirs(tmp_path: Path):
    """Kill rebuild_task_index(ctx/'XXtasksXX') and leases path mangling."""
    ctx = tmp_path / "context"
    tasks = ctx / "tasks"
    leases = ctx / "leases"
    tasks.mkdir(parents=True)
    leases.mkdir(parents=True)
    (tasks / "T-261121-seed.md").write_text(
        "# T-261121-seed — Seed task\n\nстатус: open\nтеги:\nродитель:\nclaim:\n",
        encoding="utf-8",
    )
    (leases / "T-261121-seed.md").write_text(
        "# Lease T-261121-seed\n\n"
        "task: T-261121-seed\n"
        "owner: oracle\n"
        "expires: 2099-01-01T00:00:00Z\n"
        "status: active\n"
        "paths:\n- runtime/agentized/context_skeleton.py\n",
        encoding="utf-8",
    )
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    tasks_idx = (tasks / "INDEX.md").read_text(encoding="utf-8")
    leases_idx = (leases / "INDEX.md").read_text(encoding="utf-8")
    assert "T-261121-seed" in tasks_idx
    assert "Seed task" in tasks_idx
    assert "T-261121-seed" in leases_idx
    assert "runtime/agentized/context_skeleton.py" in leases_idx


def test_write_text_encoding_is_utf8_literal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill encoding=None / omitted / UTF-8 case variants."""
    seen: list[str | None] = []
    real = Path.write_text

    def wrapped(self: Path, data: str, encoding: str | None = None, **kwargs):
        seen.append(encoding)
        return real(self, data, encoding=encoding, **kwargs)

    monkeypatch.setattr(Path, "write_text", wrapped)
    ensure_context_skeleton(tmp_path, "context")
    assert seen
    assert all(enc == "utf-8" for enc in seen)
