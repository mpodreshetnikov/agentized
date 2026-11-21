"""Managed-hash connect: user edits preserved; untouched pins auto-update."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agentized.connect import connect, pin_reviewer_agents
from agentized.managed import (
    content_sha256,
    load_managed,
    managed_path,
    managed_write_text,
)
from agentized.quality import load_quality, save_quality, set_reviewer_options


def _minimal_external(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    ctx = tmp_path / "context"
    for p in (ctx / "tasks", ctx / "leases"):
        p.mkdir(parents=True, exist_ok=True)
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")


def test_user_edit_survives_reconnect(tmp_path: Path, monkeypatch):
    """(a) User edit → skipped_user; content preserved on re-connect."""
    _minimal_external(tmp_path)
    monkeypatch.chdir(tmp_path)
    result1 = connect(tmp_path, context_rel="context", harnesses=["cursor", "claude", "codex"])
    assert (tmp_path / "context" / ".agentized" / "managed.json").exists()
    assert result1.get("skipped_user") == []

    skill = tmp_path / "context" / "skills" / "acceptance-artifacts" / "SKILL.md"
    cursor_rev = tmp_path / ".cursor" / "agents" / "reviewer.md"
    claude_rev = tmp_path / ".claude" / "agents" / "reviewer.md"
    codex_toml = tmp_path / ".codex" / "agents" / "reviewer.toml"
    assert skill.exists() and cursor_rev.exists()

    skill.write_text(skill.read_text(encoding="utf-8") + "\n# USER_SKILL_NOTE\n", encoding="utf-8")
    cursor_rev.write_text(
        cursor_rev.read_text(encoding="utf-8") + "\nUSER_EDIT_LINE = 42\n", encoding="utf-8"
    )
    claude_rev.write_text(
        claude_rev.read_text(encoding="utf-8") + "\nCLAUDE_USER_EDIT\n", encoding="utf-8"
    )
    codex_toml.write_text(
        codex_toml.read_text(encoding="utf-8") + "\n# USER_TOML_NOTE\n", encoding="utf-8"
    )

    result2 = connect(tmp_path, context_rel="context", harnesses=["cursor", "claude", "codex"])
    assert "USER_SKILL_NOTE" in skill.read_text(encoding="utf-8")
    assert "USER_EDIT_LINE = 42" in cursor_rev.read_text(encoding="utf-8")
    assert "CLAUDE_USER_EDIT" in claude_rev.read_text(encoding="utf-8")
    assert "USER_TOML_NOTE" in codex_toml.read_text(encoding="utf-8")
    skipped = result2.get("skipped_user") or []
    assert any("acceptance-artifacts" in p for p in skipped)
    assert any("reviewer.md" in p for p in skipped)
    assert any("reviewer.toml" in p for p in skipped)


def test_untouched_updates_on_template_and_model_change(tmp_path: Path, monkeypatch):
    """(b) Untouched pin updates when shared skill or quality.json model changes."""
    _minimal_external(tmp_path)
    # Local packages so we can mutate the skill source.
    shared = tmp_path / "packages" / "shared"
    (shared / "skills" / "demo").mkdir(parents=True)
    (shared / "skills" / "demo" / "SKILL.md").write_text("VERSION_ONE\n", encoding="utf-8")
    (shared / "hooks" / "scripts").mkdir(parents=True)
    (shared / "hooks" / "scripts" / "session_start.py").write_text("print(1)\n", encoding="utf-8")
    (shared / "agents").mkdir(parents=True)
    (shared / "agents" / "reviewer.md").write_text(
        "---\nname: reviewer\nmodel: old\nreadonly: true\n---\n\nBody\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    connect(tmp_path, context_rel="context", harnesses=["cursor"])

    skill = tmp_path / "context" / "skills" / "demo" / "SKILL.md"
    cursor_skill = tmp_path / ".cursor" / "skills" / "demo" / "SKILL.md"
    assert skill.read_text(encoding="utf-8") == "VERSION_ONE\n"
    assert cursor_skill.read_text(encoding="utf-8") == "VERSION_ONE\n"

    (shared / "skills" / "demo" / "SKILL.md").write_text("VERSION_TWO\n", encoding="utf-8")
    connect(tmp_path, context_rel="context", harnesses=["cursor"])
    assert skill.read_text(encoding="utf-8") == "VERSION_TWO\n"
    assert cursor_skill.read_text(encoding="utf-8") == "VERSION_TWO\n"

    # quality.json model change → untouched reviewer re-renders
    set_reviewer_options(tmp_path, context_rel="context", harness="cursor", model="gpt-5.4-test")
    # Without force, connect should still update because file hash matches manifest
    # (untouched) and desired body changed.
    pin_reviewer_agents(tmp_path, "context")
    body = (tmp_path / ".cursor" / "agents" / "reviewer.md").read_text(encoding="utf-8")
    assert "gpt-5.4-test" in body


def test_context_skill_edit_propagates_to_untouched_mirrors(tmp_path: Path, monkeypatch):
    """(c) Edit in context/skills propagates to untouched harness mirrors."""
    _minimal_external(tmp_path)
    monkeypatch.chdir(tmp_path)
    connect(tmp_path, context_rel="context", harnesses=["cursor"])

    ctx_skill = tmp_path / "context" / "skills" / "acceptance-artifacts" / "SKILL.md"
    cursor_skill = tmp_path / ".cursor" / "skills" / "acceptance-artifacts" / "SKILL.md"
    assert ctx_skill.exists() and cursor_skill.exists()
    before_mirror = cursor_skill.read_text(encoding="utf-8")

    # User edits Context SoT (manifest will mark context skill as skipped_user).
    # Mirror is still untouched → next connect copies Context → mirror.
    ctx_skill.write_text(
        ctx_skill.read_text(encoding="utf-8") + "\n# CONTEXT_EDIT\n", encoding="utf-8"
    )
    result = connect(tmp_path, context_rel="context", harnesses=["cursor"])
    assert "CONTEXT_EDIT" in ctx_skill.read_text(encoding="utf-8")
    mirror_text = cursor_skill.read_text(encoding="utf-8")
    assert "CONTEXT_EDIT" in mirror_text
    assert mirror_text != before_mirror
    # Context skill itself listed as skipped_user; mirror should not be.
    skipped = result.get("skipped_user") or []
    assert any("context/skills" in p.replace("\\", "/") for p in skipped)
    assert not any(".cursor/skills" in p.replace("\\", "/") for p in skipped)


def test_review_set_force_overwrites_user_edit(tmp_path: Path, monkeypatch):
    """review set force-repins even when the reviewer file was customized."""
    _minimal_external(tmp_path)
    monkeypatch.chdir(tmp_path)
    connect(tmp_path, context_rel="context", harnesses=["cursor"])
    rev = tmp_path / ".cursor" / "agents" / "reviewer.md"
    rev.write_text(rev.read_text(encoding="utf-8") + "\nCUSTOM\n", encoding="utf-8")
    connect(tmp_path, context_rel="context", harnesses=["cursor"])
    assert "CUSTOM" in rev.read_text(encoding="utf-8")

    set_reviewer_options(tmp_path, context_rel="context", harness="cursor", model="force-model-x")
    pin_reviewer_agents(tmp_path, "context", force=True)
    text = rev.read_text(encoding="utf-8")
    model_lines = [ln for ln in text.splitlines() if ln.startswith("model:")]
    assert model_lines == ["model: force-model-x"]
    assert [ln for ln in text.splitlines() if ln == "CUSTOM"] == []


def test_legacy_bootstrap_records_without_overwrite(tmp_path: Path, monkeypatch):
    """Pre-manifest file: first managed connect bootstraps hash, keeps bytes."""
    _minimal_external(tmp_path)
    monkeypatch.chdir(tmp_path)
    # Pretend an already-connected project: skill exists, no managed.json.
    skill = tmp_path / "context" / "skills" / "legacy" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("LEGACY_USER_OR_OLD_PIN\n", encoding="utf-8")

    # Seed packages so connect has something to desire that differs.
    shared = tmp_path / "packages" / "shared"
    (shared / "skills" / "legacy").mkdir(parents=True)
    (shared / "skills" / "legacy" / "SKILL.md").write_text("NEW_TEMPLATE\n", encoding="utf-8")
    (shared / "hooks" / "scripts").mkdir(parents=True)
    (shared / "hooks" / "scripts" / "session_start.py").write_text("print(1)\n", encoding="utf-8")
    (shared / "agents").mkdir(parents=True)
    (shared / "agents" / "reviewer.md").write_text(
        "---\nname: reviewer\nreadonly: true\n---\nBody\n", encoding="utf-8"
    )

    connect(tmp_path, context_rel="context", harnesses=["cursor"])
    assert skill.read_text(encoding="utf-8") == "LEGACY_USER_OR_OLD_PIN\n"
    man = load_managed(tmp_path, "context")
    key = "context/skills/legacy/SKILL.md"
    assert key in man["files"]
    assert man["files"][key] == content_sha256(b"LEGACY_USER_OR_OLD_PIN\n")

    # Second connect: untouched (hash matches) → auto-update to new template.
    connect(tmp_path, context_rel="context", harnesses=["cursor"])
    assert skill.read_text(encoding="utf-8") == "NEW_TEMPLATE\n"


def test_managed_write_unit_statuses(tmp_path: Path):
    ctx = "context"
    (tmp_path / ctx).mkdir()
    path = tmp_path / ctx / "f.txt"
    assert managed_write_text(tmp_path, ctx, path, "a\n") == "created"
    assert managed_write_text(tmp_path, ctx, path, "a\n") == "unchanged"
    assert managed_write_text(tmp_path, ctx, path, "b\n") == "updated"
    path.write_text("user\n", encoding="utf-8")
    assert managed_write_text(tmp_path, ctx, path, "c\n") == "skipped_user"
    assert path.read_text(encoding="utf-8") == "user\n"
    assert managed_write_text(tmp_path, ctx, path, "c\n", force=True) == "updated"
    assert path.read_text(encoding="utf-8") == "c\n"
    assert managed_path(tmp_path, ctx).exists()
