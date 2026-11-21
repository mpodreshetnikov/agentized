"""Unit + mutation oracles for format_disable_gate (T-261121-8c84 REJECT pack)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentized import format_disable_gate as gate
from agentized import process_size as ps


def _needle(*parts: str) -> str:
    return "".join(parts)


def test_path_kind_classifiers():
    cases = [
        ("a.py", 1, 0, 0),
        ("a.pyw", 1, 0, 0),
        ("a.pyi", 1, 0, 0),
        ("a.ts", 0, 1, 0),
        ("x.mjs", 0, 1, 0),
        ("x.tsx", 0, 1, 0),
        ("pyproject.toml", 0, 0, 1),
        (".coveragerc", 0, 0, 1),
        (".eslintrc.yml", 0, 0, 1),
        (".prettierrc.yaml", 0, 0, 1),
        ("cfg/.eslintrc.json", 0, 0, 1),
        ("docs/QUALITY.md", 0, 0, 0),
        ("not-eslintrc", 0, 0, 0),
    ]
    got = [
        (
            p,
            1 if gate.is_python_path(p) else 0,
            1 if gate.is_js_path(p) else 0,
            1 if gate.is_config_path(p) else 0,
        )
        for p, *_ in cases
    ]
    assert got == cases
    assert [1 if gate.is_scannable_path(p) else 0 for p, *_ in cases] == [
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        0,
        0,
    ]


def test_line_has_disable_families():
    py_pos = [
        _needle("#", " fmt: ", "off"),
        _needle("#", " noqa"),
        _needle("#", " pragma: ", "no cover"),
        _needle("#", " pragma: ", "no mutate"),
        _needle("#", " type: ", "ignore"),
        _needle("#", " pylint: ", "disable=x"),
        _needle("#", " mypy: ", "ignore-errors"),
        _needle("#", " pyright: ", "ignore"),
    ]
    assert [1 if gate.line_has_disable(s) else 0 for s in py_pos] == [1] * len(py_pos)
    assert [1 if gate.line_has_disable(s) else 0 for s in ("x=1", "# no qa")] == [0, 0]
    js_pos = [
        "eslint-disable-next-line",
        "prettier-ignore",
        "@ts-ignore",
        "@ts-nocheck",
        "@ts-expect-error",
        "Stryker disable all",
    ]
    assert [1 if gate.line_has_js_disable(s) else 0 for s in js_pos] == [1] * len(js_pos)
    cfg = ["per-file-ignores =", "extend-exclude =", "exclude = [", "omit =", "paths_to_exclude"]
    assert [1 if gate.line_has_config_disable(s) else 0 for s in cfg] == [1] * len(cfg)


def test_disable_comments_in_source_ignores_strings():
    fmt_off = _needle("#", " fmt: ", "off")
    noqa = _needle("#", " noqa")
    src = f'"""docs {fmt_off}"""\ns = \'{fmt_off}\'\nx = 1  {fmt_off}\ny = 2  {noqa}\n'
    assert [(n, t.strip()) for n, t in gate.disable_comments_in_source(src)] == [
        (3, fmt_off),
        (4, noqa),
    ]


def test_disable_comments_untokenizeable_and_js_config():
    fmt_off = _needle("#", " fmt: ", "off")
    assert gate.disable_comments_in_source(f'"""\n{fmt_off}\n') == [(0, gate._UNTTOKEN_MSG)]
    assert gate.disable_comments_in_source('"""\nplain\n') == []
    js = "const x = 1;\n// eslint-disable-next-line no-var\nvar y = 2;\n"
    hits = gate.js_disable_comments_in_source(js)
    assert hits == [(2, "// eslint-disable-next-line no-var")]
    assert hits[0][1].startswith("//")
    # Trailing spaces: rstrip (not lstrip); full match group(0) keeps //.
    spaced = "code; // eslint-disable-next-line no-var   \n"
    spaced_hits = gate.js_disable_comments_in_source(spaced)
    assert spaced_hits == [(1, "// eslint-disable-next-line no-var")]
    assert not spaced_hits[0][1].endswith(" ")
    # Block after blank lines → count("\n", 0, start)+1
    block = "\n\n/* prettier-ignore */\nconst z = 1;\n"
    assert gate.js_disable_comments_in_source(block) == [(3, "/* prettier-ignore */")]
    long_inner = "prettier-ignore " + ("x" * 200)
    long_block = f"/* {long_inner} */\n"
    long_hits = gate.js_disable_comments_in_source(long_block)
    assert long_hits[0][0] == 1
    assert long_hits[0][1] == long_block.splitlines()[0][:120]
    assert len(long_hits[0][1]) == 120
    cfg = "  omit =  \n  src/skip.py\n"
    assert gate.config_disable_lines(cfg) == [(1, "  omit =")]
    assert gate.disables_in_file("a.py", f"x=1  {fmt_off}\n")[0][1].strip() == fmt_off
    assert gate.disables_in_file("a.ts", js)[0][0] == 2
    assert gate.disables_in_file("pyproject.toml", "per-file-ignores = {}\n")[0][0] == 1


def test_format_findings_message():
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
    two = gate.format_findings_message("b", [("a.py", 1, fmt_off), ("a.py", 2, fmt_off)])
    assert two.endswith(f"  a.py:1: {fmt_off}\n  a.py:2: {fmt_off}")


def test_parse_name_status_renames():
    raw = "A\tnew.py\nM\told.py\nR100\tfrom.py\tto.py\nC050\tc_old.ts\tc_new.ts\n"
    assert gate.parse_name_status(raw) == [
        ("new.py", None),
        ("old.py", "old.py"),
        ("to.py", "from.py"),
        ("c_new.ts", "c_old.ts"),
    ]
    # Blank lines skipped with continue (not break).
    assert gate.parse_name_status("\nA\tok.py\n") == [("ok.py", None)]
    # Incomplete R/C and M rows skipped with continue (not break).
    assert gate.parse_name_status("R100\tonly\nM\nA\tafter.py\n") == [("after.py", None)]
    # Tab split keeps spaces in path (split(None) would truncate).
    assert gate.parse_name_status("A\tmy file.py\n") == [("my file.py", None)]


def test_changed_scan_targets_git_args(tmp_path: Path, monkeypatch):
    class FakeProc:
        def __init__(self, code: int, stdout: str = "", stderr: str = ""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    calls: list[tuple] = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        if "..." in str(cmd):
            return FakeProc(128, stderr="no triple")
        return FakeProc(0, stdout="A\ta.py\nM\tb.ts\nA\tREADME.md\n")

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    assert gate.changed_scan_targets(tmp_path, "origin/main") == [
        ("a.py", None),
        ("b.ts", "b.ts"),
    ]
    assert len(calls) == 2
    assert calls[0][0] == [
        "git",
        "diff",
        "--name-status",
        "--find-renames",
        f"--diff-filter={gate._DIFF_FILTER}",
        f"origin/main...{gate._HEAD}",
    ]
    assert calls[1][0] == [
        "git",
        "diff",
        "--name-status",
        "--find-renames",
        f"--diff-filter={gate._DIFF_FILTER}",
        "origin/main",
    ]
    for _, kw in calls:
        assert kw["cwd"] == str(tmp_path)
        assert kw["capture_output"] is True
        assert kw["text"] is True
        assert kw["check"] is False


def test_changed_scan_targets_success_one_call(tmp_path: Path, monkeypatch):
    class FakeProc:
        def __init__(self, code: int, stdout: str = "", stderr: str = ""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return FakeProc(0, stdout="A\tz.py\n")

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    assert gate.changed_scan_targets(tmp_path, "base") == [("z.py", None)]
    assert len(calls) == 1
    assert calls[0][-1] == f"base...{gate._HEAD}"


def test_changed_scan_targets_fail_closed(tmp_path: Path, monkeypatch):
    class FakeProc:
        def __init__(self, code: int, stdout: str = "", stderr: str = ""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: FakeProc(7, "", ""))
    with pytest.raises(RuntimeError) as excinfo:
        gate.changed_scan_targets(tmp_path, "origin/main")
    assert str(excinfo.value) == (
        f"format-disable-gate: git diff failed for 'origin/main': exit 7. See {gate.DOC}."
    )

    # Prefer stderr over stdout when both set.
    monkeypatch.setattr(
        ps.subprocess, "run", lambda *a, **k: FakeProc(3, stdout="out-msg", stderr="err-msg")
    )
    with pytest.raises(RuntimeError) as e2:
        gate.changed_scan_targets(tmp_path, "b")
    assert str(e2.value) == (
        f"format-disable-gate: git diff failed for 'b': err-msg. See {gate.DOC}."
    )

    # stderr empty → stdout detail (or/and mutants).
    monkeypatch.setattr(
        ps.subprocess, "run", lambda *a, **k: FakeProc(9, stdout="only-out", stderr="")
    )
    with pytest.raises(RuntimeError) as e3:
        gate.changed_scan_targets(tmp_path, "c")
    assert str(e3.value) == (
        f"format-disable-gate: git diff failed for 'c': only-out. See {gate.DOC}."
    )


def test_git_show_text_utf8_and_missing(tmp_path: Path, monkeypatch):
    class FakeProc:
        def __init__(self, code: int, stdout: bytes = b""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = b""

    calls: list[tuple[object, list[str]]] = []

    def fake_bytes(root, args):
        calls.append((root, list(args)))
        return FakeProc(0, stdout=b"BODY")

    monkeypatch.setattr(gate, "_run_git_bytes", fake_bytes)
    assert gate.git_show_text(tmp_path, "rev", "x.py") == "BODY"
    assert calls == [(tmp_path, ["git", "show", "rev:x.py"])]

    monkeypatch.setattr(gate, "_run_git_bytes", lambda *a, **k: FakeProc(1))
    assert gate.git_show_text(tmp_path, "rev", "missing.py") is None

    monkeypatch.setattr(
        gate,
        "_run_git_bytes",
        lambda *a, **k: FakeProc(0, stdout=b"\xff\xfe bad"),
    )
    with pytest.raises(RuntimeError) as excinfo:
        gate.git_show_text(tmp_path, "HEAD", "bad.py")
    assert "bad.py" in str(excinfo.value)
    assert "non-UTF-8" in str(excinfo.value)


def test_run_git_bytes_kwargs(tmp_path: Path, monkeypatch):
    recorded: list[dict] = []

    class FakeProc:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(args, **kwargs):
        recorded.append({"args": list(args), **kwargs})
        return FakeProc()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    proc = gate._run_git_bytes(tmp_path, ["git", "status"])
    assert proc.returncode == 0
    assert len(recorded) == 1
    kw = recorded[0]
    assert kw["args"] == ["git", "status"]
    assert kw["cwd"] == str(tmp_path)
    assert kw["capture_output"] is True
    assert "check" in kw
    assert kw["check"] is False


def test_read_head_text_blob_only(tmp_path: Path, monkeypatch):
    show_calls: list[tuple[object, str, str]] = []

    def capture(root, rev, path):
        show_calls.append((root, rev, path))
        return "HEADBODY"

    monkeypatch.setattr(gate, "git_show_text", capture)
    # Even if WT file exists, must use HEAD blob only.
    (tmp_path / "y.py").write_text("WT\n", encoding="utf-8")
    assert gate.read_head_text(tmp_path, "y.py") == "HEADBODY"
    assert show_calls == [(tmp_path, gate._HEAD, "y.py")]
    monkeypatch.setattr(gate, "git_show_text", lambda *a, **k: None)
    assert gate.read_head_text(tmp_path, "nope.py") == ""


def test_new_disable_findings_rename_and_missing_base(tmp_path: Path, monkeypatch):
    fmt_off = _needle("#", " fmt: ", "off")
    noqa = _needle("#", " noqa")
    head_calls: list[tuple[object, str]] = []
    show_calls: list[tuple[object, str, str]] = []

    def fake_head(root, path):
        head_calls.append((root, path))
        return f"a  {fmt_off}\nb  {fmt_off}\nc  {noqa}\n"

    def fake_show(root, rev, path):
        show_calls.append((root, rev, path))
        if path == "old.py":
            return f"a  {fmt_off}\n"
        return None

    monkeypatch.setattr(gate, "read_head_text", fake_head)
    monkeypatch.setattr(gate, "git_show_text", fake_show)
    # Rename: base at old.py grandfathers one fmt_off.
    findings = gate.new_disable_findings(tmp_path, "origin/main", "new.py", "old.py")
    assert findings == [("new.py", 2, fmt_off), ("new.py", 3, noqa)]
    assert head_calls == [(tmp_path, "new.py")]
    assert show_calls == [(tmp_path, "origin/main", "old.py")]
    # Added file: base_path None → empty base.
    src_calls: list[str] = []
    real = gate.disables_in_file

    def spy(path, src):
        src_calls.append(src)
        return real(path, src)

    monkeypatch.setattr(gate, "disables_in_file", spy)
    show_calls.clear()
    head_calls.clear()
    all_new = gate.new_disable_findings(tmp_path, "origin/main", "new.py", None)
    assert len(all_new) == 3
    assert show_calls == []
    assert head_calls == [(tmp_path, "new.py")]
    assert src_calls[1] == ""

    # base_path set but blob missing → base_src must be "" (not None / not XXXX).
    src_calls.clear()
    show_calls.clear()
    missing = gate.new_disable_findings(tmp_path, "origin/main", "new.py", "gone.py")
    assert len(missing) == 3
    assert show_calls == [(tmp_path, "origin/main", "gone.py")]
    assert src_calls[1] == ""


def test_new_disable_findings_decrement_by_one(tmp_path: Path, monkeypatch):
    fmt_off = _needle("#", " fmt: ", "off")
    lines = "\n".join(f"x  {fmt_off}" for _ in range(4)) + "\n"
    base_lines = "\n".join(f"x  {fmt_off}" for _ in range(2)) + "\n"
    monkeypatch.setattr(gate, "read_head_text", lambda root, path: lines)
    monkeypatch.setattr(gate, "git_show_text", lambda root, rev, path: base_lines)
    findings = gate.new_disable_findings(tmp_path, "origin/main", "z.py", "z.py")
    assert findings == [("z.py", 3, fmt_off), ("z.py", 4, fmt_off)]


def test_format_disable_check_ok_fail_error(tmp_path: Path, monkeypatch):
    validate_calls: list[tuple[object, str]] = []
    target_calls: list[tuple[object, str]] = []
    finding_calls: list[tuple[object, str, str, str | None]] = []

    def spy_validate(root, base):
        validate_calls.append((root, base))

    def spy_targets(root, base):
        target_calls.append((root, base))
        return []

    monkeypatch.setattr(gate, "validate_process_base", spy_validate)
    monkeypatch.setattr(gate, "changed_scan_targets", spy_targets)
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
    assert target_calls == [(tmp_path, "origin/main")]

    fmt_off = _needle("#", " fmt: ", "off")
    validate_calls.clear()
    target_calls.clear()

    def spy_targets_one(root, base):
        target_calls.append((root, base))
        return [("x.py", "x.py")]

    def spy_findings(root, base, head, base_path):
        finding_calls.append((root, base, head, base_path))
        return [(head, 1, fmt_off)]

    monkeypatch.setattr(gate, "changed_scan_targets", spy_targets_one)
    monkeypatch.setattr(gate, "new_disable_findings", spy_findings)
    bad = gate.format_disable_check(tmp_path, base_ref="deadbeef")
    expected_msg = gate.format_findings_message("deadbeef", [("x.py", 1, fmt_off)])
    assert bad == {
        "ok": False,
        "level": "fail",
        "base": "deadbeef",
        "findings": [{"path": "x.py", "line": 1, "text": fmt_off}],
        "message": expected_msg,
    }
    assert set(bad.keys()) == {"ok", "level", "base", "findings", "message"}
    assert finding_calls == [(tmp_path, "deadbeef", "x.py", "x.py")]

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
    monkeypatch.setattr(gate, "changed_scan_targets", spy_targets)
    validate_calls.clear()
    monkeypatch.setenv("PROCESS_BASE", "env-base-sha")
    assert gate.format_disable_check(tmp_path)["base"] == "env-base-sha"
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    assert gate.format_disable_check(tmp_path)["base"] == gate.DEFAULT_BASE


def test_format_disable_check_runtime_error(tmp_path: Path, monkeypatch):
    validate_calls: list[tuple[object, str]] = []

    def spy_validate(root, base):
        validate_calls.append((root, base))

    def boom(root, base):
        raise RuntimeError("format-disable-gate: git diff failed")

    monkeypatch.setattr(gate, "validate_process_base", spy_validate)
    monkeypatch.setattr(gate, "changed_scan_targets", boom)
    err = gate.format_disable_check(tmp_path, base_ref="origin/main")
    assert err["message"] == "format-disable-gate: git diff failed"
    assert validate_calls == [(tmp_path, "origin/main")]


def test_constants():
    assert gate.DOC == "docs/QUALITY.md"
    assert gate.DEFAULT_BASE == "origin/main"
    assert gate._FILE_ENCODING == "utf-8"
    assert gate._DIFF_FILTER == "ACMR"
    assert gate._HEAD == "HEAD"
    assert "pyproject.toml" in gate._CONFIG_NAMES
    assert ".eslintrc.yml" in gate._CONFIG_NAMES


def test_changed_python_files_filters(tmp_path: Path, monkeypatch):
    target_calls: list[tuple[object, str]] = []

    def spy(root, base):
        target_calls.append((root, base))
        return [("a.py", None), ("b.ts", "b.ts"), ("c.pyw", "c.pyw")]

    monkeypatch.setattr(gate, "changed_scan_targets", spy)
    assert gate.changed_python_files(tmp_path, "base") == ["a.py", "c.pyw"]
    assert target_calls == [(tmp_path, "base")]


def test_run_git_bytes_real(tmp_path: Path):
    proc = gate._run_git_bytes(tmp_path, ["git", "rev-parse", "--is-inside-work-tree"])
    assert proc.returncode != 0
    assert isinstance(proc.stdout, (bytes, bytearray))
