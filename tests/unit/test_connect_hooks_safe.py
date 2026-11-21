"""AGE-52: connect e2e — tree snapshot, refuse, dry-run writes nothing, abs-path."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import agentized.connect as connect_mod

QUALITY_MARKER = connect_mod.QUALITY_MARKER


def _skeleton(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    ctx = root / "context"
    for rel in (
        "context/tasks",
        "context/leases",
        "context/hooks/scripts",
        "context/skills",
        "packages/shared/skills/navigate",
        "packages/shared/hooks/scripts",
        "templates/quality",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (root / "packages/shared/skills/navigate/SKILL.md").write_text(
        "---\nname: navigate\n---\n", encoding="utf-8"
    )
    for name in (
        "session_start.py",
        "process_guard.py",
        "lease_warn.py",
        "ensure_agent_hooks.py",
    ):
        (root / "packages/shared/hooks/scripts" / name).write_text(
            "print('ok')\n", encoding="utf-8"
        )
    from agentized.hooks_install import _desired_bundle_path

    desired = _desired_bundle_path()
    (root / "packages/shared/hooks/harness_desired.json").write_bytes(desired.read_bytes())
    (root / "templates/quality/pre-push").write_text(
        f"#!/bin/sh\n# {QUALITY_MARKER}\necho hi\n", encoding="utf-8"
    )
    (root / "templates/quality/ci.yml").write_text(
        f"# {QUALITY_MARKER}\nname: CI\n", encoding="utf-8"
    )
    for pkg in ("agentized-cursor", "agentized-claude", "agentized-codex"):
        (root / "packages" / pkg).mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")


def _tree_hash(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "/.git/" in str(path) or path.name == ".git":
            continue
        rel = str(path.relative_to(root))
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_connect_tree_snapshot_foreign_byte_equal(tmp_path: Path, monkeypatch):
    _skeleton(tmp_path)
    monkeypatch.chdir(tmp_path)
    foreign = {
        tmp_path / ".cursor/hooks.json": {
            "version": 1,
            "hooks": {
                "sessionStart": [{"command": "echo foreign-cursor"}],
                "customEvent": [{"command": "foreign/cursor.py"}],
            },
        },
        tmp_path / ".claude/settings.json": {
            "permissions": {"allow": ["Bash"]},
            "hooks": {
                "Notification": [
                    {"matcher": "*", "hooks": [{"type": "command", "command": "echo n"}]}
                ]
            },
        },
        tmp_path / ".codex/hooks.json": {
            "description": "keep-codex",
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [{"type": "command", "command": "echo foreign-codex"}],
                    }
                ]
            },
        },
        tmp_path / ".agents/plugins/marketplace.json": {
            "name": "keep-market",
            "plugins": [{"name": "foreign-plug"}],
        },
        tmp_path / ".codex/config.toml": 'model = "foreign"\n',
        tmp_path / ".husky/pre-commit": "#!/bin/sh\necho husky-foreign\n",
    }
    for path, body in foreign.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, dict):
            path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        else:
            path.write_text(body, encoding="utf-8")
    before = _tree_hash(tmp_path)
    result = connect_mod.connect(
        tmp_path, context_rel="context", harnesses=["cursor", "claude", "codex"]
    )
    assert result.get("ok") is True
    assert "hooks_refused" in result and result["hooks_refused"] == []
    after = _tree_hash(tmp_path)
    changed = {k for k in after.keys() | before.keys() if before.get(k) != after.get(k)}
    expected_prefixes = (
        ".cursor/",
        ".claude/",
        ".codex/",
        ".agents/",
        ".agentized/",
        "context/",
        "packages/",
        "AGENTS.md",
        "CLAUDE.md",
        ".githooks/",
        ".github/",
    )
    for rel in changed:
        assert any(rel == p or rel.startswith(p) for p in expected_prefixes), rel
    assert ".codex/config.toml" not in changed
    assert ".husky/pre-commit" not in changed
    assert "context/.agentized/hooks_owned.json" in changed
    cursor = json.loads((tmp_path / ".cursor/hooks.json").read_text(encoding="utf-8"))
    assert any(e.get("command") == "echo foreign-cursor" for e in cursor["hooks"]["sessionStart"])
    assert cursor["hooks"]["customEvent"] == [{"command": "foreign/cursor.py"}]
    assert all("agentized" not in e for e in cursor["hooks"]["sessionStart"] if isinstance(e, dict))
    claude = json.loads((tmp_path / ".claude/settings.json").read_text(encoding="utf-8"))
    assert claude["permissions"] == {"allow": ["Bash"]}
    assert claude["hooks"]["Notification"][0]["hooks"][0]["command"] == "echo n"
    codex = json.loads((tmp_path / ".codex/hooks.json").read_text(encoding="utf-8"))
    assert codex["description"] == "keep-codex"
    assert codex["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "echo foreign-codex"
    market = json.loads((tmp_path / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    assert market["name"] == "keep-market"
    assert market["plugins"][0]["name"] == "foreign-plug"
    assert any(p.get("name") == "agentized" for p in market["plugins"])


def test_connect_broken_claude_refuse_ok_false(tmp_path: Path, monkeypatch):
    _skeleton(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir(parents=True)
    broken = b"{not-json-claude"
    settings.write_bytes(broken)
    result = connect_mod.connect(tmp_path, context_rel="context", harnesses=["claude"])
    assert settings.read_bytes() == broken
    assert result["harnesses"]["claude"]["hooks_merge"]["action"] == "refuse"
    assert result.get("ok") is False


def test_connect_dry_run_tree_snapshot_writes_nothing(tmp_path: Path, monkeypatch):
    """`--dry-run` must leave the whole tree byte-identical (Lead REJECT-3)."""
    _skeleton(tmp_path)
    monkeypatch.chdir(tmp_path)
    cursor = tmp_path / ".cursor" / "hooks.json"
    cursor.parent.mkdir(parents=True)
    body = {
        "version": 1,
        "hooks": {"sessionStart": [{"command": "echo keep-dry"}]},
    }
    cursor.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    market = tmp_path / ".agents" / "plugins" / "marketplace.json"
    market.parent.mkdir(parents=True)
    market.write_text('{"name":"keep","plugins":[]}\n', encoding="utf-8")
    (tmp_path / ".husky").mkdir()
    (tmp_path / ".husky/pre-commit").write_text("#!/bin/sh\necho husky\n", encoding="utf-8")
    before = _tree_hash(tmp_path)
    result = connect_mod.connect(
        tmp_path,
        context_rel="context",
        harnesses=["cursor", "claude", "codex"],
        dry_run=True,
    )
    assert result.get("ok") is True
    assert result.get("dry_run") is True
    after = _tree_hash(tmp_path)
    assert after == before
    assert result["harnesses"]["cursor"]["hooks_merge"]["wrote"] is False
    assert result["harnesses"]["cursor"]["hooks_merge"]["dry_run"] is True
    assert result["harnesses"]["codex"]["marketplace_merge"]["wrote"] is False
    assert not (tmp_path / "context" / ".agentized" / "hooks_owned.json").exists()
