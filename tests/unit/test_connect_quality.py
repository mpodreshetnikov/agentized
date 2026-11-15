from __future__ import annotations

import subprocess
from pathlib import Path

from agentized.connect import (
    QUALITY_MARKER,
    _safe_install_template,
    connect,
    ensure_githooks_path,
    ensure_quality_config,
    pin_quality_templates,
)
from agentized.quality import load_quality


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
        root / "templates" / "quality",
    ):
        p.mkdir(parents=True, exist_ok=True)
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (root / "packages" / "shared" / "skills" / "navigate" / "SKILL.md").write_text(
        "---\nname: navigate\n---\n", encoding="utf-8"
    )
    (root / "packages" / "shared" / "hooks" / "scripts" / "session_start.py").write_text(
        "print('ok')\n", encoding="utf-8"
    )
    (root / "packages" / "shared" / "hooks" / "scripts" / "lease_warn.py").write_text(
        "print('ok')\n", encoding="utf-8"
    )
    (root / "templates" / "quality" / "pre-push").write_text(
        f"#!/bin/sh\n# {QUALITY_MARKER}\necho hi\n", encoding="utf-8"
    )
    (root / "templates" / "quality" / "ci.yml").write_text(
        f"# {QUALITY_MARKER}\nname: CI\n", encoding="utf-8"
    )


def test_ensure_quality_and_coverage(tmp_path: Path):
    _skeleton(tmp_path)
    info = ensure_quality_config(tmp_path, "context", coverage_pct=88)
    assert info["created"] is True
    cfg = load_quality(tmp_path)
    assert cfg["coverage"]["lines"] == 88.0


def test_safe_install_does_not_clobber_user(tmp_path: Path):
    src = tmp_path / "tpl"
    src.write_text(f"# {QUALITY_MARKER}\nA\n", encoding="utf-8")
    dst = tmp_path / "out"
    dst.write_text("# custom user workflow\n", encoding="utf-8")
    assert _safe_install_template(src, dst) == "skipped-user-file"
    assert "custom user" in dst.read_text(encoding="utf-8")


def test_safe_install_updates_marked(tmp_path: Path):
    src = tmp_path / "tpl"
    src.write_text(f"# {QUALITY_MARKER}\nNEW\n", encoding="utf-8")
    dst = tmp_path / "out"
    dst.write_text(f"# {QUALITY_MARKER}\nOLD\n", encoding="utf-8")
    assert _safe_install_template(src, dst) == "updated"
    assert "NEW" in dst.read_text(encoding="utf-8")


def test_connect_pins_quality(tmp_path: Path, monkeypatch):
    _skeleton(tmp_path)
    # also need quality-gates skill in shared for pin
    qdir = tmp_path / "packages" / "shared" / "skills" / "quality-gates"
    qdir.mkdir(parents=True)
    (qdir / "SKILL.md").write_text("---\nname: quality-gates\n---\n", encoding="utf-8")
    for pkg in ("agentized-cursor", "agentized-claude", "agentized-codex"):
        (tmp_path / "packages" / pkg).mkdir(parents=True, exist_ok=True)
    (tmp_path / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
    # invalid existing claude settings should be replaced safely
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{not-json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = connect(
        tmp_path,
        context_rel="context",
        harnesses=["cursor", "claude", "codex"],
        coverage_pct=80,
    )
    assert (tmp_path / "context" / "quality.json").exists()
    assert (tmp_path / "context" / "skills" / "quality-gates" / "SKILL.md").exists()
    assert (tmp_path / ".cursor" / "hooks.json").exists()
    assert (tmp_path / ".claude" / "settings.json").exists()
    assert (tmp_path / ".codex" / "hooks.json").exists()
    assert "NAV.md" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert result["quality_templates"]["pre_push"] in {"created", "updated", "unchanged"}
    assert result["quality_templates"]["hooks_path"] in {"set", "unchanged"}
    assert pin_quality_templates(tmp_path)["pre_push"] in {"unchanged", "updated", "skipped-user-file"}
    # second connect keeps a single AGENTIZED marker block
    again = connect(tmp_path, context_rel="context", harnesses=["cursor"])
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.count("AGENTIZED:BEGIN") == 1
    assert again["quality"]["path"].endswith("quality.json")


def test_ensure_githooks_path_preserves_user(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", "custom-hooks"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert ensure_githooks_path(tmp_path) == "preserved-user"
    assert ensure_githooks_path(tmp_path) == "preserved-user"
    # Cursor agent-hooks path is left alone
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", "/home/u/.cursor/agent-hooks/abc"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert ensure_githooks_path(tmp_path) == "skipped-cursor-agent-hooks"


def test_connect_requires_nav(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "context").mkdir()
    try:
        connect(tmp_path, context_rel="context", harnesses=[])
        raised = False
    except FileNotFoundError:
        raised = True
    assert raised
