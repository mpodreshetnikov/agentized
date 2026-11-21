"""AGE-68 A2: mutation oracles for connect hook-merge helpers.

Tests-only; no runtime change. Target survivors on:
``ensure_githooks_path``, ``_pin_hook_scripts``, ``_safe_install_template``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agentized.connect import (
    QUALITY_MARKER,
    _pin_hook_scripts,
    _safe_install_template,
    ensure_githooks_path,
)

# ---------------------------------------------------------------------------
# _pin_hook_scripts
# ---------------------------------------------------------------------------


def _seed_shared_hooks(root: Path, body: str = "shared-hook\n") -> Path:
    scripts = root / "packages" / "shared" / "hooks" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "session_start.py").write_text(body, encoding="utf-8")
    return scripts


def _seed_context_hooks(root: Path, body: str = "context-hook\n") -> Path:
    scripts = root / "context" / "hooks" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "session_start.py").write_text(body, encoding="utf-8")
    return scripts


def test_pin_prefers_context_hooks_over_shared(tmp_path: Path):
    """Kill hooks/scripts string mutants + inverted ``is_dir`` (use shared)."""
    _seed_shared_hooks(tmp_path, "FROM-SHARED\n")
    _seed_context_hooks(tmp_path, "FROM-CONTEXT\n")
    dest = tmp_path / ".cursor" / "hooks"
    copied = _pin_hook_scripts(tmp_path, "context", dest)
    assert copied == [str(dest / "session_start.py")]
    assert (dest / "session_start.py").read_text(encoding="utf-8") == "FROM-CONTEXT\n"


def test_pin_falls_back_to_shared_when_context_hooks_missing(tmp_path: Path):
    """Kill ``src_dir = None`` / ``_shared_hook_scripts(None)`` on missing context dir."""
    _seed_shared_hooks(tmp_path, "FALLBACK-SHARED\n")
    (tmp_path / "context").mkdir()
    dest = tmp_path / "out-hooks"
    copied = _pin_hook_scripts(tmp_path, "context", dest)
    assert copied == [str(dest / "session_start.py")]
    assert (dest / "session_start.py").read_text(encoding="utf-8") == "FALLBACK-SHARED\n"


def test_pin_mkdir_parents_true_for_nested_dest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill ``parents=True`` → False/None/omit on dest.mkdir."""
    _seed_context_hooks(tmp_path)
    seen: list[dict] = []
    real = Path.mkdir

    def wrapped(self: Path, *args, **kwargs):
        if "hooks-nested" in self.parts:
            seen.append(dict(kwargs))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", wrapped)
    dest = tmp_path / "deep" / "hooks-nested" / "hooks"
    _pin_hook_scripts(tmp_path, "context", dest)
    assert any(s.get("parents") is True for s in seen)
    assert dest.is_dir()


def test_pin_mkdir_exist_ok_when_dest_exists(tmp_path: Path):
    """Kill ``exist_ok=True`` → False when dest already exists."""
    _seed_context_hooks(tmp_path)
    dest = tmp_path / "hooks-dest"
    dest.mkdir()
    copied = _pin_hook_scripts(tmp_path, "context", dest)
    assert (dest / "session_start.py").is_file()
    assert copied == [str(dest / "session_start.py")]


def test_pin_chmod_sets_all_execute_bits(tmp_path: Path):
    """Kill ``| 0o111`` → ``| 74`` (and similar) on copied hook scripts."""
    _seed_context_hooks(tmp_path)
    dest = tmp_path / "hooks-dest"
    _pin_hook_scripts(tmp_path, "context", dest)
    mode = (dest / "session_start.py").stat().st_mode
    assert mode & 0o111 == 0o111


def test_pin_return_paths_are_str_not_none(tmp_path: Path):
    """Kill ``copied.append(str(target))`` → ``None`` / ``str(None)``."""
    _seed_context_hooks(tmp_path)
    dest = tmp_path / "hooks-dest"
    copied = _pin_hook_scripts(tmp_path, "context", dest)
    assert len(copied) == 1
    assert copied[0] == str(dest / "session_start.py")


def test_pin_only_copies_py_sorted(tmp_path: Path):
    """Kill glob / sorted drift: non-.py ignored; order stable."""
    scripts = _seed_context_hooks(tmp_path)
    (scripts / "zzz.py").write_text("z\n", encoding="utf-8")
    (scripts / "aaa.py").write_text("a\n", encoding="utf-8")
    (scripts / "skip.txt").write_text("nope\n", encoding="utf-8")
    dest = tmp_path / "hooks-dest"
    copied = _pin_hook_scripts(tmp_path, "context", dest)
    names = [Path(p).name for p in copied]
    assert names == sorted(names)
    assert "skip.txt" not in names
    assert set(names) == {"aaa.py", "session_start.py", "zzz.py"}


# ---------------------------------------------------------------------------
# _safe_install_template
# ---------------------------------------------------------------------------


def test_safe_missing_src_returns_literal(tmp_path: Path):
    """Kill ``missing-src`` → ``XXmissing-srcXX`` / ``MISSING-SRC``."""
    assert _safe_install_template(tmp_path / "nope", tmp_path / "dst") == "missing-src"


def test_safe_create_writes_utf8_and_returns_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill encoding=None/omit/UTF-8 on create write + return ``created``."""
    src = tmp_path / "tpl.txt"
    src.write_text(f"# {QUALITY_MARKER}\nbody\n", encoding="utf-8")
    dst = tmp_path / "nested" / "out.txt"
    seen_write: list[str | None] = []
    seen_read: list[str | None] = []
    real_w = Path.write_text
    real_r = Path.read_text

    def wrap_w(self: Path, data: str, encoding: str | None = None, **kwargs):
        seen_write.append(encoding)
        return real_w(self, data, encoding=encoding, **kwargs)

    def wrap_r(self: Path, encoding: str | None = None, **kwargs):
        seen_read.append(encoding)
        return real_r(self, encoding=encoding, **kwargs)

    monkeypatch.setattr(Path, "write_text", wrap_w)
    monkeypatch.setattr(Path, "read_text", wrap_r)
    assert _safe_install_template(src, dst) == "created"
    assert dst.read_text(encoding="utf-8") == f"# {QUALITY_MARKER}\nbody\n"
    assert seen_read and all(enc == "utf-8" for enc in seen_read)
    assert seen_write and all(enc == "utf-8" for enc in seen_write)


def test_safe_create_pre_push_chmod_execute_bits(tmp_path: Path):
    """Kill pre-push name mutants + ``| 0o111`` → ``| 74`` on create."""
    src = tmp_path / "pre-push"
    src.write_text(f"#!/bin/sh\n# {QUALITY_MARKER}\n", encoding="utf-8")
    dst = tmp_path / ".githooks" / "pre-push"
    assert _safe_install_template(src, dst) == "created"
    mode = dst.stat().st_mode
    assert mode & 0o111 == 0o111


def test_safe_create_non_hook_skips_chmod_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill inverted hook-name check on create (would chmod ci.yml)."""
    src = tmp_path / "ci.yml"
    src.write_text(f"# {QUALITY_MARKER}\nname: CI\n", encoding="utf-8")
    dst = tmp_path / ".github" / "workflows" / "ci.yml"
    chmod_calls: list[Path] = []
    real = Path.chmod

    def wrap(self: Path, mode: int):
        chmod_calls.append(self)
        return real(self, mode)

    monkeypatch.setattr(Path, "chmod", wrap)
    assert _safe_install_template(src, dst) == "created"
    assert chmod_calls == []


def test_safe_update_marked_different_returns_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill encoding spies on update path + return ``updated``."""
    src = tmp_path / "pre-push"
    src.write_text(f"#!/bin/sh\n# {QUALITY_MARKER}\nNEW\n", encoding="utf-8")
    dst = tmp_path / ".githooks" / "pre-push"
    dst.parent.mkdir(parents=True)
    dst.write_text(f"#!/bin/sh\n# {QUALITY_MARKER}\nOLD\n", encoding="utf-8")
    seen_w: list[str | None] = []
    seen_r: list[str | None] = []
    real_w = Path.write_text
    real_r = Path.read_text

    def wrap_w(self: Path, data: str, encoding: str | None = None, **kwargs):
        seen_w.append(encoding)
        return real_w(self, data, encoding=encoding, **kwargs)

    def wrap_r(self: Path, encoding: str | None = None, **kwargs):
        seen_r.append(encoding)
        return real_r(self, encoding=encoding, **kwargs)

    monkeypatch.setattr(Path, "write_text", wrap_w)
    monkeypatch.setattr(Path, "read_text", wrap_r)
    assert _safe_install_template(src, dst) == "updated"
    assert "NEW" in dst.read_text(encoding="utf-8")
    assert all(enc == "utf-8" for enc in seen_w)
    assert all(enc == "utf-8" for enc in seen_r)
    assert dst.stat().st_mode & 0o111 == 0o111


def test_safe_update_pre_push_chmod_or_not_and(tmp_path: Path):
    """Kill ``| 0o111`` → ``& 0o111`` / ``chmod(None)`` on marked update (pre-push only until connect pin follow-up)."""
    src = tmp_path / "pre-push"
    src.write_text(f"#!/bin/sh\n# {QUALITY_MARKER}\nNEW\n", encoding="utf-8")
    dst = tmp_path / ".githooks" / "pre-push"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(f"#!/bin/sh\n# {QUALITY_MARKER}\nOLD\n", encoding="utf-8")
    os.chmod(dst, 0o644)
    assert _safe_install_template(src, dst) == "updated"
    assert dst.stat().st_mode & 0o111 == 0o111


def test_safe_update_non_hook_no_chmod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill inverted hook-name check on update branch."""
    src = tmp_path / "tpl-ci.yml"
    src.write_text(f"# {QUALITY_MARKER}\nNEW\n", encoding="utf-8")
    dst = tmp_path / ".github" / "workflows" / "ci.yml"
    dst.parent.mkdir(parents=True)
    dst.write_text(f"# {QUALITY_MARKER}\nOLD\n", encoding="utf-8")
    chmod_calls: list[Path] = []
    real = Path.chmod

    def wrap(self: Path, mode: int):
        chmod_calls.append(self)
        return real(self, mode)

    monkeypatch.setattr(Path, "chmod", wrap)
    assert _safe_install_template(src, dst) == "updated"
    assert "NEW" in dst.read_text(encoding="utf-8")
    assert chmod_calls == []


def test_safe_unchanged_when_marked_identical(tmp_path: Path):
    """Kill ``unchanged`` path: same marked body stays put."""
    body = f"# {QUALITY_MARKER}\nsame\n"
    src = tmp_path / "tpl"
    src.write_text(body, encoding="utf-8")
    dst = tmp_path / "out"
    dst.write_text(body, encoding="utf-8")
    assert _safe_install_template(src, dst) == "unchanged"
    assert dst.read_text(encoding="utf-8") == body


def test_safe_skipped_user_file_literal(tmp_path: Path):
    """Kill ``skipped-user-file`` when QUALITY_MARKER absent."""
    src = tmp_path / "tpl"
    src.write_text(f"# {QUALITY_MARKER}\nA\n", encoding="utf-8")
    dst = tmp_path / "out"
    dst.write_text("# custom user file\n", encoding="utf-8")
    assert _safe_install_template(src, dst) == "skipped-user-file"
    assert dst.read_text(encoding="utf-8") == "# custom user file\n"


# ---------------------------------------------------------------------------
# ensure_githooks_path
# ---------------------------------------------------------------------------


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)


def test_githooks_set_when_unset_literal_and_value(tmp_path: Path):
    """Kill wanted ``.githooks`` string mutants; return ``set``."""
    _git_init(tmp_path)
    assert ensure_githooks_path(tmp_path) == "set"
    got = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert got.stdout.strip() == ".githooks"


def test_githooks_subprocess_argv_and_kwargs_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill core.hooksPath case/XX mutants + cwd/capture_output/text kwargs."""
    _git_init(tmp_path)
    calls: list[tuple] = []
    real = subprocess.run

    def wrap(cmd, *args, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", wrap)
    assert ensure_githooks_path(tmp_path) == "set"
    assert len(calls) >= 2
    get_cmd, get_kw = calls[0]
    set_cmd, set_kw = calls[1]
    assert get_cmd == ["git", "config", "--local", "--get", "core.hooksPath"]
    assert set_cmd == ["git", "config", "--local", "core.hooksPath", ".githooks"]
    for kw in (get_kw, set_kw):
        assert kw.get("cwd") == tmp_path
        assert kw.get("capture_output") is True
        assert kw.get("text") is True


def test_githooks_get_failure_ignores_stdout_garbage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill ``returncode == 0 or True`` — failed get must not trust stdout."""
    _git_init(tmp_path)
    real = subprocess.run
    state = {"n": 0}

    def wrap(cmd, *args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return MagicMock(returncode=1, stdout="custom-hooks\n", stderr="")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", wrap)
    assert ensure_githooks_path(tmp_path) == "set"
    got = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert got.stdout.strip() == ".githooks"


def test_githooks_empty_stdout_on_success_still_sets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill ``(stdout or \"XXXX\")`` — empty success stdout must set, not preserve."""
    _git_init(tmp_path)
    real = subprocess.run
    state = {"n": 0}

    def wrap(cmd, *args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return MagicMock(returncode=0, stdout="", stderr="")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", wrap)
    assert ensure_githooks_path(tmp_path) == "set"


def test_githooks_set_failure_returns_failed_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill ``returncode == 0 or True`` on set — failure must return ``failed:``."""
    _git_init(tmp_path)
    real = subprocess.run

    def wrap(cmd, *args, **kwargs):
        # set arm: ["git", "config", "--local", "core.hooksPath", wanted]
        if (
            len(cmd) >= 5
            and list(cmd)[:3] == ["git", "config", "--local"]
            and cmd[3] == "core.hooksPath"
        ):
            return MagicMock(returncode=1, stdout="", stderr="boom\n")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", wrap)
    result = ensure_githooks_path(tmp_path)
    assert result == "failed:boom"


def test_githooks_relative_unchanged_literal(tmp_path: Path):
    """Kill return ``unchanged`` string mutants when already ``.githooks``."""
    _git_init(tmp_path)
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", ".githooks"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert ensure_githooks_path(tmp_path) == "unchanged"


def test_githooks_absolute_match_requires_resolve(tmp_path: Path):
    """Kill ``str((root/wanted).resolve())`` → ``str(None)`` absolute match."""
    _git_init(tmp_path)
    abs_hooks = str((tmp_path / ".githooks").resolve())
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", abs_hooks],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert ensure_githooks_path(tmp_path) == "unchanged"


def test_githooks_trailing_slash_rstrip_not_lstrip(tmp_path: Path):
    """Kill ``rstrip("/")`` → ``lstrip`` / ``rstrip(None)``."""
    _git_init(tmp_path)
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", ".githooks/"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert ensure_githooks_path(tmp_path) == "unchanged"


def test_githooks_rstrip_slash_not_xx_charset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill ``rstrip("/")`` → ``rstrip("XX/XX")`` (would strip trailing X)."""
    _git_init(tmp_path)
    real = subprocess.run

    def wrap(cmd, *args, **kwargs):
        if list(cmd) == ["git", "config", "--local", "--get", "core.hooksPath"]:
            return MagicMock(returncode=0, stdout=".githooksX\n", stderr="")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", wrap)
    # Orig keeps trailing X → not wanted → preserved-user.
    # Mutant rstrip("XX/XX") strips X → matches wanted → unchanged.
    assert ensure_githooks_path(tmp_path) == "preserved-user"


def test_githooks_backslash_normalized_in_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill ``replace("\\\\", "/")`` string mutants on ``current`` norm path."""
    _git_init(tmp_path)
    real = subprocess.run

    def wrap(cmd, *args, **kwargs):
        if list(cmd) == ["git", "config", "--local", "--get", "core.hooksPath"]:
            return MagicMock(returncode=0, stdout=".githooks\\", stderr="")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", wrap)
    assert ensure_githooks_path(tmp_path) == "unchanged"


def test_githooks_absolute_resolve_backslash_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill resolve().replace(\"\\\\\", \"/\") → XX\\\\XX / XX/XX (noop on Linux otherwise)."""
    _git_init(tmp_path)
    win_abs = r"C:\workspace\.githooks"
    posix_abs = "C:/workspace/.githooks"
    real_run = subprocess.run

    def wrap_run(cmd, *args, **kwargs):
        if list(cmd) == ["git", "config", "--local", "--get", "core.hooksPath"]:
            return MagicMock(returncode=0, stdout=posix_abs + "\n", stderr="")
        return real_run(cmd, *args, **kwargs)

    class _SlashyResolved:
        def __str__(self) -> str:
            return win_abs

    real_resolve = Path.resolve

    def wrap_resolve(self, *args, **kwargs):
        if self.name == ".githooks" or str(self).endswith(".githooks"):
            return _SlashyResolved()
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", wrap_run)
    monkeypatch.setattr(Path, "resolve", wrap_resolve)
    assert ensure_githooks_path(tmp_path) == "unchanged"


def test_githooks_agent_hooks_skip_literal(tmp_path: Path):
    """Kill ``skipped-cursor-agent-hooks`` path."""
    _git_init(tmp_path)
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", "/home/u/.cursor/agent-hooks/abc"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert ensure_githooks_path(tmp_path) == "skipped-cursor-agent-hooks"


def test_githooks_preserved_user_literal(tmp_path: Path):
    """Kill ``preserved-user`` when custom hooksPath set."""
    _git_init(tmp_path)
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", "custom-hooks"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert ensure_githooks_path(tmp_path) == "preserved-user"
