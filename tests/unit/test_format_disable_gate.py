"""Unit + mutation oracles for format_disable_gate (T-261121-8c84)."""

from __future__ import annotations

from pathlib import Path

from agentized import format_disable_gate as gate


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
    # Unclosed triple-quote → TokenError; lexeme still present → synthetic finding.
    src = f'"""\n{fmt_off}\n'
    hits = gate.disable_comments_in_source(src)
    assert hits == [(0, "<untokenizeable source with disable lexeme>")]
    # TokenError without a disable lexeme → empty (not a false positive).
    assert gate.disable_comments_in_source('"""\nplain\n') == []


def test_format_findings_message_empty_and_nonempty():
    empty = gate.format_findings_message("origin/main", [])
    assert empty.startswith("format-disable-gate: PR adds 0")
    assert empty.endswith(f"See {gate.DOC}.")
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


def test_new_disable_findings_grandfather_and_net_new(tmp_path: Path, monkeypatch):
    fmt_off = _needle("#", " fmt: ", "off")
    noqa = _needle("#", " noqa")

    def fake_head(root: Path, path: str) -> str:
        return f"x = 1  {fmt_off}\ny = 2  {noqa}\n"

    def fake_base(root: Path, rev: str, path: str) -> str | None:
        return f"x = 1  {fmt_off}\n"

    monkeypatch.setattr(gate, "read_head_text", fake_head)
    monkeypatch.setattr(gate, "git_show_text", fake_base)
    findings = gate.new_disable_findings(tmp_path, "origin/main", "x.py")
    assert len(findings) == 1
    assert findings[0][0] == "x.py"
    assert noqa in findings[0][2]


def test_format_disable_check_ok_and_fail(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gate, "validate_process_base", lambda *a, **k: None)
    monkeypatch.setattr(gate, "changed_python_files", lambda root, base: [])
    ok = gate.format_disable_check(tmp_path, base_ref="origin/main")
    assert ok["ok"] is True
    assert ok["level"] == "ok"
    assert ok["findings"] == []
    assert "no new" in ok["message"]
    assert ok["base"] == "origin/main"

    fmt_off = _needle("#", " fmt: ", "off")
    monkeypatch.setattr(gate, "changed_python_files", lambda root, base: ["x.py"])
    monkeypatch.setattr(
        gate,
        "new_disable_findings",
        lambda root, base, path: [(path, 1, fmt_off)],
    )
    bad = gate.format_disable_check(tmp_path, base_ref="deadbeef")
    assert bad["ok"] is False
    assert bad["level"] == "fail"
    assert bad["base"] == "deadbeef"
    assert len(bad["findings"]) == 1
    assert bad["findings"][0]["path"] == "x.py"
    assert "Maxim" in bad["message"]


def test_format_disable_check_error_and_process_base(tmp_path: Path, monkeypatch):
    def refuse_head(*_a, **_k):
        raise ValueError("process-control: base ref must not be HEAD")

    monkeypatch.setattr(gate, "validate_process_base", refuse_head)
    err = gate.format_disable_check(tmp_path, base_ref="HEAD")
    assert err["ok"] is False
    assert err["level"] == "error"
    assert err["findings"] == []
    assert "HEAD" in err["message"]

    monkeypatch.setattr(gate, "validate_process_base", lambda *a, **k: None)
    monkeypatch.setattr(gate, "changed_python_files", lambda root, base: [])
    monkeypatch.setenv("PROCESS_BASE", "env-base-sha")
    used = gate.format_disable_check(tmp_path)
    assert used["base"] == "env-base-sha"
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    used2 = gate.format_disable_check(tmp_path)
    assert used2["base"] == "origin/main"


def test_changed_python_files_fail_closed(tmp_path: Path, monkeypatch):
    class Proc:
        def __init__(self, code: int, stderr: str = "", stdout: str = ""):
            self.returncode = code
            self.stderr = stderr
            self.stdout = stdout

    calls: list[list[str]] = []

    def fake_run(root: Path, args: list[str]) -> Proc:
        calls.append(args)
        return Proc(1, stderr="boom")

    monkeypatch.setattr(gate, "_run_git", fake_run)
    try:
        gate.changed_python_files(tmp_path, "origin/main")
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "git diff failed" in str(exc)
        assert "boom" in str(exc)
        assert gate.DOC in str(exc)
    assert raised is True
    assert len(calls) == 2


def test_changed_python_files_filters(tmp_path: Path, monkeypatch):
    class Proc:
        def __init__(self, code: int, stdout: str = ""):
            self.returncode = code
            self.stderr = ""
            self.stdout = stdout

    monkeypatch.setattr(
        gate,
        "_run_git",
        lambda root, args: Proc(0, stdout="a.py\nREADME.md\nb.PYI\n\nc.sh\n"),
    )
    assert gate.changed_python_files(tmp_path, "base") == ["a.py", "b.PYI"]


def test_git_show_and_read_head(tmp_path: Path, monkeypatch):
    class Proc:
        def __init__(self, code: int, stdout: str = ""):
            self.returncode = code
            self.stderr = ""
            self.stdout = stdout

    monkeypatch.setattr(gate, "_run_git", lambda root, args: Proc(1))
    assert gate.git_show_text(tmp_path, "rev", "missing.py") is None

    monkeypatch.setattr(gate, "_run_git", lambda root, args: Proc(0, stdout="BODY"))
    assert gate.git_show_text(tmp_path, "rev", "x.py") == "BODY"

    py = tmp_path / "x.py"
    py.write_text("from_disk\n", encoding="utf-8")
    assert gate.read_head_text(tmp_path, "x.py") == "from_disk\n"

    monkeypatch.setattr(gate, "git_show_text", lambda root, rev, path: "FROM_HEAD")
    assert gate.read_head_text(tmp_path, "nope.py") == "FROM_HEAD"

    monkeypatch.setattr(gate, "git_show_text", lambda root, rev, path: None)
    assert gate.read_head_text(tmp_path, "nope.py") == ""


def test_run_git_real_subprocess(tmp_path: Path):
    """Cover _run_git body (not only monkeypatched callers)."""
    subprocess_init = tmp_path / "repo"
    subprocess_init.mkdir()
    proc = gate._run_git(subprocess_init, ["git", "rev-parse", "--is-inside-work-tree"])
    assert proc.returncode != 0
    assert isinstance(proc.stdout, str)
    assert isinstance(proc.stderr, str)
