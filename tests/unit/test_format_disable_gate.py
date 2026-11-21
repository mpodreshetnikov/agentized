"""Unit + mutation oracles for format_disable_gate (T-261121-8c84)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentized import format_disable_gate as gate
from agentized import process_size as ps


def _needle(*parts: str) -> str:
    """Build a banned lexeme without writing it as a contiguous comment in this file."""
    return "".join(parts)


def test_is_python_path():
    cases = [
        ("runtime/agentized/x.py", 1),
        ("x.PY", 1),
        ("x.pyi", 1),
        ("docs/QUALITY.md", 0),
        ("script.sh", 0),
        ("", 0),
    ]
    got = [(path, 1 if gate.is_python_path(path) else 0) for path, _ in cases]
    assert got == cases


def test_line_has_disable_positive_and_negative():
    fmt_off = _needle("#", " fmt: ", "off")
    fmt_skip = _needle("#", " fmt: ", "skip")
    fmt_on = _needle("#", " fmt: ", "on")
    noqa = _needle("#", " noqa")
    noqa_code = _needle("#", " noqa: ", "E501")
    ruff_noqa = _needle("#", " ruff: ", "noqa")
    flake = _needle("#", " flake8: ", "noqa")
    isort_skip = _needle("#", " isort: ", "skip")
    isort_off = _needle("#", " isort: ", "off")
    yapf = _needle("#", " yapf: ", "disable")
    positives = (
        fmt_off,
        f"x = 1  {fmt_off}",
        fmt_skip,
        fmt_on,
        noqa,
        noqa_code,
        ruff_noqa,
        flake,
        isort_skip,
        isort_off,
        yapf,
        _needle("#", "FMT:", "OFF"),
    )
    negatives = ("x = 1", "print('hello')", "# comment about format", "# no qa typo")
    got = [1 if gate.line_has_disable(s) else 0 for s in positives + negatives]
    assert got == [1] * len(positives) + [0] * len(negatives)


def test_disable_comments_in_source_ignores_strings_and_docstrings():
    fmt_off = _needle("#", " fmt: ", "off")
    noqa = _needle("#", " noqa")
    src = (
        f'"""docs may mention {fmt_off} and {noqa}."""\n'
        f"s = '{fmt_off}'\n"
        f"x = 1  {fmt_off}\n"
        f"y = 2  {noqa}\n"
    )
    hits = gate.disable_comments_in_source(src)
    assert [(n, t.strip()) for n, t in hits] == [
        (3, fmt_off),
        (4, noqa),
    ]


def test_disable_comments_untokenizeable_fail_closed():
    fmt_off = _needle("#", " fmt: ", "off")
    src = f'"""\n{fmt_off}\n'
    hits = gate.disable_comments_in_source(src)
    assert hits == [(0, gate._UNTTOKEN_MSG)]
    assert gate.disable_comments_in_source('"""\nplain\n') == []


def test_format_findings_message_empty_and_nonempty():
    empty = gate.format_findings_message("origin/main", [])
    assert empty == (
        "format-disable-gate: PR adds 0 formatter/linter disable "
        "comment(s) vs origin/main (no allowlist). Remove them or get Maxim approval. "
        f"See {gate.DOC}."
    )
    fmt_off = _needle("#", " fmt: ", "off")
    raw = f"  {fmt_off}  "
    msg = gate.format_findings_message("abc", [("x.py", 4, raw)])
    assert msg == (
        "format-disable-gate: PR adds 1 formatter/linter disable "
        "comment(s) vs abc (no allowlist). Remove them or get Maxim approval. "
        f"See {gate.DOC}.\n"
        f"  x.py:4: {raw.rstrip()}"
    )
    # Two findings pin the "\n".join separator (not XX\nXX).
    two = gate.format_findings_message(
        "b",
        [("a.py", 1, fmt_off), ("a.py", 2, fmt_off)],
    )
    assert two.endswith(f"  a.py:1: {fmt_off}\n  a.py:2: {fmt_off}")


def test_changed_python_files_git_args_and_fallback(tmp_path: Path, monkeypatch):
    class FakeProc:
        def __init__(self, code: int, stdout: str = "", stderr: str = ""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    calls: list[tuple] = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        if "..." in cmd[-1]:
            return FakeProc(128, stderr="no triple")
        return FakeProc(0, stdout="a.py\nREADME.md\nb.PYI\n\nc.sh\n")

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    assert gate.changed_python_files(tmp_path, "origin/main") == ["a.py", "b.PYI"]
    assert len(calls) == 2
    cmd0, kw0 = calls[0]
    cmd1, kw1 = calls[1]
    assert cmd0 == [
        "git",
        "diff",
        "--name-only",
        f"--diff-filter={gate._DIFF_FILTER}",
        "origin/main...HEAD",
    ]
    assert cmd1 == [
        "git",
        "diff",
        "--name-only",
        f"--diff-filter={gate._DIFF_FILTER}",
        "origin/main",
    ]
    for kw in (kw0, kw1):
        assert kw["cwd"] == str(tmp_path)
        assert kw["capture_output"] is True
        assert kw["text"] is True
        assert kw["check"] is False


def test_changed_python_files_fail_closed_detail(tmp_path: Path, monkeypatch):
    class FakeProc:
        def __init__(self, code: int, stdout: str = "", stderr: str = ""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(
        ps.subprocess,
        "run",
        lambda *a, **k: FakeProc(7, stdout="", stderr=""),
    )
    with pytest.raises(RuntimeError) as excinfo:
        gate.changed_python_files(tmp_path, "origin/main")
    assert str(excinfo.value) == (
        f"format-disable-gate: git diff failed for 'origin/main': exit 7. See {gate.DOC}."
    )

    monkeypatch.setattr(
        ps.subprocess,
        "run",
        lambda *a, **k: FakeProc(3, stdout="out-only", stderr=""),
    )
    with pytest.raises(RuntimeError) as excinfo:
        gate.changed_python_files(tmp_path, "base")
    assert str(excinfo.value) == (
        f"format-disable-gate: git diff failed for 'base': out-only. See {gate.DOC}."
    )

    monkeypatch.setattr(
        ps.subprocess,
        "run",
        lambda *a, **k: FakeProc(3, stdout="ignored", stderr="err-wins"),
    )
    with pytest.raises(RuntimeError) as excinfo:
        gate.changed_python_files(tmp_path, "base")
    assert str(excinfo.value) == (
        f"format-disable-gate: git diff failed for 'base': err-wins. See {gate.DOC}."
    )


def test_changed_python_files_triple_ok(tmp_path: Path, monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = "only.py\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        assert cmd[-1] == "main...HEAD"
        return FakeProc()

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    assert gate.changed_python_files(tmp_path, "main") == ["only.py"]


def test_git_show_text_args(tmp_path: Path, monkeypatch):
    class FakeProc:
        def __init__(self, code: int, stdout: str = ""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = ""

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        return FakeProc(0, stdout="BODY")

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    assert gate.git_show_text(tmp_path, "rev", "x.py") == "BODY"
    assert calls == [["git", "show", "rev:x.py"]]

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: FakeProc(1))
    assert gate.git_show_text(tmp_path, "rev", "missing.py") is None


def test_read_head_text_disk_and_fallback(tmp_path: Path, monkeypatch):
    py = tmp_path / "x.py"
    py.write_text("from_disk\n", encoding=gate._FILE_ENCODING)
    encodings: list[str | None] = []
    real_read = Path.read_text

    def spy_read(self, *args, encoding=None, **kwargs):
        encodings.append(encoding)
        return real_read(self, *args, encoding=encoding, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read)
    assert gate.read_head_text(tmp_path, "x.py") == "from_disk\n"
    assert encodings == [gate._FILE_ENCODING]

    show_calls: list[tuple[object, str, str]] = []

    def capture(root, rev, path):
        show_calls.append((root, rev, path))
        return "HEADBODY"

    monkeypatch.setattr(gate, "git_show_text", capture)
    assert gate.read_head_text(tmp_path, "y.py") == "HEADBODY"
    assert show_calls == [(tmp_path, "HEAD", "y.py")]

    monkeypatch.setattr(gate, "git_show_text", lambda root, rev, path: None)
    assert gate.read_head_text(tmp_path, "nope.py") == ""


def test_new_disable_findings_grandfather_duplicates_and_missing_base(tmp_path: Path, monkeypatch):
    fmt_off = _needle("#", " fmt: ", "off")
    noqa = _needle("#", " noqa")

    head_calls: list[tuple[object, str]] = []
    show_calls: list[tuple[object, str, str]] = []
    src_calls: list[str] = []

    def fake_head(root: Path, path: str) -> str:
        head_calls.append((root, path))
        return f"a  {fmt_off}\nb  {fmt_off}\nc  {noqa}\n"

    def fake_base(root: Path, rev: str, path: str) -> str | None:
        show_calls.append((root, rev, path))
        if rev == "missing":
            return None
        return f"a  {fmt_off}\n"

    real_disable = gate.disable_comments_in_source

    def spy_disable(src: str):
        src_calls.append(src)
        return real_disable(src)

    monkeypatch.setattr(gate, "read_head_text", fake_head)
    monkeypatch.setattr(gate, "git_show_text", fake_base)
    monkeypatch.setattr(gate, "disable_comments_in_source", spy_disable)
    findings = gate.new_disable_findings(tmp_path, "origin/main", "x.py")
    assert findings == [
        ("x.py", 2, fmt_off),
        ("x.py", 3, noqa),
    ]
    assert head_calls == [(tmp_path, "x.py")]
    assert show_calls == [(tmp_path, "origin/main", "x.py")]

    src_calls.clear()
    head_calls.clear()
    show_calls.clear()
    all_new = gate.new_disable_findings(tmp_path, "missing", "x.py")
    assert len(all_new) == 3
    assert all_new[0][0] == "x.py"
    assert show_calls == [(tmp_path, "missing", "x.py")]
    # Missing base must feed exact empty string into the tokenizer (not None / XXXX).
    assert src_calls[1] == ""


def test_new_disable_findings_decrement_by_one(tmp_path: Path, monkeypatch):
    """remaining[text] -= 1 (not 2): base=2, head=4 → exactly 2 net-new."""
    fmt_off = _needle("#", " fmt: ", "off")
    lines = "\n".join(f"x  {fmt_off}" for _ in range(4)) + "\n"
    base_lines = "\n".join(f"x  {fmt_off}" for _ in range(2)) + "\n"
    monkeypatch.setattr(gate, "read_head_text", lambda root, path: lines)
    monkeypatch.setattr(gate, "git_show_text", lambda root, rev, path: base_lines)
    findings = gate.new_disable_findings(tmp_path, "origin/main", "z.py")
    assert findings == [
        ("z.py", 3, fmt_off),
        ("z.py", 4, fmt_off),
    ]


def test_format_disable_check_ok_fail_error(tmp_path: Path, monkeypatch):
    validate_calls: list[tuple[object, str]] = []
    changed_calls: list[tuple[object, str]] = []
    finding_calls: list[tuple[object, str, str]] = []

    def spy_validate(root, base):
        validate_calls.append((root, base))

    def spy_changed(root, base):
        changed_calls.append((root, base))
        return []

    monkeypatch.setattr(gate, "validate_process_base", spy_validate)
    monkeypatch.setattr(gate, "changed_python_files", spy_changed)
    ok = gate.format_disable_check(tmp_path, base_ref="origin/main")
    assert ok == {
        "ok": True,
        "level": "ok",
        "base": "origin/main",
        "findings": [],
        "message": (
            "format-disable-gate: no new fmt/noqa-style disable comments vs origin/main. "
            f"See {gate.DOC}."
        ),
    }
    assert validate_calls == [(tmp_path, "origin/main")]
    assert changed_calls == [(tmp_path, "origin/main")]

    fmt_off = _needle("#", " fmt: ", "off")
    validate_calls.clear()
    changed_calls.clear()

    def spy_changed_one(root, base):
        changed_calls.append((root, base))
        return ["x.py"]

    def spy_findings(root, base, path):
        finding_calls.append((root, base, path))
        return [(path, 1, fmt_off)]

    monkeypatch.setattr(gate, "changed_python_files", spy_changed_one)
    monkeypatch.setattr(gate, "new_disable_findings", spy_findings)
    bad = gate.format_disable_check(tmp_path, base_ref="deadbeef")
    assert bad["ok"] is False
    assert bad["level"] == "fail"
    assert bad["base"] == "deadbeef"
    assert bad["findings"] == [{"path": "x.py", "line": 1, "text": fmt_off}]
    assert bad["message"] == gate.format_findings_message("deadbeef", [("x.py", 1, fmt_off)])
    assert validate_calls == [(tmp_path, "deadbeef")]
    assert changed_calls == [(tmp_path, "deadbeef")]
    assert finding_calls == [(tmp_path, "deadbeef", "x.py")]

    def refuse(root, base):
        raise ValueError("process-control: base ref must not be HEAD")

    monkeypatch.setattr(gate, "validate_process_base", refuse)
    err = gate.format_disable_check(tmp_path, base_ref="HEAD")
    assert err == {
        "ok": False,
        "level": "error",
        "base": "HEAD",
        "findings": [],
        "message": "process-control: base ref must not be HEAD",
    }

    monkeypatch.setattr(gate, "validate_process_base", spy_validate)
    monkeypatch.setattr(gate, "changed_python_files", spy_changed)
    validate_calls.clear()
    monkeypatch.setenv("PROCESS_BASE", "env-base-sha")
    used = gate.format_disable_check(tmp_path)
    assert used["base"] == "env-base-sha"
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    used2 = gate.format_disable_check(tmp_path)
    assert used2["base"] == gate.DEFAULT_BASE


def test_format_disable_check_runtime_error_path(tmp_path: Path, monkeypatch):
    validate_calls: list[tuple[object, str]] = []

    def spy_validate(root, base):
        validate_calls.append((root, base))

    def boom(root, base):
        raise RuntimeError("format-disable-gate: git diff failed")

    monkeypatch.setattr(gate, "validate_process_base", spy_validate)
    monkeypatch.setattr(gate, "changed_python_files", boom)
    err = gate.format_disable_check(tmp_path, base_ref="origin/main")
    assert err["ok"] is False
    assert err["level"] == "error"
    assert err["message"] == "format-disable-gate: git diff failed"
    assert validate_calls == [(tmp_path, "origin/main")]


def test_constants():
    assert gate.DOC == "docs/QUALITY.md"
    assert gate.DEFAULT_BASE == "origin/main"
    assert gate._FILE_ENCODING == "utf-8"
    assert gate._DIFF_FILTER == "ACMR"
