"""Mutation-oriented tests for fail-closed process size / config helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentized.process_size import (
    DOC,
    classify_size,
    diff_insertions,
    load_process_config_file,
    parse_numstat,
    require_hard_size_mode,
)


def test_load_missing_returns_defaults_copy(tmp_path: Path):
    defaults = {"reviewable_lines": 1500, "warn_at_pct": 75, "size_mode": "hard"}
    path = tmp_path / "missing.json"
    cfg = load_process_config_file(path, defaults)
    assert cfg == {"reviewable_lines": 1500, "warn_at_pct": 75, "size_mode": "hard"}
    cfg["reviewable_lines"] = 1
    assert defaults["reviewable_lines"] == 1500


def test_require_hard_size_mode_accepts_hard_and_missing():
    require_hard_size_mode({"size_mode": "hard"})
    require_hard_size_mode({})  # missing → treated as hard


def test_require_hard_size_mode_rejects_others():
    for bad in ("soft", "warn", "banana", 1, True, None):
        with pytest.raises(ValueError) as excinfo:
            require_hard_size_mode({"size_mode": bad})
        assert str(excinfo.value) == (
            f"process-control: size_mode must be 'hard', got {bad!r}. See {DOC}."
        )


def test_load_rejects_non_hard_size_mode(tmp_path: Path):
    path = tmp_path / "process-control.json"
    path.write_text('{"size_mode": "soft"}\n', encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, {"size_mode": "hard", "reviewable_lines": 1500})
    assert str(excinfo.value) == (
        "process-control: size_mode must be 'hard', got 'soft'. See docs/process-control.md."
    )


def test_load_valid_merges_over_defaults(tmp_path: Path):
    path = tmp_path / "process-control.json"
    # Non-ASCII forces utf-8 decode (kills encoding mutants).
    path.write_bytes(b'{"reviewable_lines": 100, "note": "\xd1\x8f", "size_mode": "hard"}\n')
    cfg = load_process_config_file(
        path, {"reviewable_lines": 1500, "warn_at_pct": 75, "size_mode": "hard"}
    )
    assert cfg["reviewable_lines"] == 100
    assert cfg["warn_at_pct"] == 75
    assert cfg["note"] == "я"
    assert cfg["size_mode"] == "hard"


def test_load_invalid_json_raises(tmp_path: Path):
    path = tmp_path / "process-control.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, {"reviewable_lines": 1500})
    msg = str(excinfo.value)
    assert msg.startswith(f"process-control: invalid JSON in {path}:")
    assert msg.endswith(f"See {DOC}.")


def test_load_bad_utf8_raises(tmp_path: Path):
    path = tmp_path / "process-control.json"
    path.write_bytes(b'{"x": "\xff"}')
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, {"reviewable_lines": 1500})
    assert str(excinfo.value).startswith(f"process-control: invalid JSON in {path}:")


def test_load_non_object_raises(tmp_path: Path):
    path = tmp_path / "process-control.json"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, {"reviewable_lines": 1500})
    assert str(excinfo.value) == (
        f"process-control: {path} must be a JSON object, got list. See {DOC}."
    )
    path.write_text('"str"\n', encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, {"reviewable_lines": 1500})
    assert str(excinfo.value) == (
        f"process-control: {path} must be a JSON object, got str. See {DOC}."
    )
    path.write_text("null\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, {"reviewable_lines": 1500})
    assert str(excinfo.value) == (
        f"process-control: {path} must be a JSON object, got NoneType. See {DOC}."
    )


def test_parse_numstat_sums_and_skips():
    text = "\n".join(
        [
            "10\t2\ta.py",
            "-\t-\tbin.dat",
            "badline",
            "x\t1\tskip.py",
            "5\t0\tb.py",
            "0\t3\tc.py",
            # Space-separated must NOT count (tabs required).
            "99 0 spaced.py",
            "",
        ]
    )
    assert parse_numstat(text) == 15
    assert parse_numstat("") == 0
    assert parse_numstat("1\t0\tonly.py") == 1
    assert parse_numstat("99 0 spaced.py") == 0


def test_diff_insertions_asserts_git_invocation(tmp_path: Path, monkeypatch):
    import subprocess
    from agentized import process_size as ps

    class FakeProc:
        def __init__(self, code: int, stderr: str = "", stdout: str = ""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    calls: list[tuple] = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        return FakeProc(128, stderr="fatal: bad revision")

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="git diff failed") as excinfo:
        diff_insertions(tmp_path, "origin/main")
    assert DOC in str(excinfo.value)
    assert len(calls) == 2
    cmd0, kw0 = calls[0]
    cmd1, kw1 = calls[1]
    assert cmd0 == ["git", "diff", "--numstat", "origin/main...HEAD"]
    assert cmd1 == ["git", "diff", "--numstat", "origin/main"]
    for kw in (kw0, kw1):
        assert kw["cwd"] == str(tmp_path)
        assert kw["capture_output"] is True
        assert kw["text"] is True
        assert kw["check"] is False


def test_diff_insertions_empty_detail_uses_exit_code(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        returncode = 2
        stdout = ""
        stderr = ""

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: FakeProc())  # noqa: ARG005
    with pytest.raises(RuntimeError, match="exit 2"):
        diff_insertions(tmp_path, "main")


def test_diff_insertions_fallback_and_parse(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        def __init__(self, code: int, stdout: str = "", stderr: str = ""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        assert kwargs["cwd"] == str(tmp_path)
        assert cmd[0] == "git"
        assert cmd[1] == "diff"
        assert cmd[2] == "--numstat"
        ref = cmd[3]
        if "..." in ref:
            return FakeProc(128, stderr="no triple")
        return FakeProc(0, stdout="3\t1\tc.py\n7\t0\td.py\n")

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    assert diff_insertions(tmp_path, "main") == 10


def test_diff_insertions_triple_dot_success(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        returncode = 0
        stdout = "4\t1\te.py\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        assert cmd == ["git", "diff", "--numstat", "origin/main...HEAD"]
        assert kwargs["cwd"] == str(tmp_path)
        return FakeProc()

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    assert diff_insertions(tmp_path, "origin/main") == 4


def test_diff_insertions_stdout_detail_when_stderr_empty(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        returncode = 1
        stdout = "stdout-detail"
        stderr = ""

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: FakeProc())  # noqa: ARG005
    with pytest.raises(RuntimeError, match="stdout-detail"):
        diff_insertions(tmp_path, "x")


def test_classify_size_levels():
    assert classify_size(10, 100, 50.0) == ("ok", True, 50)
    assert classify_size(50, 100, 50.0) == ("warn", True, 50)
    assert classify_size(51, 100, 50.0) == ("warn", True, 50)
    assert classify_size(100, 100, 50.0) == ("over", False, 50)
    assert classify_size(101, 100, 75.0) == ("over", False, 75)
    assert classify_size(0, 1500, 75.0) == ("ok", True, 1125)
    assert classify_size(1125, 1500, 75.0) == ("warn", True, 1125)
    assert classify_size(1499, 1500, 75.0) == ("warn", True, 1125)
    assert classify_size(1500, 1500, 75.0) == ("over", False, 1125)
