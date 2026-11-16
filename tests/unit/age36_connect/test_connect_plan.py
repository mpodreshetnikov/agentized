"""AGE-36: dry-run plan accuracy (quality / marketplace / pin trees / coverage)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agentized.connect import QUALITY_MARKER, connect
from agentized.connect_dry_run import desired_codex_marketplace, plan_connect_writes
from agentized.connect_plan import (
    plan_ensure_json,
    plan_hooks_path_action,
    plan_json_document_action,
    plan_marker_action,
    plan_pin_tree_action,
    plan_template_action,
    plan_quality_action,
    plans_include_refuse,
    tree_digests,
    trees_identical,
)
from agentized.paths import CONNECT_MARKER_BEGIN, CONNECT_MARKER_END
from agentized.quality import save_quality


def _skeleton(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    ctx = root / "context"
    for p in (
        ctx / "tasks",
        ctx / "leases",
        ctx / "hooks" / "scripts",
        ctx / "skills" / "navigate",
        root / "packages" / "shared" / "skills" / "navigate",
        root / "packages" / "shared" / "hooks" / "scripts",
        root / "packages" / "agentized-cursor" / "skills",
        root / "packages" / "agentized-codex" / "skills",
        root / "templates" / "quality",
    ):
        p.mkdir(parents=True, exist_ok=True)
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (ctx / "tasks" / "INDEX.md").write_text("# tasks\n", encoding="utf-8")
    (ctx / "leases" / "INDEX.md").write_text("# leases\n", encoding="utf-8")
    skill = "---\nname: navigate\n---\nbody\n"
    (root / "packages" / "shared" / "skills" / "navigate" / "SKILL.md").write_text(
        skill, encoding="utf-8"
    )
    (ctx / "skills" / "navigate" / "SKILL.md").write_text(skill, encoding="utf-8")
    hook = "print('ok')\n"
    (root / "packages" / "shared" / "hooks" / "scripts" / "session_start.py").write_text(
        hook, encoding="utf-8"
    )
    (ctx / "hooks" / "scripts" / "session_start.py").write_text(hook, encoding="utf-8")
    (root / "templates" / "quality" / "pre-push").write_text(
        f"#!/bin/sh\n# {QUALITY_MARKER}\necho hi\n", encoding="utf-8"
    )
    (root / "templates" / "quality" / "ci.yml").write_text(
        f"# {QUALITY_MARKER}\nname: CI\n", encoding="utf-8"
    )


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            out[str(path.relative_to(root))] = path.read_bytes()
    return out


def test_plan_quality_warn_to_hard_is_update_not_skip(tmp_path: Path):
    _skeleton(tmp_path)
    save_quality(
        tmp_path,
        {
            "coverage": {"lines": 80, "branches": 80},
            "test_smells": {"mode": "warn", "enabled": True},
            "architecture": {"mode": "hard"},
        },
    )
    assert plan_quality_action(tmp_path, "context") == "update"
    assert plan_quality_action(tmp_path, "context", coverage_pct=80) == "update"


def test_plan_quality_honors_coverage_pct(tmp_path: Path):
    _skeleton(tmp_path)
    save_quality(
        tmp_path,
        {
            "coverage": {"lines": 80, "branches": 80},
            "test_smells": {"mode": "hard"},
            "architecture": {"mode": "hard"},
        },
    )
    assert plan_quality_action(tmp_path, "context") == "skip"
    assert plan_quality_action(tmp_path, "context", coverage_pct=80) == "skip"
    assert plan_quality_action(tmp_path, "context", coverage_pct=90) == "update"
    assert plan_quality_action(tmp_path, "context", coverage_pct=80.0) == "skip"


def test_plan_quality_missing_is_create(tmp_path: Path):
    _skeleton(tmp_path)
    assert plan_quality_action(tmp_path, "context") == "create"


def test_pin_tree_identical_skips(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "a.txt").write_text("same\n", encoding="utf-8")
    (dst / "a.txt").write_text("same\n", encoding="utf-8")
    assert trees_identical(src, dst) is True
    assert plan_pin_tree_action(dst, src) == "skip"
    (dst / "a.txt").write_text("diff\n", encoding="utf-8")
    assert plan_pin_tree_action(dst, src) == "update"
    assert plan_pin_tree_action(tmp_path / "missing", src) == "create"


def test_marketplace_and_plugin_refresh_in_plan(tmp_path: Path):
    _skeleton(tmp_path)
    dry = plan_connect_writes(
        tmp_path, context_rel="context", harnesses=["cursor", "codex"], coverage_pct=85
    )
    by_path = {w["path"]: w for w in dry["planned_writes"]}
    assert ".agents/plugins/marketplace.json" in by_path
    assert by_path[".agents/plugins/marketplace.json"]["action"] == "create"
    assert by_path[".agents/plugins/marketplace.json"]["kind"] == "marketplace"
    assert "packages/agentized-cursor/skills/" in by_path
    assert by_path["packages/agentized-cursor/skills/"]["kind"] == "plugin-refresh"
    assert "packages/agentized-codex/skills/" in by_path
    assert by_path["context/quality.json"]["action"] == "create"
    assert dry["coverage_pct"] == 85
    # Existing quality + --coverage must plan update (not false skip).
    save_quality(
        tmp_path,
        {
            "coverage": {"lines": 80, "branches": 80},
            "test_smells": {"mode": "hard"},
            "architecture": {"mode": "hard"},
        },
    )
    dry2 = plan_connect_writes(
        tmp_path, context_rel="context", harnesses=["codex"], coverage_pct=85
    )
    q2 = next(w for w in dry2["planned_writes"] if w["path"] == "context/quality.json")
    assert q2["action"] == "update"


def test_marketplace_skip_when_identical(tmp_path: Path):
    path = tmp_path / "marketplace.json"
    desired = desired_codex_marketplace()
    path.write_text(json.dumps(desired, indent=2) + "\n", encoding="utf-8")
    assert plan_json_document_action(path, desired) == "skip"
    path.write_text("{}\n", encoding="utf-8")
    assert plan_json_document_action(path, desired) == "update"


def test_dry_run_no_writes_and_actions_valid(tmp_path: Path, monkeypatch):
    _skeleton(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "hooks.json").write_text(
        json.dumps({"version": 1, "hooks": {}}, indent=2) + "\n", encoding="utf-8"
    )
    before = _tree_snapshot(tmp_path)
    before_git = subprocess.run(
        ["git", "config", "--local", "--list"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    ).stdout
    dry = connect(
        tmp_path,
        context_rel="context",
        harnesses=["cursor", "claude", "codex"],
        coverage_pct=88,
        dry_run=True,
    )
    assert _tree_snapshot(tmp_path) == before
    after_git = subprocess.run(
        ["git", "config", "--local", "--list"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    ).stdout
    assert after_git == before_git
    assert dry["dry_run"] is True
    assert dry["refused"] is False
    actions = {w["action"] for w in dry["planned_writes"]}
    assert actions <= {"create", "update", "merge", "skip", "refuse"}
    paths = {w["path"] for w in dry["planned_writes"]}
    for required in (
        "AGENTS.md",
        "context/quality.json",
        ".agents/plugins/marketplace.json",
        "packages/agentized-cursor/skills/",
        "core.hooksPath",
    ):
        assert required in paths, required
    assert dry["coverage_pct"] == 88
    quality = next(w for w in dry["planned_writes"] if w["path"] == "context/quality.json")
    # Missing quality.json → create even when --coverage is set.
    assert quality["action"] == "create"


def test_dry_run_identical_skills_skip(tmp_path: Path):
    _skeleton(tmp_path)
    dry = plan_connect_writes(tmp_path, context_rel="context", harnesses=["cursor"])
    skills = next(w for w in dry["planned_writes"] if w["path"] == "context/skills/")
    assert skills["action"] == "skip"


def test_plans_include_refuse():
    cases = [
        ([{"action": "skip"}, {"action": "update"}], 0),
        ([{"action": "skip"}, {"action": "refuse"}], 1),
        ([], 0),
        ([{"action": "create"}], 0),
        ([{"action": "refused"}], 0),
        ([{"action": "Refuse"}], 0),
        ([{"action": "refuse"}, {"action": "refuse"}], 2),
    ]
    for planned, expected_count in cases:
        got = sum(1 for item in planned if item.get("action") == "refuse")
        flag = 1 if plans_include_refuse(planned) else 0
        assert [got, flag] == [expected_count, 1 if expected_count > 0 else 0]


def test_plan_marker_and_template_actions(tmp_path: Path):
    body = f"{CONNECT_MARKER_BEGIN}\nX\n{CONNECT_MARKER_END}\n"
    missing = tmp_path / "AGENTS.md"
    assert plan_marker_action(missing, body, create=True) == "create"
    assert plan_marker_action(missing, body, create=False) == "skip"
    missing.write_text("user preface\n", encoding="utf-8")
    assert plan_marker_action(missing, body, create=True) == "merge"
    # Exact shape the planner emits when pre/post are empty.
    missing.write_text("\n\n" + body.rstrip() + "\n", encoding="utf-8")
    assert plan_marker_action(missing, body, create=True) == "skip"
    missing.write_text(
        f"pre\n{CONNECT_MARKER_BEGIN}\nold\n{CONNECT_MARKER_END}\npost\n",
        encoding="utf-8",
    )
    assert plan_marker_action(missing, body, create=True) == "update"

    src = tmp_path / "pre-push"
    dst = tmp_path / "dst-pre"
    assert plan_template_action(src, dst) == "skip"
    src.write_text(f"# {QUALITY_MARKER}\nv1\n", encoding="utf-8")
    assert plan_template_action(src, dst) == "create"
    dst.write_text("user file\n", encoding="utf-8")
    assert plan_template_action(src, dst) == "skip"
    dst.write_text(f"# {QUALITY_MARKER}\nv1\n", encoding="utf-8")
    assert plan_template_action(src, dst) == "skip"
    dst.write_text(f"# {QUALITY_MARKER}\nv0\n", encoding="utf-8")
    assert plan_template_action(src, dst) == "update"


def test_plan_pin_file_and_pycache_ignored(tmp_path: Path):
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("x\n", encoding="utf-8")
    dst.write_text("x\n", encoding="utf-8")
    assert plan_pin_tree_action(dst, src) == "skip"
    dst.write_text("y\n", encoding="utf-8")
    assert plan_pin_tree_action(dst, src) == "update"
    # file vs dir mismatch → update
    ddir = tmp_path / "dir"
    ddir.mkdir()
    assert plan_pin_tree_action(ddir, src) == "update"
    assert plan_pin_tree_action(dst, None) == "update"
    cache = tmp_path / "tree"
    cache.mkdir()
    (cache / "__pycache__").mkdir()
    (cache / "__pycache__" / "x.pyc").write_bytes(b"abc")
    (cache / "keep.txt").write_text("k\n", encoding="utf-8")
    dig = tree_digests(cache)
    assert list(dig.keys()) == ["keep.txt"]


def test_plan_hooks_path_create_and_skip(tmp_path: Path):
    assert plan_hooks_path_action(tmp_path) == "skip"
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    assert plan_hooks_path_action(tmp_path) == "create"
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", ".githooks"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert plan_hooks_path_action(tmp_path) == "skip"


def test_plan_quality_architecture_warn_and_branch_mismatch(tmp_path: Path):
    _skeleton(tmp_path)
    save_quality(
        tmp_path,
        {
            "coverage": {"lines": 90, "branches": 80},
            "test_smells": {"mode": "hard"},
            "architecture": {"mode": "warn"},
        },
    )
    assert plan_quality_action(tmp_path, "context") == "update"
    save_quality(
        tmp_path,
        {
            "coverage": {"lines": 90, "branches": 80},
            "test_smells": {"mode": "hard"},
            "architecture": {"mode": "hard"},
        },
    )
    assert plan_quality_action(tmp_path, "context", coverage_pct=90) == "update"


def test_plan_json_oserror_is_update(tmp_path: Path, monkeypatch):
    path = tmp_path / "m.json"
    path.write_text("{}\n", encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(Path, "read_text", boom)
    assert plan_json_document_action(path, {"a": 1}) == "update"


def test_plugin_refresh_skipped_without_package(tmp_path: Path):
    _skeleton(tmp_path)
    # Remove cursor plugin package → no plugin-refresh rows for cursor.
    import shutil

    shutil.rmtree(tmp_path / "packages" / "agentized-cursor")
    dry = plan_connect_writes(tmp_path, context_rel="context", harnesses=["cursor"])
    plugin_rows = [w for w in dry["planned_writes"] if w.get("kind") == "plugin-refresh"]
    assert plugin_rows == []


def test_tree_digests_missing_and_bad_action(tmp_path: Path, monkeypatch):
    assert tree_digests(tmp_path / "no-such-tree") == {}
    # Absolute hooksPath that resolves to .githooks → skip.
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    abs_hooks = tmp_path / ".githooks"
    abs_hooks.mkdir()
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", str(abs_hooks)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert plan_hooks_path_action(tmp_path) == "skip"

    # Force invalid action to hit validation.
    import agentized.connect_dry_run as cdr

    monkeypatch.setattr(
        cdr,
        "plan_harness_hooks",
        lambda *a, **k: [{"path": "x", "action": "nope", "harness": "cursor"}],
    )
    try:
        plan_connect_writes(tmp_path, context_rel="context", harnesses=["cursor"])
        raised = 0
    except ValueError as exc:
        raised = 1
        assert "create|update|merge|skip|refuse" in str(exc)
    assert raised == 1


def test_marker_body_without_trailing_newline(tmp_path: Path):
    # Body without trailing newline exercises endswith("\n") false branch.
    body = f"{CONNECT_MARKER_BEGIN}\nX\n{CONNECT_MARKER_END}"
    path = tmp_path / "AGENTS.md"
    path.write_text("\n\n" + body + "\n", encoding="utf-8")
    assert plan_marker_action(path, body, create=True) == "skip"


def test_plan_ensure_json_exact(tmp_path: Path):
    path = tmp_path / "x.json"
    assert plan_ensure_json(path) == "create"
    path.write_text("{}\n", encoding="utf-8")
    assert plan_ensure_json(path) == "skip"


def test_desired_marketplace_exact_bytes():
    expected = (
        "{\n"
        '  "name": "agentized-local",\n'
        '  "plugins": [\n'
        "    {\n"
        '      "name": "agentized",\n'
        '      "source": {\n'
        '        "source": "local",\n'
        '        "path": "./packages/agentized-codex"\n'
        "      },\n"
        '      "category": "Productivity"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )
    assert json.dumps(desired_codex_marketplace(), indent=2) + "\n" == expected
