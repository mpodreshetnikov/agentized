"""AGE-95: pre-push reads git's ref list from stdin before any other step."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# mutmut copies tests under mutants/ without hooks/templates — resolve the real source tree.
_TEST_ROOT = Path(__file__).resolve().parents[2]
ROOT = _TEST_ROOT.parent if _TEST_ROOT.name == "mutants" else _TEST_ROOT
HOOKS = (ROOT / ".githooks" / "pre-push", ROOT / "templates" / "quality" / "pre-push")

LOCAL = "a" * 40
REMOTE = "b" * 40
FAKE_CLI = """#!/usr/bin/env bash
echo "cli $*" >> "$LOG"
cat >/dev/null
"""
FAKE_MECHANICAL = """#!/usr/bin/env bash
echo "mechanical stdin=$(cat | wc -c | tr -d ' ')" >> "$LOG"
"""


def _install(tmp_path: Path, hook: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "tests").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for name, body in (("bin/agentized", FAKE_CLI), ("tests/test_mechanical.sh", FAKE_MECHANICAL)):
        path = repo / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    shutil.copy(hook, repo / "pre-push")
    return repo


def _push(repo: Path, refs: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    log = repo / "log.txt"
    log.write_text("", encoding="utf-8")
    proc = subprocess.run(
        ["bash", str(repo / "pre-push"), "origin", "git@example.com:r.git"],
        cwd=repo,
        input=refs,
        env={**os.environ, "LOG": str(log)},
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("hook", HOOKS, ids=["dogfood", "template"])
def test_stdin_refs_survive_stdin_reading_steps_and_merge_gate_runs(tmp_path, hook):
    repo = _install(tmp_path, hook)
    refs = f"refs/heads/x {LOCAL} refs/heads/x {REMOTE}\n"
    proc, log = _push(repo, refs)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert log[0] == "mechanical stdin=0"
    merge = f"cli process agent-merge --remote {REMOTE} --local {LOCAL}"
    assert log.count(merge) == 1
    assert log.index(merge) > 0
    assert log[-1] == "cli quality check"


@pytest.mark.parametrize("hook", HOOKS, ids=["dogfood", "template"])
def test_every_pushed_ref_is_merge_gated(tmp_path, hook):
    repo = _install(tmp_path, hook)
    other_local, other_remote = "c" * 40, "d" * 40
    refs = f"refs/heads/x {LOCAL} refs/heads/x {REMOTE}\nrefs/heads/y {other_local} refs/heads/y {other_remote}\n"
    proc, log = _push(repo, refs)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    merges = [line for line in log if "process agent-merge" in line]
    assert merges == [
        f"cli process agent-merge --remote {REMOTE} --local {LOCAL}",
        f"cli process agent-merge --remote {other_remote} --local {other_local}",
    ]


@pytest.mark.parametrize("hook", HOOKS, ids=["dogfood", "template"])
def test_no_refs_means_no_merge_gate_call(tmp_path, hook):
    repo = _install(tmp_path, hook)
    proc, log = _push(repo, "")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not [line for line in log if "agent-merge" in line]
    assert log[0] == "mechanical stdin=0"


@pytest.mark.parametrize("hook", HOOKS, ids=["dogfood", "template"])
def test_failing_merge_gate_blocks_the_push(tmp_path, hook):
    repo = _install(tmp_path, hook)
    cli = repo / "bin" / "agentized"
    cli.write_text(
        FAKE_CLI + 'if [[ "$*" == *agent-merge* ]]; then exit 1; fi\n',
        encoding="utf-8",
    )
    proc, log = _push(repo, f"refs/heads/x {LOCAL} refs/heads/x {REMOTE}\n")
    assert proc.returncode == 1
    assert "cli quality check" not in log
