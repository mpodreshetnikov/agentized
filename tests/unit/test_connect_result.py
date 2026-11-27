"""connect() result shape, context plumbing and quality template pinning."""

from __future__ import annotations

import subprocess
from pathlib import Path

import agentized.connect as cm
from agentized.connect import (
    connect,
    pin_quality_templates,
)
from agentized.paths import load_state


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    return root


def test_connect_result_shape_and_context_plumbing(tmp_path: Path):
    root = _repo(tmp_path / "r")
    (root / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
    first = connect(root, context_rel="ctx", coverage_pct=55)
    assert sorted(first) == [
        "env_check",
        "harnesses",
        "idempotent",
        "managed_manifest",
        "pinned",
        "process_control",
        "quality",
        "quality_templates",
        "reporting",
        "reviewer",
        "skeleton",
        "skipped_user",
        "state",
    ]
    assert list(first["harnesses"]) == ["cursor", "claude", "codex"]
    assert first["managed_manifest"] == "ctx/.agentized/managed.json"
    assert (root / "ctx" / ".agentized" / "managed.json").is_file()
    assert first["process_control"]["path"] == "ctx/process-control.json"
    assert first["quality"]["path"] == "ctx/quality.json"
    assert first["quality"]["coverage_pct"] == 55
    assert first["env_check"]["path"] == "ctx/env-check.json"
    assert first["reporting"]["path"] == "ctx/reporting.json"
    assert (root / "ctx" / "NAV.md").is_file() and not (root / "context").exists()
    assert first["idempotent"] is False
    state = {
        "version": cm.__version__,
        "context": "ctx",
        "harnesses": ["cursor", "claude", "codex"],
        "agents_md_updated": True,
        "claude_md_updated": True,
        "coverage_pct": 55,
    }
    assert first["state"] == state
    assert load_state(root) == state
    for name in ("AGENTS.md", "CLAUDE.md"):
        text = (root / name).read_text(encoding="utf-8")
        assert cm.CONNECT_MARKER_BEGIN in text and cm.CONNECT_MARKER_END in text
        assert "ctx/" in text
    assert (root / "CLAUDE.md").read_text(encoding="utf-8").startswith("# mine\n")
    connect(root, context_rel="ctx", coverage_pct=55)
    third = connect(root, context_rel="ctx", coverage_pct=55)
    assert third["idempotent"] is True
    assert third["state"]["agents_md_updated"] is False
    assert third["state"]["claude_md_updated"] is False


def test_connect_idempotent_flag_needs_both_blocks_unchanged(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path / "r")
    answers = iter([(True, False), (False, True), (False, False), (True, True)])
    flags: list[tuple[bool, bool]] = []

    def fake_upsert(path, begin, end, body, *, create):
        return flags[-1][0 if path.name == "AGENTS.md" else 1]

    (root / "CLAUDE.md").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(cm, "_upsert_marked_block", fake_upsert)
    seen = []
    for agents, claude in answers:
        flags.append((agents, claude))
        res = connect(root, harnesses=["cursor"])
        seen.append((res["state"]["agents_md_updated"], res["state"]["claude_md_updated"]))
        assert res["idempotent"] is (not agents and not claude)
    assert seen == [(True, False), (False, True), (False, False), (True, True)]


def test_connect_claude_block_not_created_and_marked_with_context(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path / "r")
    calls: list[tuple] = []
    real = cm._upsert_marked_block

    def spy(path, begin, end, body, *, create):
        calls.append((path.name, begin, end, create, body))
        return real(path, begin, end, body, create=create)

    monkeypatch.setattr(cm, "_upsert_marked_block", spy)
    connect(root, context_rel="ctx", harnesses=["cursor"])
    assert [c[0] for c in calls] == ["AGENTS.md"] and calls[0][3] is True
    assert not (root / "CLAUDE.md").exists()
    (root / "CLAUDE.md").write_text("x\n", encoding="utf-8")
    calls.clear()
    connect(root, context_rel="ctx", harnesses=["cursor"])
    assert [c[0] for c in calls] == ["AGENTS.md", "CLAUDE.md"]
    assert calls[1][1:4] == (cm.CONNECT_MARKER_BEGIN, cm.CONNECT_MARKER_END, False)
    assert calls[1][4] == cm.CLAUDE_BLOCK_TEMPLATE.format(
        begin=cm.CONNECT_MARKER_BEGIN, end=cm.CONNECT_MARKER_END, context="ctx"
    )
    assert calls[0][4] == cm.AGENTS_BLOCK_TEMPLATE.format(
        begin=cm.CONNECT_MARKER_BEGIN, end=cm.CONNECT_MARKER_END, context="ctx"
    )


def test_connect_harness_selection_manifest_and_skipped_dedupe(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path / "r")
    manifests: list[tuple[str, object]] = []

    def fake_pin(name, skipped):
        def fn(root_, context_rel, *, manifest):
            manifests.append((name, manifest))
            return {"skipped_user": skipped}

        return fn

    monkeypatch.setattr(cm, "pin_context_skills_hooks", fake_pin("pinned", ["a", "b"]))
    monkeypatch.setattr(cm, "pin_reviewer_agents", fake_pin("reviewer", ["b", "c"]))
    monkeypatch.setattr(cm, "install_cursor", fake_pin("cursor", ["c", "a", "d"]))
    monkeypatch.setattr(cm, "install_claude", fake_pin("claude", None))
    monkeypatch.setattr(cm, "install_codex", fake_pin("codex", ["e", "d"]))
    res = connect(root, context_rel="ctx")
    assert res["skipped_user"] == ["a", "b", "c", "d", "e"]
    assert len({id(m) for _, m in manifests}) == 1
    assert all(isinstance(m, dict) for _, m in manifests)
    assert [n for n, _ in manifests] == ["pinned", "reviewer", "cursor", "claude", "codex"]
    assert list(res["harnesses"]) == ["cursor", "claude", "codex"]
    assert res["harnesses"]["claude"] == {"skipped_user": None}
    only = connect(root, harnesses=["codex"])
    assert list(only["harnesses"]) == ["codex"] and only["state"]["harnesses"] == ["codex"]
    assert only["skipped_user"] == ["a", "b", "c", "e", "d"]
    none = connect(root, harnesses=["cursor", "claude"])
    assert list(none["harnesses"]) == ["cursor", "claude"]


def _local_templates(root: Path, *, stryker: bool) -> Path:
    tdir = root / "templates" / "quality"
    tdir.mkdir(parents=True)
    for name in ("pre-push", "commit-msg", "ci.yml"):
        (tdir / name).write_text(f"# AGENTIZED:QUALITY {name}\n", encoding="utf-8")
    if stryker:
        (tdir / "stryker.config.mjs.example").write_text("{}\n", encoding="utf-8")
    return tdir


def test_pin_quality_templates_result_paths_and_flags(tmp_path: Path):
    bare = tmp_path / "bare"
    bare.mkdir()
    tdir = _local_templates(bare, stryker=True)
    (bare / ".GIT").write_text("x", encoding="utf-8")
    (bare / "XX.gitXX").write_text("x", encoding="utf-8")
    res = pin_quality_templates(bare)
    assert res == {
        "pre_push": "created",
        "commit_msg": "created",
        "ci_workflow": "created",
        "js_guidance": True,
        "templates_from": str(tdir),
        "hooks_path": "skipped-no-git",
    }
    for src, dst in (
        ("pre-push", ".githooks/pre-push"),
        ("commit-msg", ".githooks/commit-msg"),
        ("ci.yml", ".github/workflows/ci.yml"),
    ):
        assert (bare / dst).read_text(encoding="utf-8") == f"# AGENTIZED:QUALITY {src}\n"
    repo = _repo(tmp_path / "repo")
    _local_templates(repo, stryker=False)
    res = pin_quality_templates(repo)
    assert res["hooks_path"] == "set" and res["js_guidance"] is False
    gitfile = tmp_path / "wt"
    _local_templates(gitfile, stryker=False)
    (gitfile / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert pin_quality_templates(gitfile)["hooks_path"] != "skipped-no-git"
