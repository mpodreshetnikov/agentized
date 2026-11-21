"""AST-equivalent mutation exclusion (AGE-55 / Option A)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agentized import mutation_ast as mast

BASE_SRC = "def f():\n    return 1 + 1\n"
FORMAT_ONLY = "def f():\n  return 1+1\n"
SEMANTIC = "def f():\n    return 1 + 2\n"
DOC_A = 'def f():\n    """alpha"""\n    return 1\n'
DOC_B = 'def f():\n    """beta"""\n    return 1\n'
BAD_SRC = "def f(\n"


def test_ast_dump_format_equal_semantic_and_doc_differ(monkeypatch):
    dump = mast.ast_dump(BASE_SRC)
    assert dump == mast.ast_dump(FORMAT_ONLY)
    assert dump != mast.ast_dump(SEMANTIC)
    assert mast.ast_dump(DOC_A) != mast.ast_dump(DOC_B)
    assert mast.ast_dump(BAD_SRC) is None
    assert "lineno" not in dump
    assert "col_offset" not in dump
    # Kill include_attributes=None / omitted mutants (equiv on 3.12 dump output).
    calls: list[object] = []
    real_dump = __import__("ast").dump

    def spy_dump(node, *a, **k):
        calls.append(k.get("include_attributes", "MISSING"))
        return real_dump(node, *a, **k)

    monkeypatch.setattr(mast.ast, "dump", spy_dump)
    assert mast.ast_dump(BASE_SRC) is not None
    assert calls == [False]


def test_exclude_a_format_only(tmp_path: Path, monkeypatch):
    """(a) format-only / AST-noop → excluded."""
    rel = "runtime/agentized/sample.py"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(FORMAT_ONLY, encoding="utf-8")
    calls: list[tuple] = []

    def spy(root, ref, path):
        calls.append((root, ref, path))
        return BASE_SRC

    monkeypatch.setattr(mast, "git_show_blob", spy)
    kept, excluded = mast.exclude_ast_equivalent(tmp_path, "origin/main", [rel])
    assert kept == []
    assert excluded == [rel]
    assert calls == [(tmp_path, "origin/main", rel)]


def test_exclude_b_semantic_stays(tmp_path: Path, monkeypatch):
    """(b) semantic edit stays in scope."""
    rel = "runtime/agentized/sample.py"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(SEMANTIC, encoding="utf-8")
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: BASE_SRC)
    kept, excluded = mast.exclude_ast_equivalent(tmp_path, "origin/main", [rel])
    assert kept == [rel]
    assert excluded == []


def test_exclude_c_docstring_stays(tmp_path: Path, monkeypatch):
    """(c) docstring text change stays (AST Constant differs)."""
    rel = "runtime/agentized/sample.py"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(DOC_B, encoding="utf-8")
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: DOC_A)
    kept, excluded = mast.exclude_ast_equivalent(tmp_path, "origin/main", [rel])
    assert kept == [rel]
    assert excluded == []


def test_exclude_d_new_file_stays(tmp_path: Path, monkeypatch):
    """(d) missing base (new file) → stay; never silent exclude."""
    rel = "runtime/agentized/newmod.py"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(BASE_SRC, encoding="utf-8")
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: None)
    kept, excluded = mast.exclude_ast_equivalent(tmp_path, "origin/main", [rel])
    assert kept == [rel]
    assert excluded == []


def test_exclude_e_unparseable_fail_closed(tmp_path: Path, monkeypatch):
    """(e) unparseable either side → stay in scope."""
    rel = "runtime/agentized/broken.py"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(BAD_SRC, encoding="utf-8")
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: BASE_SRC)
    kept, excluded = mast.exclude_ast_equivalent(tmp_path, "origin/main", [rel])
    assert kept == [rel]
    assert excluded == []

    (tmp_path / rel).write_text(BASE_SRC, encoding="utf-8")
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: BAD_SRC)
    kept2, excluded2 = mast.exclude_ast_equivalent(tmp_path, "origin/main", [rel])
    assert kept2 == [rel]
    assert excluded2 == []


def test_exclude_continue_not_break_on_multi(tmp_path: Path, monkeypatch):
    """continue→break mutant: first missing must not stop second exclude."""
    missing = "runtime/agentized/missing.py"
    fmt = "runtime/agentized/fmt.py"
    (tmp_path / fmt).parent.mkdir(parents=True)
    (tmp_path / fmt).write_text(FORMAT_ONLY, encoding="utf-8")
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: BASE_SRC)
    kept, excluded = mast.exclude_ast_equivalent(
        tmp_path, "origin/main", [missing, fmt]
    )
    assert kept == [missing]
    assert excluded == [fmt]


def test_exclude_parse_continue_not_break(tmp_path: Path, monkeypatch):
    """Parse-None continue→break must not drop a later exclude (base or head)."""
    bad_head = "runtime/agentized/bad_head.py"
    bad_base = "runtime/agentized/bad_base.py"
    fmt = "runtime/agentized/fmt.py"
    (tmp_path / bad_head).parent.mkdir(parents=True)
    (tmp_path / bad_head).write_text(BAD_SRC, encoding="utf-8")
    (tmp_path / bad_base).write_text(BASE_SRC, encoding="utf-8")
    (tmp_path / fmt).write_text(FORMAT_ONLY, encoding="utf-8")

    def blob(_root, _ref, path):
        if path == bad_base:
            return BAD_SRC
        return BASE_SRC

    monkeypatch.setattr(mast, "git_show_blob", blob)
    # Head parse fail first, then format exclude.
    kept, excluded = mast.exclude_ast_equivalent(
        tmp_path, "origin/main", [bad_head, fmt]
    )
    assert kept == [bad_head]
    assert excluded == [fmt]
    # Base parse fail first (base_key is None → continue, not break).
    kept2, excluded2 = mast.exclude_ast_equivalent(
        tmp_path, "origin/main", [bad_base, fmt]
    )
    assert kept2 == [bad_base]
    assert excluded2 == [fmt]


def test_exclude_base_parse_none_skips_head_dump(tmp_path: Path, monkeypatch):
    """If base AST dump fails, keep and do not dump head."""
    rel = "runtime/agentized/x.py"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(BASE_SRC, encoding="utf-8")
    real = mast.ast_dump
    state = {"n": 0}

    def spy(source: str):
        state["n"] += 1
        if state["n"] == 1:
            return None
        return real(source)

    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: BASE_SRC)
    monkeypatch.setattr(mast, "ast_dump", spy)
    kept, excluded = mast.exclude_ast_equivalent(tmp_path, "origin/main", [rel])
    assert kept == [rel]
    assert excluded == []
    assert state["n"] == 1


def test_exclude_head_unreadable_stays(tmp_path: Path, monkeypatch):
    """Fail-closed: head read error keeps file."""
    rel = "runtime/agentized/missing.py"
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: BASE_SRC)
    kept, excluded = mast.exclude_ast_equivalent(tmp_path, "origin/main", [rel])
    assert kept == [rel]
    assert excluded == []


def test_git_show_blob_missing_and_ok(tmp_path: Path):
    assert mast.git_show_blob(tmp_path, "origin/main", "no/such.py") is None

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    rel = "mod.py"
    (tmp_path / rel).write_text(BASE_SRC, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert mast.git_show_blob(tmp_path, "HEAD", rel) == BASE_SRC
    assert mast.git_show_blob(tmp_path, "HEAD", "gone.py") is None


def test_read_workdir_blob_ok_error_unicode(tmp_path: Path, monkeypatch):
    rel = "x.py"
    (tmp_path / rel).write_text("x = 1\n", encoding="utf-8")
    enc_calls: list[object] = []
    real = Path.read_text

    def spy(self, *a, **k):
        enc_calls.append(k.get("encoding", a[0] if a else "MISSING"))
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy)
    assert mast.read_workdir_blob(tmp_path, rel) == "x = 1\n"
    assert enc_calls == ["utf-8"]
    assert mast.read_workdir_blob(tmp_path, "absent.py") is None

    def boom(self, *a, **k):
        if self.name == rel:
            raise UnicodeError("bad")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", boom)
    assert mast.read_workdir_blob(tmp_path, rel) is None


def _gate_cfg():
    return {
        "mutation": {
            "enabled": True,
            "min_score_covered": 100,
            "break_on_survived": True,
            "break_on_no_tests": False,
            "include_globs": ["runtime/agentized/*.py"],
            "base_ref": "origin/main",
        },
        "modules": [{"source": ["runtime/agentized"]}],
    }


def test_run_mutation_a_all_ast_noop_skips(tmp_path: Path, monkeypatch, capsys):
    """(a via gate) all AST-noop → incremental-skip; excluded logged."""
    (tmp_path / "context").mkdir()
    rel = "runtime/agentized/fmt.py"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(FORMAT_ONLY, encoding="utf-8")

    from agentized import mutation as mut

    load_calls: list[tuple] = []
    changed_calls: list[tuple] = []
    exclude_refs: list[object] = []

    def load(root, context):
        load_calls.append((root, context))
        return _gate_cfg()

    def changed(root, base_ref, prefixes):
        changed_calls.append((root, base_ref, list(prefixes)))
        return [rel]

    real_exclude = mast.exclude_ast_equivalent

    def spy_exclude(root, base_ref, paths):
        exclude_refs.append(base_ref)
        return real_exclude(root, base_ref, paths)

    monkeypatch.delenv("MUTATION_BASE", raising=False)
    monkeypatch.setattr(mut, "load_quality", load)
    monkeypatch.setattr(mut, "_changed_py_files", changed)
    monkeypatch.setattr(mast, "exclude_ast_equivalent", spy_exclude)
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: BASE_SRC)
    monkeypatch.setattr(mut, "find_repo_root", lambda: tmp_path / "WRONG")
    monkeypatch.chdir(tmp_path)

    orig_changed = mut._changed_py_files
    assert mast.run_mutation(tmp_path, context="ctx-a") == 0
    # finally must restore patches (kill `_changed_py_files = None`).
    assert mut._changed_py_files is orig_changed
    assert load_calls[0] == (tmp_path, "ctx-a")
    assert changed_calls[0][0] == tmp_path
    assert changed_calls[0][1] == "origin/main"
    assert changed_calls[0][2] == ["runtime/agentized"]
    assert exclude_refs == ["origin/main"]

    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["mode"] == "incremental-skip"
    assert summary.get("changedFiles", []) == []
    assert summary["astExcludedFiles"] == [rel]
    assert summary["passed"] is True
    out = capsys.readouterr().out
    assert "[mutation] AST-equivalent excluded (1):" in out
    assert f"  exclude {rel}" in out


def test_run_mutation_root_none_uses_find(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    rel = "runtime/agentized/fmt.py"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(FORMAT_ONLY, encoding="utf-8")

    from agentized import mutation as mut

    monkeypatch.setattr(mut, "load_quality", lambda *a, **k: _gate_cfg())
    monkeypatch.setattr(mut, "_changed_py_files", lambda *a, **k: [rel])
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: BASE_SRC)
    monkeypatch.setattr(mut, "find_repo_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    assert mast.run_mutation(None) == 0
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["astExcludedFiles"] == [rel]


def test_run_mutation_f_logic_still_fails_survivors(tmp_path: Path, monkeypatch, capsys):
    """(f) logic-only remains; gate still fails closed on survivors."""
    (tmp_path / "context").mkdir()
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    fmt = "runtime/agentized/fmt.py"
    logic = "runtime/agentized/logic.py"
    for rel, body in ((fmt, FORMAT_ONLY), (logic, SEMANTIC)):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body, encoding="utf-8")
    (tmp_path / "setup.cfg").write_text("[mutmut]\n", encoding="utf-8")

    from agentized import mutation as mut

    monkeypatch.setattr(mut, "load_quality", lambda *a, **k: _gate_cfg())
    monkeypatch.setattr(mut, "_changed_py_files", lambda *a, **k: [fmt, logic])
    monkeypatch.setattr(mut, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        mast,
        "git_show_blob",
        lambda root, ref, path: BASE_SRC if path in (fmt, logic) else None,
    )
    monkeypatch.setattr(mut, "_ensure_agentized_link", lambda root: False)

    mutmut_only: list[list[str]] = []

    def capture_setup(root, only):  # noqa: ARG001
        mutmut_only.append(list(only))
        (root / "setup.cfg").write_text("[mutmut]\n", encoding="utf-8")

    monkeypatch.setattr(mut, "_write_setup", capture_setup)

    def fake_run(cmd, **kwargs):  # noqa: ARG001
        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(mut.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mut,
        "_collect_stats",
        lambda root: {  # noqa: ARG001
            "killed": 0,
            "survived": 2,
            "no_tests": 0,
            "timeout": 0,
            "other": 0,
            "totalMutants": 2,
            "files": ["logic.meta"],
            "mutationScore": 0.0,
            "mutationScoreCovered": 0.0,
        },
    )
    monkeypatch.chdir(tmp_path)
    rc = mast.run_mutation(tmp_path, context="ctx-f")
    assert rc == 1
    assert mutmut_only == [["agentized/logic.py"]]
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["passed"] is False
    assert summary["changedFiles"] == [logic]
    assert summary["astExcludedFiles"] == [fmt]
    assert any("survived=" in r for r in summary["reasons"])
    out = capsys.readouterr().out
    assert f"  exclude {fmt}" in out


def test_run_mutation_no_exclude_still_enriches_summary(tmp_path: Path, monkeypatch):
    """No AST exclusions → empty astExcludedFiles; gate still runs."""
    (tmp_path / "context").mkdir()
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    logic = "runtime/agentized/logic.py"
    (tmp_path / logic).parent.mkdir(parents=True)
    (tmp_path / logic).write_text(SEMANTIC, encoding="utf-8")
    (tmp_path / "setup.cfg").write_text("[mutmut]\n", encoding="utf-8")

    from agentized import mutation as mut

    monkeypatch.setattr(mut, "load_quality", lambda *a, **k: _gate_cfg())
    monkeypatch.setattr(mut, "_changed_py_files", lambda *a, **k: [logic])
    monkeypatch.setattr(mast, "git_show_blob", lambda *a, **k: BASE_SRC)
    monkeypatch.setattr(mut, "_ensure_agentized_link", lambda root: False)
    monkeypatch.setattr(mut, "_write_setup", lambda root, only: (root / "setup.cfg").write_text("[mutmut]\n", encoding="utf-8"))
    monkeypatch.setattr(
        mut.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0})(),
    )
    monkeypatch.setattr(
        mut,
        "_collect_stats",
        lambda root: {
            "killed": 1,
            "survived": 0,
            "no_tests": 0,
            "timeout": 0,
            "other": 0,
            "totalMutants": 1,
            "files": [],
            "mutationScore": 100.0,
            "mutationScoreCovered": 100.0,
        },
    )
    monkeypatch.chdir(tmp_path)
    assert mast.run_mutation(tmp_path) == 0
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["astExcludedFiles"] == []
    assert summary["changedFiles"] == [logic]


def test_main_context_flag_and_argv(monkeypatch):
    called: list[str] = []

    def fake_run(root=None, *, context=mast.DEFAULT_CONTEXT):  # noqa: ARG001
        called.append(context)
        return 7

    monkeypatch.setattr(mast, "run_mutation", fake_run)
    assert mast.main(["--context", "ctx"]) == 7
    assert called == ["ctx"]
    # index+1 (not -1): value after the flag, not the token before it.
    assert mast.main(["noise", "--context", "ctx2"]) == 7
    assert called == ["ctx", "ctx2"]
    # Empty argv list must not fall through to sys.argv.
    monkeypatch.setattr(sys, "argv", ["prog", "--context", "from-sys"])
    assert mast.main([]) == 7
    assert called == ["ctx", "ctx2", mast.DEFAULT_CONTEXT]
    assert mast.main(None) == 7
    assert called == ["ctx", "ctx2", mast.DEFAULT_CONTEXT, "from-sys"]

