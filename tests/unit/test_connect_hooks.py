"""AGE-52: connect_hooks wire + dry-run connect wrapper."""

from __future__ import annotations

import hashlib
from pathlib import Path

import agentized.connect as connect_mod
from agentized import connect_hooks


def _tree_hash(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "/.git/" not in str(path):
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_wire_rebinds_and_dry_run_writes_nothing(tmp_path: Path):
    connect_hooks.wire_safe_connect()
    assert connect_mod.connect is connect_hooks.connect
    assert connect_mod.install_cursor is connect_hooks.install_cursor
    assert connect_mod.install_claude is connect_hooks.install_claude
    assert connect_mod.install_codex is connect_hooks.install_codex
    (tmp_path / "context").mkdir()
    before = _tree_hash(tmp_path)
    result = connect_hooks.connect(
        tmp_path, context_rel="context", harnesses=["cursor"], dry_run=True
    )
    assert result["dry_run"] is True and result["ok"] is True
    assert result["harnesses"]["cursor"]["hooks_merge"]["dry_run"] is True
    assert result["state"]["agents_md_updated"] is False
    assert result["idempotent"] is True
    assert _tree_hash(tmp_path) == before


def test_connect_wrapper_sets_ok_flags(tmp_path: Path, monkeypatch):
    calls = {}

    def fake_orig(root, *, context_rel, harnesses, coverage_pct=None):
        calls["coverage_pct"] = coverage_pct
        return {
            "harnesses": {
                "cursor": {"hooks_merge": {"action": "merge", "path": "x", "wrote": True}},
            },
            "state": {},
        }

    monkeypatch.setattr(connect_hooks, "_ORIG_CONNECT", fake_orig)
    out = connect_hooks.connect(
        tmp_path, context_rel="context", harnesses=["cursor"], coverage_pct=80, dry_run=False
    )
    assert calls["coverage_pct"] == 80
    assert out["ok"] is True and out["dry_run"] is False and out["hooks_refused"] == []
