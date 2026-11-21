"""AGE-52: connect_hooks wire + dry-run + install wrap."""

from __future__ import annotations

import shutil
from pathlib import Path

import agentized.connect as connect_mod
from agentized import connect_hooks
from agentized.connect_hooks import install_claude, install_codex, install_cursor


def test_wire_rebinds_and_dry_run_exact(tmp_path: Path):
    connect_hooks.wire_safe_connect()
    assert connect_mod.connect is connect_hooks.connect
    assert connect_mod.install_cursor is connect_hooks.install_cursor
    assert connect_mod.install_claude is connect_hooks.install_claude
    assert connect_mod.install_codex is connect_hooks.install_codex
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = connect_hooks.connect(tmp_path, context_rel="context", dry_run=True)
    assert set(result) == {"harnesses", "dry_run", "hooks_refused", "ok"}
    assert result["dry_run"] is True and result["ok"] is True and result["hooks_refused"] == []
    assert set(result["harnesses"]) == {"cursor", "claude", "codex"}
    assert result["harnesses"]["cursor"]["hooks_merge"]["dry_run"] is True
    assert result["harnesses"]["cursor"]["hooks_merge"]["wrote"] is False
    assert result["harnesses"]["claude"]["hooks_merge"]["dry_run"] is True
    assert result["harnesses"]["codex"]["hooks_merge"]["dry_run"] is True
    assert result["harnesses"]["codex"]["marketplace_merge"]["dry_run"] is True
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_connect_wrapper_sets_ok_flags(tmp_path: Path, monkeypatch):
    calls: dict = {}

    def fake_orig(root, *, context_rel, harnesses, coverage_pct=None):
        calls["args"] = (context_rel, harnesses, coverage_pct)
        return {
            "harnesses": {
                "cursor": {
                    "hooks_merge": {"action": "refuse", "path": "x", "reason": "broken"},
                },
            },
        }

    monkeypatch.setattr(connect_hooks, "_ORIG_CONNECT", fake_orig)
    out = connect_hooks.connect(
        tmp_path, context_rel="context", harnesses=["cursor"], coverage_pct=80
    )
    assert calls["args"] == ("context", ["cursor"], 80)
    assert out["ok"] is False and out["dry_run"] is False
    assert out["hooks_refused"] == [
        {"harness": "cursor", "path": "x", "reason": "broken", "error": None}
    ]

    def bad_harnesses(root, *, context_rel, harnesses, coverage_pct=None):
        return {"harnesses": "not-a-dict"}

    monkeypatch.setattr(connect_hooks, "_ORIG_CONNECT", bad_harnesses)
    out_bad = connect_hooks.connect(tmp_path, context_rel="context", harnesses=["cursor"])
    assert out_bad["ok"] is True and out_bad["hooks_refused"] == []


def test_install_wrap_restore_and_kwargs(tmp_path: Path, monkeypatch):
    cursor = tmp_path / ".cursor/hooks.json"
    cursor.parent.mkdir(parents=True)
    foreign = b'{"version":1,"hooks":{"sessionStart":[{"command":"echo f"}]}}\n'
    cursor.write_bytes(foreign)
    seen: dict = {}

    def wipe_cursor(root, context_rel, *, force, manifest):
        seen["cursor"] = (force, manifest)
        cursor.write_bytes(b'{"version":1,"hooks":{}}\n')
        return {"skills_copied": ["c"]}

    def wipe_claude(root, context_rel, *, force, manifest):
        seen["claude"] = (force, manifest)
        return {"plugin_hint": "claude-hint"}

    def wipe_codex(root, context_rel, *, force, manifest):
        seen["codex"] = (force, manifest)
        if (root / ".agents").exists():
            shutil.rmtree(root / ".agents")
        return {"plugin_hint": "codex-hint", "gap": "g"}

    monkeypatch.setattr(connect_hooks, "_ORIG_CURSOR", wipe_cursor)
    monkeypatch.setattr(connect_hooks, "_ORIG_CLAUDE", wipe_claude)
    monkeypatch.setattr(connect_hooks, "_ORIG_CODEX", wipe_codex)
    merge_calls: list = []

    def fake_merge(root, harness, *, context_rel, dry_run=False):
        merge_calls.append((root, harness, context_rel, dry_run))
        return {
            "action": "merge",
            "wrote": not dry_run,
            "harness": harness,
            "dry_run": dry_run,
            "context_rel": context_rel,
        }

    market_calls: list = []

    def fake_market(root, *, dry_run=False):
        market_calls.append((root, dry_run))
        return {"kind": "marketplace", "wrote": not dry_run, "dry_run": dry_run}

    monkeypatch.setattr(connect_hooks, "apply_harness_hook_merge", fake_merge)
    monkeypatch.setattr(connect_hooks, "apply_marketplace_merge", fake_market)

    man = {"files": {}}
    out = install_cursor(tmp_path, "context", manifest=man)
    assert seen["cursor"] == (False, man)
    assert cursor.read_bytes() == foreign
    assert out["hooks_merge"]["harness"] == "cursor"
    assert out["hooks_merge"]["dry_run"] is False
    assert merge_calls[-1] == (tmp_path, "cursor", "context", False)

    dry = install_cursor(tmp_path, "ctx-dry", dry_run=True)
    assert list(dry) == ["hooks_merge"]
    assert dry["hooks_merge"]["dry_run"] is True
    assert merge_calls[-1] == (tmp_path, "cursor", "ctx-dry", True)
    assert cursor.read_bytes() == foreign

    cl = install_claude(tmp_path, "context", manifest=man)
    assert seen["claude"] == (False, man)
    assert cl["plugin_hint"] == "claude-hint"
    cl_dry = install_claude(tmp_path, "claude-ctx", dry_run=True)
    assert cl_dry["hooks_merge"]["dry_run"] is True
    assert merge_calls[-1] == (tmp_path, "claude", "claude-ctx", True)

    # codex without marketplace file (kills is_file() or True)
    cx0 = install_codex(tmp_path, "context", manifest=man)
    assert seen["codex"] == (False, man)
    assert "hooks_merge" in cx0
    assert cx0["hooks_merge"]["harness"] == "codex"
    assert cx0["marketplace_merge"]["dry_run"] is False

    market = tmp_path / ".agents/plugins/marketplace.json"
    market.parent.mkdir(parents=True)
    market.write_bytes(b'{"name":"keep","plugins":[]}\n')
    snap = market.read_bytes()
    cx = install_codex(tmp_path, "context", manifest=man)
    assert market.read_bytes() == snap
    assert cx["marketplace_merge"]["kind"] == "marketplace"
    market_calls.clear()
    cx_dry = install_codex(tmp_path, "codex-ctx", dry_run=True)
    assert "hooks_merge" in cx_dry
    assert cx_dry["hooks_merge"]["dry_run"] is True
    assert cx_dry["marketplace_merge"]["dry_run"] is True
    assert market_calls == [(tmp_path, True)]
    assert merge_calls[-1] == (tmp_path, "codex", "codex-ctx", True)
    assert market.read_bytes() == snap
