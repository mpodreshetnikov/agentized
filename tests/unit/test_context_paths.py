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
    with pytest.raises(ValueError) as eo:
        require_safe_rel("/x", field="metrics.output")
    assert eo.value.args == ("metrics.output must be a safe relative path",)
    assert resolve_context_dir(tmp_path, "context") == (tmp_path / "context").resolve()
    assert resolve_context_dir(tmp_path).name == "context"
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
