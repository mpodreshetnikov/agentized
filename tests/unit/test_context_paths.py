"""Confinement helpers for context paths (AGE-30)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentized.context_paths import path_under, require_safe_rel, resolve_context_dir, under_context


def test_safe_rel_and_context_confinement(tmp_path: Path):
    assert require_safe_rel("context", field="context") == "context"
    assert require_safe_rel("a/b", field="metrics.output") == "a/b"
    for bad in ("", "/abs", "a/../b", None):
        with pytest.raises(ValueError) as ex:
            require_safe_rel(bad, field="context")
        assert ex.value.args == ("context must be a safe relative path",)
    # resolve_context_dir passes field="context" into require_safe_rel (exact).
    with pytest.raises(ValueError) as bad_rel:
        resolve_context_dir(tmp_path, "../escape")
    assert bad_rel.value.args == ("context must be a safe relative path",)
    assert resolve_context_dir(tmp_path, "context") == (tmp_path / "context").resolve()
    repo, outside = tmp_path / "repo", tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (repo / "context").symlink_to(outside)
    with pytest.raises(ValueError) as er:
        resolve_context_dir(repo, "context")
    assert er.value.args == ("context path escapes repository root",)
    (tmp_path / "context" / "board").mkdir(parents=True)
    got = under_context(tmp_path, "context", "board", "m.json")
    assert got == (tmp_path / "context" / "board" / "m.json").resolve()
    # Custom context_rel must be forwarded (not defaulted away).
    (tmp_path / "pc" / "board").mkdir(parents=True)
    assert (
        under_context(tmp_path, "pc", "board", "m.json")
        == (tmp_path / "pc" / "board" / "m.json").resolve()
    )
    leak = tmp_path / "leak"
    out = leak / "out"
    (leak / "context").mkdir(parents=True)
    out.mkdir()
    (leak / "context" / "board").symlink_to(out)
    with pytest.raises(ValueError) as es:
        path_under(leak / "context", "board", "m.json")
    assert es.value.args == ("path escapes context directory",)
    with pytest.raises(ValueError) as eu:
        under_context(leak, "context", "board", "m.json")
    assert eu.value.args == ("path escapes context directory",)
    assert list(out.iterdir()) == []


def test_path_under_allows_tasks_bridge_escape(tmp_path: Path):
    """External tasks symlink may resolve outside code context (write_metrics/index)."""
    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    (ext / "tasks").mkdir(parents=True)
    (ext / "tasks" / "INDEX.md").write_text("# t\n", encoding="utf-8")
    ctx = code / "context"
    ctx.mkdir()
    (ctx / "tasks").symlink_to(ext / "tasks")
    got = under_context(code, "context", "tasks", "INDEX.md")
    assert got == (ext / "tasks" / "INDEX.md").resolve()
    # Escape past the bridge root still refused.
    (ext / "secret.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError) as esc:
        path_under(ctx, "tasks", "..", "secret.txt")
    assert esc.value.args == ("path escapes context directory",)
