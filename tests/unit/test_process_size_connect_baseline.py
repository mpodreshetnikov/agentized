"""AGE-85: process size exempts connect bootstrap paths only (no generic bypass)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentized.process_size import (
    EMPTY_TREE,
    diff_insertions_excluding_bootstrap,
    is_connect_bootstrap_path,
    parse_numstat_excluding_bootstrap,
    ref_exists,
    size_check,
)


def test_is_connect_bootstrap_path_prefixes():
    assert is_connect_bootstrap_path("AGENTS.md")
    assert is_connect_bootstrap_path("context/quality.json")
    assert is_connect_bootstrap_path("context/skills/navigate/SKILL.md")
    assert is_connect_bootstrap_path(".githooks/pre-push")
    assert is_connect_bootstrap_path("./.githooks/pre-push")
    assert is_connect_bootstrap_path(".cursor/hooks.json")
    assert is_connect_bootstrap_path(".claude/settings.json")
    # Regression: str.lstrip("./") would strip leading dots from ".githooks".
    assert not is_connect_bootstrap_path("githooks/pre-push")
    assert not is_connect_bootstrap_path("src/app.py")
    assert not is_connect_bootstrap_path("README.md")
    assert is_connect_bootstrap_path("ctx/quality.json", "ctx")
    assert not is_connect_bootstrap_path("context/quality.json", "ctx")


def test_parse_numstat_excluding_bootstrap():
    stdout = "100\t0\tcontext/quality.json\n50\t0\tsrc/app.py\n-\t-\tbin/blob\n10\t0\tAGENTS.md\n"
    assert parse_numstat_excluding_bootstrap(stdout) == 50


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _commit(root: Path, msg: str) -> None:
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", msg)


def test_size_check_connect_baseline_excludes_bootstrap(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "README").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README")
    _commit(root, "base")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git(root, "update-ref", "refs/remotes/origin/main", sha)

    managed = root / "context" / ".agentized"
    managed.mkdir(parents=True)
    (managed / "managed.json").write_text('{"version":1,"files":{}}\n', encoding="utf-8")
    (root / "context" / "quality.json").write_text("{}\n", encoding="utf-8")
    # Large bootstrap-looking tree (would exceed 1500 if counted).
    big = "x\n" * 2000
    (root / "context" / "skills").mkdir(parents=True)
    (root / "context" / "skills" / "big.md").write_text(big, encoding="utf-8")
    (root / "AGENTS.md").write_text("# agentized\n", encoding="utf-8")
    # Non-bootstrap user file under limit.
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("V = 1\n", encoding="utf-8")
    (root / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 1500, "warn_at_pct": 75}\n', encoding="utf-8"
    )
    _git(root, "add", "-A")
    _commit(root, "connect")

    result = size_check(root, base_ref="origin/main")
    assert result["ok"] is True
    assert result["insertions"] < 50
    assert "connect-baseline" in result["message"]


def test_size_check_negative_user_bulk_still_blocks(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "README").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README")
    _commit(root, "base")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git(root, "update-ref", "refs/remotes/origin/main", sha)

    managed = root / "context" / ".agentized"
    managed.mkdir(parents=True)
    (managed / "managed.json").write_text('{"version":1,"files":{}}\n', encoding="utf-8")
    (root / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 1500, "warn_at_pct": 75}\n', encoding="utf-8"
    )
    (root / "src").mkdir()
    (root / "src" / "huge.py").write_text("x\n" * 1600, encoding="utf-8")
    _git(root, "add", "-A")
    _commit(root, "connect+huge")

    result = size_check(root, base_ref="origin/main")
    assert result["ok"] is False
    assert result["level"] == "over"
    assert result["insertions"] > 1500


def test_diff_excluding_vs_empty_tree(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    managed = root / "context" / ".agentized"
    managed.mkdir(parents=True)
    (managed / "managed.json").write_text("{}\n", encoding="utf-8")
    (root / "src" / "a.py").parent.mkdir(parents=True)
    (root / "src" / "a.py").write_text("a=1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _commit(root, "c")
    n = diff_insertions_excluding_bootstrap(root, EMPTY_TREE, "context")
    assert n == 1


def _first_push_repo(tmp_path: Path, *, managed: bool) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    if managed:
        (root / "context" / ".agentized").mkdir(parents=True)
        (root / "context" / ".agentized" / "managed.json").write_text("{}\n", encoding="utf-8")
        (root / "context" / "skills").mkdir(parents=True)
        (root / "context" / "skills" / "big.md").write_text("x\n" * 2000, encoding="utf-8")
    (root / "context").mkdir(exist_ok=True)
    (root / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 1500, "warn_at_pct": 75}\n', encoding="utf-8"
    )
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _commit(root, "connect")
    return root


def test_size_check_first_push_without_origin_main(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    root = _first_push_repo(tmp_path, managed=True)
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
            "(no origin/main; bootstrap paths excluded) (warn ≥1125 = 75.0% of 1500; "
            "over >1500; ≤1500 OK). See docs/process-control.md."
        ),
    }
    assert size_check(root, base_ref="origin/main") == result


def test_size_check_first_push_unmanaged_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    root = _first_push_repo(tmp_path, managed=False)
    result = size_check(root)
    assert result["ok"] is False
    assert result["level"] == "error"
    assert result["message"].startswith("process-control: origin/main unavailable")


def test_size_check_other_missing_base_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    root = _first_push_repo(tmp_path, managed=True)
    result = size_check(root, base_ref="feature")
    assert result["ok"] is False
    assert result["level"] == "error"
    assert result["base"] == "feature"


def test_ref_exists(tmp_path: Path):
    root = _first_push_repo(tmp_path, managed=False)
    assert ref_exists(root, "HEAD") is True
    assert ref_exists(root, "origin/main") is False
