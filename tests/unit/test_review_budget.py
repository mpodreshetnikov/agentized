from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agentized.connect import _render_reviewer_agent, connect, pin_reviewer_agents
from agentized.quality import load_quality, set_reviewer_options
from agentized.review_budget import (
    allow_review,
    decode_git_path,
    default_reviewer_config,
    evaluate_delta,
    expand_numstat_paths,
    load_state,
    record_review,
    reset_scope,
    save_state,
    status,
)
import pytest


def test_expand_numstat_paths_rename_brace():
    assert expand_numstat_paths(".github/{disabled => workflows}/deploy.yml") == [
        ".github/disabled/deploy.yml",
        ".github/workflows/deploy.yml",
    ]
    assert expand_numstat_paths("old.py => new.py") == ["old.py", "new.py"]
    assert expand_numstat_paths("runtime/x.py") == ["runtime/x.py"]


def test_decode_git_quoted_non_ascii_path():
    quoted = '".github/workflows/d\\303\\251ploy.yml"'
    assert decode_git_path(quoted) == ".github/workflows/déploy.yml"
    assert expand_numstat_paths(quoted) == [".github/workflows/déploy.yml"]


def _git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def test_default_reviewer_config():
    cfg = default_reviewer_config()
    assert cfg["budget_max"] == 3
    assert cfg["effort"] == "high"
    assert cfg["model"]


def test_allow_first_then_budget(tmp_path: Path, monkeypatch):
    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps({"version": 1, "reviewer": {"budget_max": 2, "delta_lines": 1}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    first = allow_review(tmp_path)
    assert first["ok"] is True
    assert first["action"] == "request"
    head = status(tmp_path)["head"]
    record_review(tmp_path, head, findings=1)
    # same head → skip
    again = allow_review(tmp_path)
    assert again["ok"] is False
    assert again["action"] == "skip"
    # new commit then second pass
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "c2"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "x.py").write_text("print(1)\n" * 50, encoding="utf-8")
    subprocess.run(["git", "add", "runtime/x.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "code"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    second = allow_review(tmp_path)
    assert second["ok"] is True
    record_review(tmp_path, status(tmp_path)["head"], findings=0)
    # budget 2 exhausted
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "c3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "runtime" / "y.py").write_text("print(2)\n" * 50, encoding="utf-8")
    subprocess.run(["git", "add", "runtime/y.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "more"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    blocked = allow_review(tmp_path)
    assert blocked["ok"] is False
    assert blocked["action"] == "escalate"


def test_disabled_and_cli(tmp_path: Path, monkeypatch):
    from agentized.connect import pin_reviewer_agents
    from agentized.review_budget import (
        evaluate_delta,
        main as review_main,
        load_state,
        save_state,
    )

    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps({"version": 1, "reviewer": {"enabled": False}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agentized.review_budget.find_repo_root", lambda: tmp_path)
    off = allow_review(tmp_path)
    assert off["action"] == "disabled"
    assert review_main(["status", "--context", "context"]) == 0
    assert review_main(["allow", "--context", "context"]) == 1
    # corrupt state still loads defaults
    save_state(tmp_path, {"used": 0})
    (tmp_path / ".agentized" / "review-state.json").write_text("{nope", encoding="utf-8")
    assert load_state(tmp_path)["used"] == 0
    (tmp_path / ".agentized" / "review-state.json").write_text("[]\n", encoding="utf-8")
    assert load_state(tmp_path)["used"] == 0
    # record + status path
    head = status(tmp_path)["head"]
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "reviewer": {
                    "enabled": True,
                    "budget_max": 3,
                    "sensitive_globs": ["runtime/**"],
                    "trivial_globs": ["**/*.md"],
                    "trivial_except_globs": ["docs/QUALITY.md"],
                },
            }
        ),
        encoding="utf-8",
    )
    assert review_main(["record", "--sha", head, "--findings", "2", "--context", "context", "--json"]) == 0
    assert review_main(["allow", "--force", "--context", "context", "--json"]) == 0
    # delta with sensitive path
    (tmp_path / "runtime").mkdir(exist_ok=True)
    (tmp_path / "runtime" / "z.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "runtime/z.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "z"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    delta = evaluate_delta(tmp_path, head, default_reviewer_config())
    assert delta["files"] >= 1
    assert review_main([]) == 2
    # missing agent src (local packages/shared without agents/ — no installed fallback write)
    (tmp_path / "packages" / "shared").mkdir(parents=True, exist_ok=True)
    assert pin_reviewer_agents(tmp_path, "context").get("skipped") == "missing-src"
    bare = tmp_path / "bare.md"
    bare.write_text("plain body\n", encoding="utf-8")
    assert _render_reviewer_agent(bare, "x") == "plain body\n"
    set_reviewer_options(tmp_path, effort="max", helper_model="composer-2")
    assert load_quality(tmp_path)["reviewer"]["effort"] == "max"


def test_render_and_pin_reviewer(tmp_path: Path, monkeypatch):
    _git_repo(tmp_path)
    ctx = tmp_path / "context"
    for p in (ctx / "tasks", ctx / "leases", tmp_path / "packages" / "shared" / "agents"):
        p.mkdir(parents=True, exist_ok=True)
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (tmp_path / "packages" / "shared" / "skills" / "navigate").mkdir(parents=True)
    (tmp_path / "packages" / "shared" / "skills" / "navigate" / "SKILL.md").write_text(
        "---\nname: navigate\n---\n", encoding="utf-8"
    )
    (tmp_path / "packages" / "shared" / "hooks" / "scripts").mkdir(parents=True)
    (tmp_path / "packages" / "shared" / "hooks" / "scripts" / "session_start.py").write_text(
        "print(1)\n", encoding="utf-8"
    )
    (tmp_path / "packages" / "shared" / "agents" / "reviewer.md").write_text(
        "---\nname: reviewer\nmodel: old\nreadonly: true\n---\nBody\n",
        encoding="utf-8",
    )
    (tmp_path / "templates" / "quality").mkdir(parents=True)
    (tmp_path / "templates" / "quality" / "pre-push").write_text(
        "#!/bin/sh\n# AGENTIZED:QUALITY\n", encoding="utf-8"
    )
    rendered = _render_reviewer_agent(
        tmp_path / "packages" / "shared" / "agents" / "reviewer.md", "claude-opus-4.5"
    )
    assert "model: claude-opus-4.5" in rendered
    assert "model: old" not in rendered
    monkeypatch.chdir(tmp_path)
    connect(tmp_path, context_rel="context", harnesses=["cursor"])
    q = load_quality(tmp_path)
    assert q["reviewer"]["budget_max"] == 3
    assert (ctx / "agents" / "reviewer.md").exists()
    assert (tmp_path / ".cursor" / "agents" / "reviewer.md").exists()
    assert "claude-opus-4.5" in (tmp_path / ".cursor" / "agents" / "reviewer.md").read_text(
        encoding="utf-8"
    )
    set_reviewer_options(tmp_path, model="gpt-5.4", budget_max=5)
    pin_reviewer_agents(tmp_path, "context")
    assert "gpt-5.4" in (tmp_path / ".cursor" / "agents" / "reviewer.md").read_text(encoding="utf-8")
    assert load_quality(tmp_path)["reviewer"]["budget_max"] == 5


def test_open_findings_allows_fix_pack_rereview(tmp_path: Path, monkeypatch):
    """Small non-sensitive delta still requests when open_findings > 0."""
    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "reviewer": {
                    "budget_max": 3,
                    "delta_lines": 500,
                    "sensitive_globs": ["runtime/**"],
                    "trivial_globs": [],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    head = status(tmp_path)["head"]
    record_review(tmp_path, head, findings=2, scope="task-a")
    # Tiny docs-only change — under delta_lines and outside sensitive_globs.
    (tmp_path / "NOTES.md").write_text("fix\n", encoding="utf-8")
    subprocess.run(["git", "add", "NOTES.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "tiny"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    allowed = allow_review(tmp_path, scope="task-a")
    assert allowed["ok"] is True
    assert allowed["action"] == "request"
    assert "open_findings=2" in allowed["message"]


def test_scope_isolates_budget(tmp_path: Path, monkeypatch):
    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps({"version": 1, "reviewer": {"budget_max": 1}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    head = status(tmp_path)["head"]
    record_review(tmp_path, head, findings=0, scope="task-old")
    # Exhausted / already reviewed for task-old; new scope still gets first pass.
    blocked = allow_review(tmp_path, scope="task-old")
    assert blocked["action"] in {"skip", "escalate"}
    fresh = allow_review(tmp_path, scope="task-new")
    assert fresh["ok"] is True
    assert fresh["action"] == "request"
    assert fresh["scope"] == "task-new"
    assert fresh["used"] == 0
    reset = reset_scope(tmp_path, scope="task-old")
    assert reset["used"] == 0
    assert load_state(tmp_path, scope="task-old")["watermark"] is None


def test_invalid_watermark_blocks_and_record_rejects(tmp_path: Path, monkeypatch):
    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps({"version": 1, "reviewer": {"budget_max": 3, "delta_lines": 1}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="invalid commit"):
        record_review(tmp_path, "not-a-commit", findings=0)
    # Plant a bogus watermark (simulates deleted/unreachable commit).
    save_state(
        tmp_path,
        {
            "used": 1,
            "budget_max": 3,
            "watermark": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "open_findings": 0,
            "history": [],
        },
        scope="default",
    )
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "x.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "runtime/x.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "code"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    blocked = allow_review(tmp_path)
    assert blocked["ok"] is False
    assert blocked["action"] == "blocked"
    assert "unavailable" in blocked["message"] or "cannot compare" in blocked["message"]


def test_unavailable_watermark_blocks_even_with_open_findings(
    tmp_path: Path, monkeypatch
):
    """Fix-pack path must not skip watermark validation when open_findings > 0."""
    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps({"version": 1, "reviewer": {"budget_max": 3, "delta_lines": 500}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    save_state(
        tmp_path,
        {
            "used": 1,
            "budget_max": 3,
            "watermark": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "open_findings": 1,
            "history": [],
        },
        scope="default",
    )
    (tmp_path / "NOTES.md").write_text("fix\n", encoding="utf-8")
    subprocess.run(["git", "add", "NOTES.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "tiny"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    blocked = allow_review(tmp_path)
    assert blocked["ok"] is False
    assert blocked["action"] == "blocked"
    assert blocked["open_findings"] == 1
    assert "unavailable" in blocked["message"] or "cannot compare" in blocked["message"]


def test_rename_into_sensitive_glob_requests_review(tmp_path: Path, monkeypatch):
    """Rename display paths must not hide a move into a sensitive directory."""
    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "reviewer": {
                    "budget_max": 3,
                    "delta_lines": 5000,
                    "sensitive_globs": [".github/workflows/**"],
                    "trivial_globs": ["**/*.yml"],
                },
            }
        ),
        encoding="utf-8",
    )
    disabled = tmp_path / ".github" / "disabled"
    disabled.mkdir(parents=True)
    (disabled / "deploy.yml").write_text("name: deploy\non: push\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".github/disabled/deploy.yml"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "disabled"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(tmp_path)
    head = status(tmp_path)["head"]
    record_review(tmp_path, head, findings=0)

    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    subprocess.run(
        ["git", "mv", ".github/disabled/deploy.yml", ".github/workflows/deploy.yml"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "enable wf"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Confirm git still emits brace rename form for this move.
    numstat = subprocess.run(
        ["git", "diff", "--numstat", "--find-renames", head],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "=>" in numstat or "workflows/deploy.yml" in numstat

    delta = evaluate_delta(tmp_path, head, load_quality_reviewer(tmp_path))
    assert ".github/workflows/deploy.yml" in delta["sensitive"]
    assert delta["request"] is True

    allowed = allow_review(tmp_path)
    assert allowed["ok"] is True
    assert allowed["action"] == "request"


def load_quality_reviewer(root: Path) -> dict:
    from agentized.review_budget import reviewer_config

    return reviewer_config(root)


def test_quoted_non_ascii_sensitive_path_requests_review(tmp_path: Path, monkeypatch):
    """Git-quoted UTF-8 paths under sensitive globs must still request review."""
    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "reviewer": {
                    "budget_max": 3,
                    "delta_lines": 5000,
                    "sensitive_globs": [".github/workflows/**"],
                    "trivial_globs": [],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    head = status(tmp_path)["head"]
    record_review(tmp_path, head, findings=0)
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "déploy.yml").write_text("name: d\non: push\n", encoding="utf-8")
    subprocess.run(["git", "add", ".github/workflows/déploy.yml"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "wf"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Without -z, Git quotes the path; our parser must still see the sensitive file.
    plain = subprocess.run(
        ["git", "diff", "--numstat", head],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "\\" in plain or "déploy" in plain or "workflows" in plain

    delta = evaluate_delta(tmp_path, head, load_quality_reviewer(tmp_path))
    assert any(p.endswith("déploy.yml") for p in delta["sensitive"])
    assert delta["request"] is True
    allowed = allow_review(tmp_path)
    assert allowed["ok"] is True
    assert allowed["action"] == "request"


def test_binary_under_sensitive_glob_requests_review(tmp_path: Path, monkeypatch):
    """Binary --numstat rows (-\\t-) must still match sensitive globs."""
    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "reviewer": {
                    "budget_max": 3,
                    "delta_lines": 5000,
                    "sensitive_globs": ["runtime/**"],
                    "trivial_globs": [],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    head = status(tmp_path)["head"]
    record_review(tmp_path, head, findings=0)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "payload.bin").write_bytes(b"\x00\x01\x02\xff")
    subprocess.run(["git", "add", "runtime/payload.bin"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "bin"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    numstat = subprocess.run(
        ["git", "diff", "--numstat", head, "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "-\t-\truntime/payload.bin" in numstat

    delta = evaluate_delta(tmp_path, head, load_quality_reviewer(tmp_path))
    assert "runtime/payload.bin" in delta["sensitive"]
    assert delta["request"] is True
    allowed = allow_review(tmp_path)
    assert allowed["ok"] is True
    assert allowed["action"] == "request"


def test_dirty_worktree_cannot_hide_head_sensitive_delta(tmp_path: Path, monkeypatch):
    """Diff watermark..HEAD, not watermark..worktree, so dirty checkouts can't skip."""
    _git_repo(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "reviewer": {
                    "budget_max": 3,
                    "delta_lines": 5000,
                    "sensitive_globs": ["runtime/**"],
                    "trivial_globs": [],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    # Watermark on a clean tree that already has runtime/x.py baseline content.
    (tmp_path / "runtime").mkdir()
    baseline = "print('baseline')\n"
    (tmp_path / "runtime" / "x.py").write_text(baseline, encoding="utf-8")
    subprocess.run(["git", "add", "runtime/x.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    watermark = status(tmp_path)["head"]
    record_review(tmp_path, watermark, findings=0)

    # Commit a sensitive change on HEAD.
    (tmp_path / "runtime" / "x.py").write_text("print('reviewed-needed')\n", encoding="utf-8")
    subprocess.run(["git", "add", "runtime/x.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "change"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Dirty worktree: restore file contents to watermark text (hides vs worktree).
    (tmp_path / "runtime" / "x.py").write_text(baseline, encoding="utf-8")
    dirty = subprocess.run(
        ["git", "diff", "--numstat", "--find-renames", watermark],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert dirty.strip() == ""  # worktree looks unchanged vs watermark
    allowed = allow_review(tmp_path)
    assert allowed["ok"] is True
    assert allowed["action"] == "request"
    assert "runtime/x.py" in (allowed.get("delta") or {}).get("sensitive", [])
