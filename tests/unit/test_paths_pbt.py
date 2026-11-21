"""Property-based pilot for pure paths helpers (Hypothesis)."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from agentized.paths import (
    DEFAULT_CONTEXT,
    context_dir,
    path_under,
    require_safe_rel,
    resolve_context_dir,
    state_path,
    under_context,
)


@given(
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
        min_size=1,
        max_size=24,
    )
)
def test_context_dir_joins_rel(name: str):
    root = Path("/tmp/agentized-pbt-root")
    out = context_dir(root, name)
    assert out == (root / name).resolve()
    assert out.name == name


def test_state_path_stable(tmp_path: Path):
    p = state_path(tmp_path)
    assert p.name == "connect.json"
    assert p.parent.name == ".agentized"
    assert DEFAULT_CONTEXT == "context"


def test_safe_rel_and_context_confinement(tmp_path: Path):
    assert require_safe_rel("context", field="context") == "context"
    for bad in ("", "/abs", "a/../b", None):
        with pytest.raises(ValueError) as ex:
            require_safe_rel(bad, field="context")
        assert ex.value.args == ("context must be a safe relative path",)
    ctx = resolve_context_dir(tmp_path, "context")
    assert ctx == (tmp_path / "context").resolve()
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "context").symlink_to(outside)
    with pytest.raises(ValueError) as er:
        resolve_context_dir(repo, "context")
    assert er.value.args == ("context path escapes repository root",)
    (tmp_path / "context" / "board").mkdir(parents=True)
    assert under_context(tmp_path, "context", "board", "m.json").name == "m.json"
    leak = tmp_path / "leak"
    (leak / "context").mkdir(parents=True)
    out = leak / "out"
    out.mkdir()
    (leak / "context" / "board").symlink_to(out)
    with pytest.raises(ValueError) as es:
        path_under(leak / "context", "board", "m.json")
    assert es.value.args == ("path escapes context directory",)
    with pytest.raises(ValueError):
        under_context(leak, "context", "board", "m.json")
    assert list(out.iterdir()) == []
