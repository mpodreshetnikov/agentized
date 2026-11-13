from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agentized.connect import connect, QUALITY_MARKER


def _skeleton(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    ctx = root / "context"
    for p in (
        ctx / "tasks",
        ctx / "leases",
        ctx / "hooks" / "scripts",
        ctx / "skills",
        root / "packages" / "shared" / "skills" / "navigate",
        root / "packages" / "shared" / "hooks" / "scripts",
        root / "packages" / "shared" / "agents",
        root / "templates" / "quality",
    ):
        p.mkdir(parents=True, exist_ok=True)
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (root / "packages" / "shared" / "skills" / "navigate" / "SKILL.md").write_text(
        "---\nname: navigate\n---\n", encoding="utf-8"
    )
    for name in (
        "session_start.py",
        "lease_warn.py",
        "process_guard.py",
        "ensure_agent_hooks.py",
        "_bootstrap.py",
    ):
        (root / "packages" / "shared" / "hooks" / "scripts" / name).write_text(
            "print('ok')\n", encoding="utf-8"
        )
    (root / "packages" / "shared" / "agents" / "reviewer.md").write_text(
        "---\nname: reviewer\n---\nbody\n", encoding="utf-8"
    )
    (root / "templates" / "quality" / "pre-push").write_text(
        f"#!/bin/sh\n# {QUALITY_MARKER}\necho hi\n", encoding="utf-8"
    )
    (root / "templates" / "quality" / "ci.yml").write_text(
        f"# {QUALITY_MARKER}\nname: CI\n", encoding="utf-8"
    )
    for pkg in ("agentized-cursor", "agentized-claude", "agentized-codex"):
        (root / "packages" / pkg).mkdir(parents=True, exist_ok=True)


def test_connect_wires_ensure_agent_hooks_all_harnesses(tmp_path: Path, monkeypatch):
    _skeleton(tmp_path)
    monkeypatch.chdir(tmp_path)
    connect(tmp_path, context_rel="context", harnesses=["cursor", "claude", "codex"])

    cursor = json.loads((tmp_path / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    assert any(
        "ensure_agent_hooks" in (h.get("command") or "")
        for h in cursor["hooks"].get("beforeShellExecution", [])
    )
    assert (tmp_path / ".cursor" / "hooks" / "ensure_agent_hooks.py").exists()

    claude = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    pre = claude["hooks"]["PreToolUse"]
    bash_hooks = [b for b in pre if b.get("matcher") == "Bash"]
    assert bash_hooks
    cmds = " ".join(
        h.get("command", "") for block in bash_hooks for h in block.get("hooks", [])
    )
    assert "ensure_agent_hooks" in cmds
    assert (tmp_path / ".claude" / "hooks" / "ensure_agent_hooks.py").exists()

    codex = json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    pre = codex["hooks"]["PreToolUse"]
    bash_hooks = [b for b in pre if b.get("matcher") == "Bash"]
    assert bash_hooks
    cmds = " ".join(
        h.get("command", "") for block in bash_hooks for h in block.get("hooks", [])
    )
    assert "ensure_agent_hooks" in cmds
    assert (tmp_path / ".codex" / "hooks" / "ensure_agent_hooks.py").exists()

    assert (tmp_path / "context" / "reporting.json").exists()
    assert (tmp_path / ".codex" / "agents" / "reviewer.toml").exists()
