"""AGE-68 A5: mutation oracles for the tree helpers shared by the install_* paths.

Tests-only; no runtime change. Targets survivors on ``_copy_tree``,
``_managed_copy_tree``, ``_refresh_local_plugin`` and ``_local_packages``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agentized import connect as connect_mod
from agentized.connect import (
    _copy_tree,
    _local_packages,
    _managed_copy_tree,
    _refresh_local_plugin,
)


def _seed_tree(src: Path) -> None:
    (src / "empty_dir").mkdir(parents=True)
    (src / "a" / "b").mkdir(parents=True)
    (src / "top.txt").write_text("top\n", encoding="utf-8")
    (src / "a" / "mid.txt").write_text("mid\n", encoding="utf-8")
    (src / "a" / "b" / "leaf.txt").write_text("leaf\n", encoding="utf-8")


def test_copy_tree_copies_files_past_directories_and_returns_exact_paths(tmp_path: Path):
    """Kill ``continue``→``break`` on dirs and ``append(None)`` / ``str(None)`` results."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _seed_tree(src)
    copied = _copy_tree(src, dst)
    assert copied == [
        str(dst / "a" / "b" / "leaf.txt"),
        str(dst / "a" / "mid.txt"),
        str(dst / "top.txt"),
    ]
    assert (dst / "a" / "b" / "leaf.txt").read_text(encoding="utf-8") == "leaf\n"
    assert (dst / "a" / "mid.txt").read_text(encoding="utf-8") == "mid\n"
    assert (dst / "top.txt").read_text(encoding="utf-8") == "top\n"
    assert not (dst / "empty_dir").exists()


def test_managed_copy_tree_forwards_exact_args_to_managed_copy_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill context_rel/force/manifest None-or-omit mutants and the ``force`` default."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "n").mkdir(parents=True)
    (src / "n" / "f.txt").write_text("x\n", encoding="utf-8")
    calls: list[tuple[tuple, dict]] = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return "created"

    monkeypatch.setattr(connect_mod, "managed_copy_file", fake)
    manifest: dict[str, Any] = {"mark": 1}
    expected_args = (tmp_path, "ctx", src / "n" / "f.txt", dst / "n" / "f.txt")
    _managed_copy_tree(tmp_path, "ctx", src, dst, manifest=manifest)
    assert calls == [(expected_args, {"force": False, "manifest": manifest})]
    calls.clear()
    _managed_copy_tree(tmp_path, "ctx", src, dst, force=True, manifest=manifest)
    assert calls == [(expected_args, {"force": True, "manifest": manifest})]


def test_managed_copy_tree_groups_statuses_including_unknown_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill ``setdefault(status, [])`` default mutants: an unseen status gets a fresh list."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "f.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(connect_mod, "managed_copy_file", lambda *a, **k: "novel_status")
    result = _managed_copy_tree(tmp_path, "ctx", src, dst)
    assert result == {
        "created": [],
        "updated": [],
        "unchanged": [],
        "skipped_user": [],
        "bootstrapped": [],
        "novel_status": [str(dst / "f.txt")],
    }


def _seed_local_plugin(root: Path) -> Path:
    scripts = root / "packages" / "shared" / "hooks" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "guard.py").write_text("print('guard')\n", encoding="utf-8")
    plugin = root / "packages" / "agentized-demo"
    plugin.mkdir()
    skills = root / "context" / "skills" / "s"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# s\n", encoding="utf-8")
    return plugin


def test_refresh_local_plugin_writes_skills_and_scripts_dirs(tmp_path: Path):
    """Kill the ``skills`` / ``scripts`` destination-name XX/CASE mutants and exact return."""
    plugin = _seed_local_plugin(tmp_path)
    result = _refresh_local_plugin(tmp_path, "agentized-demo", tmp_path / "context" / "skills")
    assert result == str(plugin)
    assert len([p for p in plugin.rglob("*") if p.is_file()]) == 2
    assert (plugin / "skills" / "s" / "SKILL.md").read_text(encoding="utf-8") == "# s\n"
    assert (plugin / "scripts" / "guard.py").read_text(encoding="utf-8") == "print('guard')\n"


def test_local_packages_requires_both_packages_and_shared(tmp_path: Path):
    """Kill ``and``→``or``: ``packages/`` without ``shared/`` is not a local packages tree."""
    assert _local_packages(tmp_path) is None
    (tmp_path / "packages").mkdir()
    assert _local_packages(tmp_path) is None
    (tmp_path / "packages" / "shared").mkdir()
    assert _local_packages(tmp_path) == tmp_path / "packages"
