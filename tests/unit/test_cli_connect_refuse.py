"""AGE-23: CLI connect exit 1 on refuse / missing ok; dry-run flag."""

from __future__ import annotations
import argparse
from pathlib import Path
import agentized.connect as connect_mod
import agentized_cli


def _args(**kw):
    base = dict(context="context", harness=["claude"], coverage=None, json=False, dry_run=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_cmd_connect_exit_1_on_refuse_and_missing_ok(monkeypatch):
    monkeypatch.setattr(agentized_cli, "find_repo_root", lambda: Path("."))
    monkeypatch.setattr(
        connect_mod,
        "connect",
        lambda *a, **k: {
            "ok": False,
            "harnesses": {"claude": {"hooks_merge": {"action": "refuse"}}},
            "state": {"agents_md_updated": False, "claude_md_updated": False},
        },
    )
    assert agentized_cli.cmd_connect(_args()) == 1
    monkeypatch.setattr(
        connect_mod,
        "connect",
        lambda *a, **k: {"state": {"agents_md_updated": False, "claude_md_updated": False}},
    )
    assert agentized_cli.cmd_connect(_args()) == 1


def test_cmd_connect_passes_dry_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(agentized_cli, "find_repo_root", lambda: Path("."))

    def fake(*_a, **kwargs):
        seen.update(kwargs)
        return {
            "ok": True,
            "dry_run": True,
            "harnesses": {
                "cursor": {
                    "hooks_merge": {
                        "action": "merge",
                        "wrote": False,
                        "path": ".cursor/hooks.json",
                        "dry_run": True,
                    }
                }
            },
        }

    monkeypatch.setattr(connect_mod, "connect", fake)
    assert agentized_cli.cmd_connect(_args(harness=["cursor"], dry_run=True)) == 0
    assert seen.get("dry_run") is True
