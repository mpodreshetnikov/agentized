"""AGE-76 REJECT r3/r4: connect+new/ready flows for tip hygiene (not full CI scripts)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from agentized.connect import connect
from agentized.task_schema import PLACEHOLDER_PARENT, rebuild_task_index
from agentized.tip_hygiene import MSG_TIP_INDEX, validate_index_freshness

_TEST_ROOT = Path(__file__).resolve().parents[2]
# mutmut copies tests under mutants/ without templates/ — resolve source tree.
ROOT = _TEST_ROOT.parent if _TEST_ROOT.name == "mutants" else _TEST_ROOT
TEMPLATE_CI = ROOT / "templates" / "quality" / "ci.yml"
TEMPLATE_PRE_PUSH = ROOT / "templates" / "quality" / "pre-push"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _cli(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    full_env["PYTHONPATH"] = str(ROOT / "runtime") + (
        os.pathsep + full_env["PYTHONPATH"] if full_env.get("PYTHONPATH") else ""
    )
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(ROOT / "runtime" / "agentized_cli.py"), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_after_connect_template_files_omit_tip_hygiene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(b) empty git → connect → commit: template files omit tip hygiene; check OK.

    Not a real pre-push/CI script run — only asserts template text + lightweight
    ``process size`` / ``check``. Hand INDEX still fails tip hygiene (AGE-68 seed).
    """
    repo = tmp_path / "fresh"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    # Empty root commit as PR/process base (mirrors CI PROCESS_BASE sha).
    _git(repo, "commit", "--allow-empty", "-m", "root")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # process size requires origin/main ancestor check even with PROCESS_BASE.
    _git(repo, "branch", "-M", "main")
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    monkeypatch.chdir(repo)

    connect(repo, context_rel="context", harnesses=["cursor"], coverage_pct=80)
    # Install template quality hooks/ci as connect would for consumers.
    githooks = repo / ".githooks"
    githooks.mkdir(exist_ok=True)
    shutil.copy(TEMPLATE_PRE_PUSH, githooks / "pre-push")
    (githooks / "pre-push").chmod(0o755)
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATE_CI, workflows / "ci.yml")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "connect skeleton")
    tip = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # After connect lands on main, size vs that tip is 0 (first-push size is out of scope).
    _git(repo, "update-ref", "refs/remotes/origin/main", tip)

    tmpl_pre = (githooks / "pre-push").read_text(encoding="utf-8")
    tmpl_ci = (workflows / "ci.yml").read_text(encoding="utf-8")
    assert "tasks-validate" not in tmpl_pre
    assert "tasks-validate" not in tmpl_ci

    # Document the gap: hand INDEX ≠ rebuild (AGE-68 seed) — would red tip hygiene.
    idx = validate_index_freshness(repo / "context" / "tasks")
    assert idx.ok is False
    assert MSG_TIP_INDEX in idx.errors

    # Lightweight gates templates also run (not full pre-push/CI).
    size = _cli(repo, "process", "size", env={"PROCESS_BASE": tip})
    assert size.returncode == 0, size.stderr
    check = _cli(repo, "check")
    assert check.returncode == 0, check.stderr


def test_new_claim_ready_tasks_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """connect → new(--value) → claim → ready --pr → tasks-validate OK under GITHUB_REF."""
    repo = tmp_path / "flow"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    monkeypatch.chdir(repo)

    connect(repo, context_rel="context", harnesses=["cursor"], coverage_pct=80)
    # Fresh INDEX via rebuild so tip hygiene can pass after ready (AGE-68 seed pending).
    tasks = repo / "context" / "tasks"
    (tasks / "INDEX.md").write_text(rebuild_task_index(tasks), encoding="utf-8")
    leases = repo / "context" / "leases"
    from agentized.leases import rebuild_lease_index

    (leases / "INDEX.md").write_text(rebuild_lease_index(leases), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "connect + fresh index")

    missing = _cli(repo, "new", "--title", "No value", "--yes")
    assert missing.returncode == 2
    assert "the following arguments are required: --value" in (missing.stderr + missing.stdout)

    created = _cli(
        repo,
        "new",
        "--title",
        "Ready flow",
        "--value",
        "Prove new→claim→ready tip hygiene",
        "--yes",
    )
    assert created.returncode == 0, created.stderr
    tid = next(
        ln.split(":", 1)[1].strip() for ln in created.stdout.splitlines() if ln.startswith("id:")
    )
    body = (tasks / f"{tid}.md").read_text(encoding="utf-8")
    assert "родитель: _(пусто)_" in body.splitlines()
    assert f"родитель: {PLACEHOLDER_PARENT}" not in body.splitlines()
    assert "Ценность: Prove new→claim→ready tip hygiene" in body.splitlines()

    claim = _cli(repo, "claim", tid, "--owner", "e2e-worker")
    assert claim.returncode == 0, claim.stderr

    ready = _cli(
        repo,
        "ready",
        tid,
        "--review-note",
        "e2e ready note",
        "--pr",
        "#1",
    )
    assert ready.returncode == 0, ready.stderr
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "ready tip")

    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REF": "refs/pull/1/merge",
    }
    validate = _cli(repo, "tasks-validate", "--pr", "#1", "--base", "HEAD~1", env=env)
    assert validate.returncode == 0, validate.stderr + validate.stdout


def test_new_requires_value_and_defaults_empty_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "context" / "tasks").mkdir(parents=True)
    (tmp_path / "context" / "tasks" / "INDEX.md").write_text(
        rebuild_task_index(tmp_path / "context" / "tasks"), encoding="utf-8"
    )
    # Minimal git root for find_repo_root
    _git(tmp_path, "init")

    bad = _cli(tmp_path, "new", "--title", "x", "--yes")
    assert bad.returncode == 2
    assert "the following arguments are required: --value" in (bad.stderr + bad.stdout)

    ok = _cli(
        tmp_path,
        "new",
        "--title",
        "y",
        "--value",
        "Business value line",
        "--yes",
    )
    assert ok.returncode == 0, ok.stderr
    tid = next(ln.split(":", 1)[1].strip() for ln in ok.stdout.splitlines() if ln.startswith("id:"))
    text = (tmp_path / "context" / "tasks" / f"{tid}.md").read_text(encoding="utf-8")
    assert "родитель: _(пусто)_" in text.splitlines()
    assert "Ценность: Business value line" in text.splitlines()
