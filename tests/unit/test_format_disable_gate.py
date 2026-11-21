"""Unit + mutation oracles for format_disable_gate (T-261121-8c84)."""

from __future__ import annotations

from pathlib import Path

from agentized import format_disable_gate as gate


def _needle(*parts: str) -> str:
    """Build a banned lexeme without writing it as a contiguous comment in this file."""
    return "".join(parts)


def test_is_python_path():
    assert gate.is_python_path("runtime/agentized/x.py") is True
    assert gate.is_python_path("x.PY") is True
    assert gate.is_python_path("x.pyi") is True
    assert gate.is_python_path("docs/QUALITY.md") is False
    assert gate.is_python_path("script.sh") is False
    assert gate.is_python_path("") is False


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
    for sample in (
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
    ):
        assert gate.line_has_disable(sample) is True, sample
    for clean in ("x = 1", "print('hello')", "# comment about format", "# no qa typo"):
        assert gate.line_has_disable(clean) is False, clean


def test_parse_unified_added_hits_python_only_and_linenos():
    fmt_off = _needle("#", " fmt: ", "off")
    noqa = _needle("#", " noqa")
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,0 +10,2 @@\n"
        f"+x = 1  {fmt_off}\n"
        "+y = 2\n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,0 +1 @@\n"
        f"+docs mention {fmt_off}\n"
        "diff --git a/b.pyi b/b.pyi\n"
        "--- a/b.pyi\n"
        "+++ b/b.pyi\n"
        "@@ -3 +3 @@\n"
        f"+z: int  {noqa}\n"
    )
    hits = gate.parse_unified_added_hits(diff)
    assert hits == [
        ("a.py", 10, f"x = 1  {fmt_off}"),
        ("b.pyi", 3, f"z: int  {noqa}"),
    ]


def test_parse_unified_ignores_deletes_and_dev_null():
    fmt_off = _needle("#", " fmt: ", "off")
    diff = (
        "diff --git a/gone.py b/gone.py\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        f"-{fmt_off}\n"
        "diff --git a/keep.py b/keep.py\n"
        "--- a/keep.py\n"
        "+++ b/keep.py\n"
        "@@ -5,1 +5,1 @@\n"
        " context\n"
        f"-old {fmt_off}\n"
        "+clean = 1\n"
    )
    assert gate.parse_unified_added_hits(diff) == []


def test_format_findings_message_empty_and_nonempty():
    empty = gate.format_findings_message("origin/main", [])
    assert "adds 0" in empty
    assert "no allowlist" in empty
    assert gate.DOC in empty
    fmt_off = _needle("#", " fmt: ", "off")
    msg = gate.format_findings_message("abc", [("x.py", 4, f"  {fmt_off}  ")])
    assert "adds 1" in msg
    assert "x.py:4:" in msg
    assert fmt_off in msg


def test_format_disable_check_ok_and_fail(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gate, "validate_process_base", lambda *a, **k: None)
    monkeypatch.setattr(gate, "diff_unified", lambda root, base: "")
    ok = gate.format_disable_check(tmp_path, base_ref="origin/main")
    assert ok["ok"] is True
    assert ok["level"] == "ok"
    assert ok["findings"] == []
    assert "no new" in ok["message"]
    assert ok["base"] == "origin/main"

    fmt_off = _needle("#", " fmt: ", "off")
    dirty = f"--- a/x.py\n+++ b/x.py\n@@ -1,0 +1 @@\n+boom  {fmt_off}\n"
    monkeypatch.setattr(gate, "diff_unified", lambda root, base: dirty)
    bad = gate.format_disable_check(tmp_path, base_ref="deadbeef")
    assert bad["ok"] is False
    assert bad["level"] == "fail"
    assert bad["base"] == "deadbeef"
    assert len(bad["findings"]) == 1
    assert bad["findings"][0]["path"] == "x.py"
    assert bad["findings"][0]["line"] == 1
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
    monkeypatch.setattr(gate, "diff_unified", lambda root, base: "")
    monkeypatch.setenv("PROCESS_BASE", "env-base-sha")
    used = gate.format_disable_check(tmp_path)
    assert used["base"] == "env-base-sha"
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    # default when neither arg nor env
    used2 = gate.format_disable_check(tmp_path)
    assert used2["base"] == "origin/main"


def test_diff_unified_fail_closed(tmp_path: Path, monkeypatch):
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
        gate.diff_unified(tmp_path, "origin/main")
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "git diff failed" in str(exc)
        assert "boom" in str(exc)
        assert gate.DOC in str(exc)
    assert raised is True
    assert len(calls) == 2
    assert "--unified=0" in calls[0]
    assert "origin/main...HEAD" in calls[0]
    assert calls[1][-1] == "origin/main"


def test_diff_unified_ok_triple_then_fallback(tmp_path: Path, monkeypatch):
    class Proc:
        def __init__(self, code: int, stdout: str = ""):
            self.returncode = code
            self.stderr = ""
            self.stdout = stdout

    seq = [Proc(0, stdout="DIFF")]

    def fake_run(root: Path, args: list[str]) -> Proc:
        return seq.pop(0)

    monkeypatch.setattr(gate, "_run_git", fake_run)
    assert gate.diff_unified(tmp_path, "base") == "DIFF"

    seq.extend([Proc(1, stdout=""), Proc(0, stdout="TWO")])

    def fake_run2(root: Path, args: list[str]) -> Proc:
        return seq.pop(0)

    monkeypatch.setattr(gate, "_run_git", fake_run2)
    assert gate.diff_unified(tmp_path, "base") == "TWO"


def test_parse_plus_plus_plus_path_variants():
    noqa = _needle("#", " noqa")
    diff = f"+++ weird/path.py\n@@ -0,0 +2 @@\n+{noqa}\n"
    hits = gate.parse_unified_added_hits(diff)
    assert hits == [("weird/path.py", 2, noqa)]


def test_ci_invokes_format_disables_hard():
    root = Path(__file__).resolve().parents[2]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lines = [
        ln.strip()
        for ln in ci.splitlines()
        if "format-disables" in ln and not ln.strip().startswith("#") and "echo " not in ln
    ]
    assert lines == ['"${CLI[@]}" process format-disables']
    # Must sit in the same hard step as process size (PROCESS_BASE env).
    assert "PROCESS_BASE:" in ci
    assert "process format-disables" in ci
    # No soft bypass next to the invoke.
    for ln in ci.splitlines():
        if "format-disables" in ln:
            assert "|| true" not in ln
