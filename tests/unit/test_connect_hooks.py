"""AGE-52: connect_hooks wire + dry-run + install wrap."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import agentized.connect as connect_mod
from agentized import connect_hooks
from agentized.connect_hooks import install_claude, install_codex, install_cursor


def _tree_hash(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "/.git/" not in str(path):
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _seed(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    for rel in (
        "context/skills",
        "context/hooks/scripts",
        "packages/shared/hooks/scripts",
        "packages/shared/skills/navigate",
        "templates/quality",
    ):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    (tmp_path / "context/NAV.md").write_text("# NAV\n", encoding="utf-8")
    (tmp_path / "packages/shared/skills/navigate/SKILL.md").write_text(
        "---\nname: navigate\n---\n", encoding="utf-8"
    )
    for name in ("session_start.py", "process_guard.py", "lease_warn.py", "ensure_agent_hooks.py"):
        for base in ("context/hooks/scripts", "packages/shared/hooks/scripts"):
            (tmp_path / base / name).write_text("print(1)\n", encoding="utf-8")
    from agentized.hooks_install import _desired_bundle_path

    (tmp_path / "packages/shared/hooks/harness_desired.json").write_bytes(
        _desired_bundle_path().read_bytes()
    )
    for pkg in ("agentized-cursor", "agentized-claude", "agentized-codex"):
        (tmp_path / "packages" / pkg).mkdir(parents=True, exist_ok=True)


def test_wire_rebinds_and_dry_run_exact(tmp_path: Path):
    connect_hooks.wire_safe_connect()
    assert connect_mod.connect is connect_hooks.connect
    assert connect_mod.install_cursor is connect_hooks.install_cursor
    assert connect_mod.install_claude is connect_hooks.install_claude
    assert connect_mod.install_codex is connect_hooks.install_codex
    (tmp_path / "context").mkdir()
    before = _tree_hash(tmp_path)
    result = connect_hooks.connect(tmp_path, context_rel="context", dry_run=True)
    assert set(result) == {
        "skeleton",
        "harnesses",
        "dry_run",
        "skipped_user",
        "state",
        "idempotent",
        "hooks_refused",
        "ok",
    }
    assert result["skeleton"] == {"created": False, "path": "context", "files": []}
    assert result["dry_run"] is True and result["ok"] is True and result["idempotent"] is True
    assert result["skipped_user"] == [] and result["hooks_refused"] == []
    assert result["state"] == {
        "version": connect_hooks.__version__,
        "context": "context",
        "harnesses": ["cursor", "claude", "codex"],
        "agents_md_updated": False,
        "claude_md_updated": False,
        "coverage_pct": None,
    }
    assert set(result["harnesses"]) == {"cursor", "claude", "codex"}
    assert result["harnesses"]["cursor"]["hooks_merge"]["dry_run"] is True
    assert result["harnesses"]["cursor"]["hooks_merge"]["wrote"] is False
    assert result["harnesses"]["claude"]["hooks_merge"]["dry_run"] is True
    assert result["harnesses"]["codex"]["hooks_merge"]["dry_run"] is True
    assert result["harnesses"]["codex"]["marketplace_merge"]["dry_run"] is True
    assert _tree_hash(tmp_path) == before


def test_connect_wrapper_sets_ok_flags(tmp_path: Path, monkeypatch):
    calls = {}

    def fake_orig(root, *, context_rel, harnesses, coverage_pct=None):
        calls["coverage_pct"] = coverage_pct
        calls["harnesses"] = harnesses
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
    assert calls == {"coverage_pct": 80, "harnesses": ["cursor"]}
    assert out["ok"] is True and out["dry_run"] is False and out["hooks_refused"] == []


def test_install_preserves_foreign_after_orig(tmp_path: Path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    cursor = tmp_path / ".cursor/hooks.json"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(
        json.dumps(
            {"version": 1, "hooks": {"sessionStart": [{"command": "echo foreign"}]}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    man: dict = {"files": {}}
    out = install_cursor(tmp_path, "context", manifest=man, force=False)
    assert out["hooks_merge"]["wrote"] is True
    assert out["hooks_merge"]["harness"] == "cursor"
    body = json.loads(cursor.read_text(encoding="utf-8"))
    assert any(e.get("command") == "echo foreign" for e in body["hooks"]["sessionStart"])
    assert ".cursor/hooks/session_start.py" in [
        e.get("command") for e in body["hooks"]["sessionStart"]
    ]
    snap = cursor.read_bytes()
    dry = install_cursor(tmp_path, "context", manifest=man, dry_run=True)
    assert dry["hooks_merge"]["dry_run"] is True and dry["hooks_merge"]["wrote"] is False
    assert cursor.read_bytes() == snap
    assert dry["skills_copied"] == [] and dry["plugin_path"] is None
    assert dry["local_plugin_hint"] == "cursor-agent --plugin-dir packages/agentized-cursor"
    cl = install_claude(tmp_path, "context", manifest=man)
    assert cl["hooks_merge"]["harness"] == "claude" and "settings" in cl
    assert cl["plugin_hint"] == "claude --plugin-dir packages/agentized-claude"
    cx = install_codex(tmp_path, "context", manifest=man)
    assert cx["marketplace_merge"]["kind"] == "marketplace"
    assert "codex plugin" in cx["plugin_hint"] and "gap" in cx
    m_snap = (tmp_path / ".agents/plugins/marketplace.json").read_bytes()
    cx_dry = install_codex(tmp_path, "context", manifest=man, dry_run=True)
    assert cx_dry["marketplace_merge"]["dry_run"] is True
    assert (tmp_path / ".agents/plugins/marketplace.json").read_bytes() == m_snap
