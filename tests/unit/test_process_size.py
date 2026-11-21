"""Mutation-oriented tests for fail-closed process size / config helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentized.process_size import (
    DOC,
    HARD_CAP,
    classify_size,
    diff_insertions,
    limit_from_base_ref,
    load_process_config_file,
    parse_numstat,
    size_check,
    validate_process_base,
    validate_size_fields,
)

_DEFAULTS = {"reviewable_lines": 1500, "warn_at_pct": 75}


def test_load_missing_returns_defaults_copy(tmp_path: Path):
    defaults = dict(_DEFAULTS)
    path = tmp_path / "missing.json"
    cfg = load_process_config_file(path, defaults)
    assert cfg == {"reviewable_lines": 1500, "warn_at_pct": 75}
    cfg["reviewable_lines"] = 1
    assert defaults["reviewable_lines"] == 1500


def test_load_valid_merges_over_defaults(tmp_path: Path):
    path = tmp_path / "process-control.json"
    # Non-ASCII forces utf-8 decode (kills encoding mutants).
    path.write_bytes(b'{"reviewable_lines": 100, "note": "\xd1\x8f"}\n')
    cfg = load_process_config_file(path, dict(_DEFAULTS))
    assert cfg["reviewable_lines"] == 100
    assert cfg["warn_at_pct"] == 75
    assert cfg["note"] == "я"
    # encoding= keyword must be utf-8 (mutant: drop encoding / wrong codec).
    # Hermetic under mutmut (agentized/…) and dogfood (runtime/agentized/…).
    import inspect

    from agentized import process_size as ps

    src = inspect.getsource(ps.load_process_config_file)
    assert 'path.read_bytes().decode("utf-8")' in src


def test_load_invalid_json_raises(tmp_path: Path):
    path = tmp_path / "process-control.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, dict(_DEFAULTS))
    msg = str(excinfo.value)
    assert msg.startswith(f"process-control: invalid JSON in {path}:")
    assert msg.endswith(f"See {DOC}.")


def test_load_bad_utf8_raises(tmp_path: Path):
    path = tmp_path / "process-control.json"
    path.write_bytes(b'{"x": "\xff"}')
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, dict(_DEFAULTS))
    assert str(excinfo.value).startswith(f"process-control: invalid JSON in {path}:")


def test_load_non_object_raises(tmp_path: Path):
    path = tmp_path / "process-control.json"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, dict(_DEFAULTS))
    assert str(excinfo.value) == (
        f"process-control: {path} must be a JSON object, got list. See {DOC}."
    )
    path.write_text('"str"\n', encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, dict(_DEFAULTS))
    assert str(excinfo.value) == (
        f"process-control: {path} must be a JSON object, got str. See {DOC}."
    )
    path.write_text("null\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, dict(_DEFAULTS))
    assert str(excinfo.value) == (
        f"process-control: {path} must be a JSON object, got NoneType. See {DOC}."
    )


@pytest.mark.parametrize(
    "payload",
    [
        '{"reviewable_lines": 0, "warn_at_pct": 75}',
        '{"reviewable_lines": 1501, "warn_at_pct": 75}',
        '{"reviewable_lines": true, "warn_at_pct": 75}',
        '{"reviewable_lines": "abc", "warn_at_pct": 75}',
        '{"reviewable_lines": {}, "warn_at_pct": 75}',
        '{"reviewable_lines": [], "warn_at_pct": 75}',
        '{"reviewable_lines": null, "warn_at_pct": 75}',
        '{"reviewable_lines": 100, "warn_at_pct": 0}',
        '{"reviewable_lines": 100, "warn_at_pct": 101}',
        '{"reviewable_lines": 100, "warn_at_pct": "abc"}',
        '{"reviewable_lines": 100, "warn_at_pct": true}',
        '{"reviewable_lines": 100, "warn_at_pct": null}',
    ],
)
def test_load_bad_size_fields_raise(tmp_path: Path, payload: str):
    path = tmp_path / "process-control.json"
    path.write_text(payload + "\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_process_config_file(path, dict(_DEFAULTS))
    msg = str(excinfo.value)
    assert msg.startswith("process-control:")
    assert f" in {path}" in msg
    assert msg.endswith(f"See {DOC}.")


def test_validate_size_fields_accepts_bounds():
    assert validate_size_fields({"reviewable_lines": 1, "warn_at_pct": 1}) == (1, 1.0)
    assert validate_size_fields({"reviewable_lines": HARD_CAP, "warn_at_pct": 100}) == (
        HARD_CAP,
        100.0,
    )
    assert validate_size_fields({"reviewable_lines": 50, "warn_at_pct": 50.5}) == (50, 50.5)


def test_validate_size_fields_where_clause_includes_path(tmp_path: Path):
    path = tmp_path / "process-control.json"
    with pytest.raises(ValueError) as with_path:
        validate_size_fields({"reviewable_lines": 0, "warn_at_pct": 75}, path=path)
    assert str(with_path.value) == (
        f"process-control: reviewable_lines must be an int 1..{HARD_CAP} in {path}, "
        f"got 0. See {DOC}."
    )
    with pytest.raises(ValueError) as no_path:
        validate_size_fields({"reviewable_lines": 0, "warn_at_pct": 75})
    assert str(no_path.value) == (
        f"process-control: reviewable_lines must be an int 1..{HARD_CAP}, got 0. See {DOC}."
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
    # Inclusive limit: at-limit is warn (not over); +1 is over.
    assert classify_size(100, 100, 50.0) == ("warn", True, 50)
    assert classify_size(101, 100, 50.0) == ("over", False, 50)
    assert classify_size(101, 100, 75.0) == ("over", False, 75)
    assert classify_size(0, 1500, 75.0) == ("ok", True, 1125)
    assert classify_size(1125, 1500, 75.0) == ("warn", True, 1125)
    assert classify_size(1499, 1500, 75.0) == ("warn", True, 1125)
    assert classify_size(1500, 1500, 75.0) == ("warn", True, 1125)
    assert classify_size(1501, 1500, 75.0) == ("over", False, 1125)


def test_validate_process_base_rejects_head(tmp_path: Path):
    for bad in ("", "   ", "HEAD", "head", "HeAd", "@"):
        with pytest.raises(ValueError, match="must not be HEAD"):
            validate_process_base(tmp_path, bad)


def test_validate_process_base_asserts_git_calls(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        def __init__(self, code: int, stderr: str = "", stdout: str = ""):
            self.returncode = code
            self.stderr = stderr
            self.stdout = stdout

    calls: list[tuple] = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        if cmd[:3] == ["git", "rev-parse", "--verify"]:
            return FakeProc(0)
        return FakeProc(0)

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    validate_process_base(tmp_path, "abc123")
    assert len(calls) == 2
    assert calls[0][0] == ["git", "rev-parse", "--verify", "origin/main"]
    assert calls[1][0] == ["git", "merge-base", "--is-ancestor", "abc123", "origin/main"]
    for _cmd, kw in calls:
        assert kw["cwd"] == str(tmp_path)
        assert kw["capture_output"] is True
        assert kw["text"] is True
        assert kw["check"] is False


def test_validate_process_base_detail_fallback(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        def __init__(self, code=128, stderr="", stdout=""):
            self.returncode = code
            self.stderr = stderr
            self.stdout = stdout

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: FakeProc())  # noqa: ARG005
    with pytest.raises(RuntimeError) as empty:
        validate_process_base(tmp_path, "abc123")
    assert str(empty.value) == (
        f"process-control: origin/main unavailable for base check: exit 128. See {DOC}."
    )
    # stdout-only detail (kills or→and mutants on stderr/stdout chain).
    monkeypatch.setattr(
        ps.subprocess, "run", lambda *a, **k: FakeProc(1, stderr="", stdout="boom\n")
    )
    with pytest.raises(RuntimeError) as from_out:
        validate_process_base(tmp_path, "abc123")
    assert str(from_out.value) == (
        f"process-control: origin/main unavailable for base check: boom. See {DOC}."
    )


def _git_repo_with_main(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Fake origin/main via fetch of local path isn't needed — update-ref.
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", sha],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_validate_process_base_ancestor_ok_and_reject(tmp_path: Path):
    root = _git_repo_with_main(tmp_path)
    validate_process_base(root, "origin/main")
    # orphan commit not ancestor of origin/main
    subprocess.run(
        ["git", "checkout", "--orphan", "orphan"], cwd=root, check=True, capture_output=True
    )
    (root / "orphan.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "orphan.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "orphan"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    orphan = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    with pytest.raises(ValueError, match="ancestor of origin/main"):
        validate_process_base(root, orphan)


def test_limit_from_base_ref(tmp_path: Path):
    root = _git_repo_with_main(tmp_path)
    ctx = root / "context"
    ctx.mkdir()
    (ctx / "process-control.json").write_text(
        '{"reviewable_lines": 400, "warn_at_pct": 50}\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "context"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "cfg"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", sha],
        cwd=root,
        check=True,
        capture_output=True,
    )
    assert limit_from_base_ref(root, "origin/main", "context") == 400
    assert limit_from_base_ref(root, "origin/main", "missing-ctx") is None


def test_validate_process_base_missing_origin_main(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "f").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "f"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "c"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    with pytest.raises(RuntimeError, match="origin/main unavailable"):
        validate_process_base(tmp_path, sha)


def test_limit_from_base_ref_invalid_payloads(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        def __init__(self, code, stdout=""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = ""

    results = []
    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: FakeProc(0, "{bad"))
    results.append(limit_from_base_ref(tmp_path, "origin/main", "context"))
    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: FakeProc(0, "[]\n"))
    results.append(limit_from_base_ref(tmp_path, "origin/main", "context"))
    monkeypatch.setattr(
        ps.subprocess, "run", lambda *a, **k: FakeProc(0, '{"reviewable_lines": 0}\n')
    )
    results.append(limit_from_base_ref(tmp_path, "origin/main", "context"))
    monkeypatch.setattr(
        ps.subprocess, "run", lambda *a, **k: FakeProc(0, '{"reviewable_lines": true}\n')
    )
    results.append(limit_from_base_ref(tmp_path, "origin/main", "context"))
    monkeypatch.setattr(
        ps.subprocess,
        "run",
        lambda *a, **k: FakeProc(0, f'{{"reviewable_lines": {HARD_CAP + 1}}}\n'),
    )
    results.append(limit_from_base_ref(tmp_path, "origin/main", "context"))
    # Concrete tuple oracle (not bare `is None` membership/identity).
    assert results == [None, None, None, None, None]
    assert [type(x).__name__ for x in results] == ["NoneType"] * 5


def test_limit_from_base_ref_asserts_git_show(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        returncode = 0
        stdout = '{"reviewable_lines": 200}\n'
        stderr = ""

    calls: list[tuple] = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        return FakeProc()

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    assert limit_from_base_ref(tmp_path, "origin/main", "context") == 200
    assert len(calls) == 1
    cmd, kw = calls[0]
    assert cmd == ["git", "show", "origin/main:context/process-control.json"]
    assert kw["cwd"] == str(tmp_path)
    assert kw["capture_output"] is True
    assert kw["text"] is True
    assert kw["check"] is False


def test_limit_from_base_ref_bounds_and_bool(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        def __init__(self, stdout: str):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: FakeProc('{"reviewable_lines": 1}\n'))
    assert limit_from_base_ref(tmp_path, "origin/main", "context") == 1
    monkeypatch.setattr(
        ps.subprocess,
        "run",
        lambda *a, **k: FakeProc(f'{{"reviewable_lines": {HARD_CAP}}}\n'),
    )
    assert limit_from_base_ref(tmp_path, "origin/main", "context") == HARD_CAP
    monkeypatch.setattr(
        ps.subprocess, "run", lambda *a, **k: FakeProc('{"reviewable_lines": false}\n')
    )
    assert limit_from_base_ref(tmp_path, "origin/main", "context") is None
    # String must return None (or→and mutant would TypeError on compare).
    monkeypatch.setattr(
        ps.subprocess, "run", lambda *a, **k: FakeProc('{"reviewable_lines": "x"}\n')
    )
    assert limit_from_base_ref(tmp_path, "origin/main", "context") is None


def test_size_check_levels_and_message(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 100, "warn_at_pct": 50}\n', encoding="utf-8"
    )
    monkeypatch.setattr("agentized.process_size.validate_process_base", lambda *a, **k: None)
    monkeypatch.setattr("agentized.process_size.limit_from_base_ref", lambda *a, **k: None)
    monkeypatch.setattr("agentized.process_size.diff_insertions", lambda *a, **k: 60)
    result = size_check(tmp_path)
    assert result["level"] == "warn"
    assert result["ok"] is True
    assert result["base"] == "origin/main"
    assert "over >100" in result["message"]
    assert "≤100 OK" in result["message"]
    assert DOC in result["message"]

    monkeypatch.setattr("agentized.process_size.diff_insertions", lambda *a, **k: 100)
    at_limit = size_check(tmp_path)
    assert at_limit["level"] == "warn"
    assert at_limit["ok"] is True

    monkeypatch.setattr("agentized.process_size.diff_insertions", lambda *a, **k: 101)
    over = size_check(tmp_path)
    assert over == {
        "ok": False,
        "level": "over",
        "insertions": 101,
        "limit": 100,
        "warn_at": 50,
        "base": "origin/main",
        "message": over["message"],
    }
    assert over["ok"] is False


def test_size_check_error_dict_and_process_base(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 100, "warn_at_pct": 50}\n', encoding="utf-8"
    )

    def boom(*a, **k):  # noqa: ARG001
        raise ValueError("process-control: base ref must not be HEAD")

    monkeypatch.setattr("agentized.process_size.validate_process_base", boom)
    err = size_check(tmp_path, base_ref="HEAD")
    assert err == {
        "ok": False,
        "level": "error",
        "insertions": 0,
        "limit": 0,
        "warn_at": 0,
        "base": "HEAD",
        "message": "process-control: base ref must not be HEAD",
    }

    monkeypatch.setattr("agentized.process_size.validate_process_base", lambda *a, **k: None)
    monkeypatch.setattr("agentized.process_size.limit_from_base_ref", lambda *a, **k: None)
    monkeypatch.setattr("agentized.process_size.diff_insertions", lambda *a, **k: 1)
    monkeypatch.setenv("PROCESS_BASE", "origin/main")
    used = size_check(tmp_path)
    assert used["base"] == "origin/main"
    assert used["ok"] is True


def test_size_check_uses_base_limit_cap(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 1500, "warn_at_pct": 75}\n', encoding="utf-8"
    )
    monkeypatch.setattr("agentized.process_size.validate_process_base", lambda *a, **k: None)
    calls: list[tuple] = []

    def fake_base_limit(root, base, context_rel):
        calls.append((root, base, context_rel))
        return 200

    monkeypatch.setattr("agentized.process_size.limit_from_base_ref", fake_base_limit)
    monkeypatch.setattr("agentized.process_size.diff_insertions", lambda *a, **k: 201)
    result = size_check(tmp_path, context_rel="context", base_ref="origin/main")
    assert calls == [(tmp_path, "origin/main", "context")]
    assert result["limit"] == 200
    assert result["ok"] is False
    assert result["level"] == "over"
    (tmp_path / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 100, "warn_at_pct": 75}\n', encoding="utf-8"
    )
    monkeypatch.setattr("agentized.process_size.diff_insertions", lambda *a, **k: 50)
    low = size_check(tmp_path, context_rel="context", base_ref="origin/main")
    assert low["limit"] == 100
    assert low["ok"] is True


def test_real_git_size_boundary_1500(tmp_path: Path, monkeypatch):
    """Real git repo: 1500 insertions → ok; 1501 → over."""

    def _init():
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "checkout", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
        )
        (tmp_path / "seed.txt").write_text("s\n", encoding="utf-8")
        subprocess.run(["git", "add", "seed.txt"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", sha],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        (tmp_path / "context").mkdir(exist_ok=True)
        (tmp_path / "context" / "process-control.json").write_text(
            '{"reviewable_lines": 1500, "warn_at_pct": 75}\n', encoding="utf-8"
        )

    _init()
    (tmp_path / "big.txt").write_text(
        "\n".join(f"L{i}" for i in range(1500)) + "\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "big.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "add1500"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr("agentized.process_size.limit_from_base_ref", lambda *a, **k: None)
    ok = size_check(tmp_path, base_ref="origin/main")
    assert ok["insertions"] == 1500
    assert ok["ok"] is True
    assert ok["level"] in {"ok", "warn"}

    (tmp_path / "big.txt").write_text(
        "\n".join(f"L{i}" for i in range(1501)) + "\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "big.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "add1501"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    over = size_check(tmp_path, base_ref="origin/main")
    assert over["insertions"] == 1501
    assert over["ok"] is False
    assert over["level"] == "over"
