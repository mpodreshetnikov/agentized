"""Property-based pilot for pure paths helpers (Hypothesis)."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, strategies as st

from agentized.paths import DEFAULT_CONTEXT, context_dir, state_path


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
