"""AGE-85: process size exempts connect bootstrap paths only (no generic bypass)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from agentized.process_size import (
    EMPTY_TREE,
    diff_insertions_excluding_bootstrap,
    head_has_connect_managed,
    is_connect_bootstrap_path,
    parse_numstat_excluding_bootstrap,
    ref_exists,
    size_check,
)

PC = '{"reviewable_lines": 1500, "warn_at_pct": 75}\n'
TAIL = "(warn ≥1125 = 75.0% of 1500; over >1500; ≤1500 OK). See docs/process-control.md."


BOOTSTRAP = [
    "AGENTS.md",
    "./AGENTS.md",
    "context/skills/navigate/SKILL.md",
    ".githooks/pre-push",
    "./.githooks/pre-push",
    ".githooks\\pre-push",
    ".github/workflows/ci.yml",
    ".cursor/hooks.json",
    ".claude/settings.json",
    ".codex/a",
    ".agents/a",
    ".agentized/a",
    "context\\quality.json",
]
USER = [
    "githooks/pre-push",
    "src/app.py",
    "README.md",
    ".github/ci.yml",
    "AGENTS.mdx",
    "docs/AGENTS.md",
    "contexts/x",
    ".githooks",
    "x/.cursor/a",
]


def test_bootstrap_paths_exact_classification():
    got = {p: is_connect_bootstrap_path(p) for p in BOOTSTRAP + USER}
    assert got == {**dict.fromkeys(BOOTSTRAP, True), **dict.fromkeys(USER, False)}


def test_bootstrap_path_custom_context():
    got = (
        is_connect_bootstrap_path("a/b/x.md", "a/b"),
        is_connect_bootstrap_path("context/x.md", "a/b"),
    )
    assert got == (True, False)


def test_parse_numstat_excluding_bootstrap_exact():
    stdout = (
        "7\t0\tAGENTS.md copy.txt\n100\t0\tctx/q.json\n3\t1\tsrc/a.py\n\nshort\n"
        "-\t-\tbin/blob\n40\t0\tcontext/k.md\n"
    )
    assert parse_numstat_excluding_bootstrap(stdout, "ctx") == 50
    assert parse_numstat_excluding_bootstrap(stdout) == 110


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(root: Path, files: dict[str, str]) -> str:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "--allow-empty", "-m", "c")
    return _git(root, "rev-parse", "HEAD")


def _repo(tmp_path: Path, base: dict[str, str] | None) -> Path:
    """Repo with optional base commit pinned as origin/main (None → no origin/main)."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    if base is not None:
        _git(root, "update-ref", "refs/remotes/origin/main", _commit(root, base))
    return root


MANAGED = {"context/.agentized/managed.json": "{}\n", "context/process-control.json": PC}


@pytest.fixture(autouse=True)
def _no_env_base(monkeypatch):
    monkeypatch.delenv("PROCESS_BASE", raising=False)


def test_connect_baseline_excludes_bootstrap(tmp_path: Path):
    root = _repo(tmp_path, {"README": "base\n"})
    _commit(root, {**MANAGED, "context/skills/big.md": "x\n" * 2000, "AGENTS.md": "# a\n"})
    _commit(root, {"src/app.py": "V = 1\n"})
    result = size_check(root, base_ref="origin/main")
    assert result["ok"] is True
    assert result["insertions"] == 1
    assert result["message"] == (
        "process-control: PR size 1 insertions vs origin/main connect-baseline "
        f"(bootstrap paths excluded) {TAIL}"
    )


def test_connect_baseline_user_bulk_still_blocks(tmp_path: Path):
    root = _repo(tmp_path, {"README": "base\n"})
    _commit(root, {**MANAGED, "src/huge.py": "x\n" * 1600})
    result = size_check(root, base_ref="origin/main")
    assert (result["ok"], result["level"], result["insertions"]) == (False, "over", 1600)


def test_diff_excluding_vs_empty_tree(tmp_path: Path):
    root = _repo(tmp_path, None)
    _commit(root, {"context/.agentized/managed.json": "{}\n", "src/a.py": "a=1\n"})
    assert diff_insertions_excluding_bootstrap(root, EMPTY_TREE, "context") == 1


def test_first_push_without_origin_main(tmp_path: Path):
    root = _repo(tmp_path, None)
    _commit(root, {**MANAGED, "context/skills/big.md": "x\n" * 2000, "src/a.py": "a\nb\n"})
    result = size_check(root)
    assert result == {
        "ok": True,
        "level": "ok",
        "insertions": 2,
        "limit": 1500,
        "warn_at": 1125,
        "base": "origin/main",
        "message": (
            "process-control: PR size 2 insertions vs origin/main connect-baseline "
            f"(no origin/main; bootstrap paths excluded) {TAIL}"
        ),
    }
    assert size_check(root, base_ref="origin/main") == result


def test_first_push_custom_context(tmp_path: Path):
    root = _repo(tmp_path, None)
    _commit(
        root,
        {
            "ctx/.agentized/managed.json": "{}\n",
            "ctx/process-control.json": PC,
            "ctx/big.md": "x\n" * 40,
            "context/user.md": "u\n" * 3,
        },
    )
    assert size_check(root, context_rel="ctx")["insertions"] == 3


def test_first_push_unmanaged_fails_closed(tmp_path: Path):
    root = _repo(tmp_path, None)
    _commit(root, {"context/process-control.json": PC, "src/a.py": "a\n"})
    result = size_check(root)
    assert (result["ok"], result["level"]) == (False, "error")
    assert result["message"].startswith("process-control: origin/main unavailable")


def test_first_push_other_missing_base_fails_closed(tmp_path: Path):
    root = _repo(tmp_path, None)
    _commit(root, {**MANAGED, "src/a.py": "a\n"})
    result = size_check(root, base_ref="feature")
    assert (result["ok"], result["level"], result["base"]) == (False, "error", "feature")


def test_base_already_managed_counts_everything(tmp_path: Path):
    root = _repo(tmp_path, MANAGED)
    _commit(root, {"context/skills/s.md": "x\n" * 30})
    result = size_check(root)
    assert result["insertions"] == 30
    assert result["message"] == f"process-control: PR size 30 insertions vs origin/main {TAIL}"


def test_custom_context_baseline(tmp_path: Path):
    root = _repo(tmp_path, {"README": "r\n"})
    _commit(
        root,
        {
            "ctx/.agentized/managed.json": "{}\n",
            "ctx/process-control.json": PC,
            "ctx/big.md": "x\n" * 40,
            "context/user.md": "u\n" * 5,
        },
    )
    result = size_check(root, context_rel="ctx")
    assert result["insertions"] == 5
    assert result["message"] == (
        "process-control: PR size 5 insertions vs origin/main connect-baseline "
        f"(bootstrap paths excluded) {TAIL}"
    )


def test_ref_exists(tmp_path: Path):
    root = _repo(tmp_path, None)
    _commit(root, {"a": "a\n"})
    got = [ref_exists(root, r) for r in ("HEAD", "origin/main", "HEAD..HEAD")]
    assert got == [True, False, False]


def test_untracked_managed_json_grants_no_exemption(tmp_path: Path):
    root = _repo(tmp_path, {"README": "base\n"})
    _commit(root, {"context/process-control.json": PC, "context/skills/big.md": "x\n" * 2000})
    (root / "context" / ".agentized").mkdir()
    (root / "context" / ".agentized" / "managed.json").write_text("{}\n", encoding="utf-8")
    result = size_check(root, base_ref="origin/main")
    assert result == {
        "ok": False,
        "level": "over",
        "insertions": 2001,
        "limit": 1500,
        "warn_at": 1125,
        "base": "origin/main",
        "message": (
            "process-control: PR size 2001 insertions vs origin/main "
            "(warn ≥1125 = 75.0% of 1500; over >1500; ≤1500 OK). "
            "See docs/process-control.md."
        ),
    }


def test_untracked_managed_json_first_push_fails_closed(tmp_path: Path):
    root = _repo(tmp_path, None)
    _commit(root, {"context/process-control.json": PC, "src/a.py": "a\n"})
    (root / "context" / ".agentized").mkdir()
    (root / "context" / ".agentized" / "managed.json").write_text("{}\n", encoding="utf-8")
    result = size_check(root)
    assert (result["ok"], result["level"]) == (False, "error")
    assert result["message"].startswith("process-control: origin/main unavailable")


def test_head_has_connect_managed_reads_committed_tree(tmp_path: Path):
    root = _repo(tmp_path, None)
    _commit(root, {"README": "r\n"})
    managed = root / "context" / ".agentized" / "managed.json"
    managed.parent.mkdir(parents=True)
    managed.write_text("{}\n", encoding="utf-8")
    untracked = head_has_connect_managed(root)
    _git(root, "add", "context/.agentized/managed.json")
    staged = head_has_connect_managed(root)
    _git(root, "commit", "-qm", "managed")
    committed = head_has_connect_managed(root)
    assert (untracked, staged, committed) == (False, False, True)
    assert head_has_connect_managed(root, "other") is False
