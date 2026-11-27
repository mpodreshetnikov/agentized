"""AGE-85: consumer first-push preflight around coverage / mutation / format-disable gates."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentized import coverage_check, format_disable_gate, gate_preflight, mutation_ast
from agentized.gate_preflight import (
    module_layout_error,
    run_coverage_gate,
    run_format_disable_check,
    run_mutation_gate,
)
from agentized.process_size import EMPTY_TREE


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    return root


def _commit_all(root: Path, msg: str = "c") -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", msg)
    return _git(root, "rev-parse", "HEAD")


def _write_quality(root: Path, data: dict, context: str = "ctx") -> None:
    (root / context).mkdir(parents=True, exist_ok=True)
    (root / context / "quality.json").write_text(json.dumps(data), encoding="utf-8")


# --- module_layout_error -------------------------------------------------------


def test_layout_missing_source_exact_message(tmp_path: Path):
    module = {"id": "m", "source": ["src"], "test_command": "pytest tests"}
    assert module_layout_error(tmp_path, module) == (
        "[coverage-check] FAIL m: source path 'src' missing. "
        "Fix context/quality.json modules (re-run connect on a detected "
        "src/tests layout, or remove stale dogfood entries)."
    )


def test_layout_missing_id_uses_question_mark(tmp_path: Path):
    err = module_layout_error(tmp_path, {"source": ["gone"]})
    assert err is not None
    assert err.startswith("[coverage-check] FAIL ?: source path 'gone' missing. ")


def test_layout_second_source_missing_is_named(tmp_path: Path):
    (tmp_path / "a").mkdir()
    err = module_layout_error(tmp_path, {"id": "x", "source": ["a", "b"]})
    assert err is not None
    assert err.startswith("[coverage-check] FAIL x: source path 'b' missing. ")


def test_layout_missing_test_paths_sorted_unique_exact(tmp_path: Path):
    (tmp_path / "src").mkdir()
    module = {
        "id": "src",
        "source": ["src"],
        "test_command": "python3 -m pytest tests/unit test tests/unit tests/quality -q",
    }
    assert module_layout_error(tmp_path, module) == (
        "[coverage-check] FAIL src: test path(s) ['test', 'tests/quality', 'tests/unit'] "
        "missing on disk. Add tests or edit context/quality.json modules."
    )


def test_layout_plain_tests_token_missing(tmp_path: Path):
    (tmp_path / "src").mkdir()
    module = {"id": "s", "source": ["src"], "test_command": "tests"}
    assert module_layout_error(tmp_path, module) == (
        "[coverage-check] FAIL s: test path(s) ['tests'] "
        "missing on disk. Add tests or edit context/quality.json modules."
    )


def test_layout_passes_when_paths_present_or_absent_from_command(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests" / "quality").mkdir(parents=True)
    modules = [
        {"id": "s", "source": ["src"], "test_command": "pytest tests/unit tests/quality"},
        {"id": "t", "test_command": "pytest"},
        {"id": "s", "source": ["src"]},
    ] + [
        {"id": "s", "source": ["src"], "test_command": cmd}
        for cmd in ("pytest -q", "make check", "pytest mytests", "pytest tests_x")
    ]
    assert [module_layout_error(tmp_path, m) for m in modules] == [None] * len(modules)


# --- run_coverage_gate ---------------------------------------------------------


def _forbid(*_a, **_k):
    raise AssertionError("must not be called")


def test_coverage_gate_empty_modules_skips(tmp_path: Path, monkeypatch, capsys):
    _write_quality(tmp_path, {"modules": []})
    monkeypatch.setattr(coverage_check, "run_coverage_check", _forbid)
    assert run_coverage_gate(tmp_path, context="ctx") == 0
    out = capsys.readouterr()
    assert out.out == (
        "[coverage-check] no modules configured — skip module tests and "
        "coverage thresholds (valid empty consumer quality.json)\n"
    )
    assert out.err == ""


def test_coverage_gate_layout_error_fails_closed(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "ok").mkdir()
    _write_quality(
        tmp_path,
        {"modules": [{"id": "a", "source": ["ok"]}, {"id": "b", "source": ["gone"]}]},
    )
    monkeypatch.setattr(coverage_check, "run_coverage_check", _forbid)
    assert run_coverage_gate(tmp_path, context="ctx") == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == module_layout_error(tmp_path, {"id": "b", "source": ["gone"]}) + "\n"


def test_coverage_gate_delegates_with_context(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "src").mkdir()
    _write_quality(tmp_path, {"modules": [{"id": "s", "source": ["src"]}]})
    seen: list[tuple] = []

    def spy(root, *, context):
        seen.append((root, context))
        return 7

    monkeypatch.setattr(coverage_check, "run_coverage_check", spy)
    assert run_coverage_gate(tmp_path, context="ctx") == 7
    assert seen == [(tmp_path, "ctx")]
    assert capsys.readouterr().out == ""


# --- run_mutation_gate ---------------------------------------------------------


def _summary(root: Path) -> dict:
    return json.loads((root / "reports" / "mutation" / "mutation-summary.json").read_text())


def _assert_skip(root: Path, base: str, out: str) -> None:
    note = f"mutation base {base!r} unavailable — skip until remote baseline exists"
    data = _summary(root)
    generated = datetime.fromisoformat(data.pop("generatedAt"))
    assert generated.utcoffset() == timedelta(0)
    assert abs(datetime.now(timezone.utc) - generated) < timedelta(minutes=1)
    assert data == {
        "schemaVersion": 1,
        "mode": "incremental-skip",
        "base": base,
        "gate": "hard",
        "passed": True,
        "note": note,
    }
    assert out == f"[mutation] skip — {note}; wrote reports/mutation/mutation-summary.json\n"


def test_mutation_gate_env_base_missing_skips(tmp_path: Path, monkeypatch, capsys):
    root = _repo(tmp_path / "r")
    _write_quality(root, {"mutation": {"base_ref": "cfgbase"}})
    monkeypatch.setenv("MUTATION_BASE", "nope")
    monkeypatch.setattr(mutation_ast, "run_mutation", _forbid)
    assert run_mutation_gate(root, context="ctx") == 0
    _assert_skip(root, "nope", capsys.readouterr().out)


def test_mutation_gate_cfg_base_when_env_unset(tmp_path: Path, monkeypatch, capsys):
    root = _repo(tmp_path / "r")
    _write_quality(root, {"mutation": {"base_ref": "cfgbase"}})
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    monkeypatch.setattr(mutation_ast, "run_mutation", _forbid)
    assert run_mutation_gate(root, context="ctx") == 0
    _assert_skip(root, "cfgbase", capsys.readouterr().out)


def test_mutation_gate_defaults_to_origin_main(tmp_path: Path, monkeypatch, capsys):
    root = _repo(tmp_path / "r")
    _write_quality(root, {"mutation": {"base_ref": None}})
    monkeypatch.setenv("MUTATION_BASE", "")
    monkeypatch.setattr(mutation_ast, "run_mutation", _forbid)
    assert run_mutation_gate(root, context="ctx") == 0
    _assert_skip(root, "origin/main", capsys.readouterr().out)


def test_mutation_gate_existing_base_delegates(tmp_path: Path, monkeypatch, capsys):
    root = _repo(tmp_path / "r")
    (root / "f").write_text("x\n", encoding="utf-8")
    sha = _commit_all(root)
    _write_quality(root, {"mutation": {"base_ref": "nope"}})
    monkeypatch.setenv("MUTATION_BASE", sha)
    seen: list[tuple] = []

    def spy(root_, *, context):
        seen.append((root_, context))
        return 5

    monkeypatch.setattr(mutation_ast, "run_mutation", spy)
    assert run_mutation_gate(root, context="ctx") == 5
    assert seen == [(root, "ctx")]
    assert not (root / "reports").exists()
    assert capsys.readouterr().out == ""


# --- run_format_disable_check --------------------------------------------------

_NOQA = "# no" + "qa: E501"


def _spy_check(seen: list):
    def spy(root, *, base_ref=None):
        seen.append((root, base_ref))
        return {"ok": True, "spy": True}

    return spy


def test_format_disable_non_default_base_delegates(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path / "r")
    seen: list = []
    monkeypatch.setattr(format_disable_gate, "format_disable_check", _spy_check(seen))
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    assert run_format_disable_check(root, base_ref="abc") == {"ok": True, "spy": True}
    monkeypatch.setenv("PROCESS_BASE", "xyz")
    assert run_format_disable_check(root) == {"ok": True, "spy": True}
    assert seen == [(root, "abc"), (root, None)]


def test_format_disable_existing_origin_main_delegates(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path / "r")
    (root / "f").write_text("x\n", encoding="utf-8")
    sha = _commit_all(root)
    _git(root, "update-ref", "refs/remotes/origin/main", sha)
    seen: list = []
    monkeypatch.setattr(format_disable_gate, "format_disable_check", _spy_check(seen))
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    assert run_format_disable_check(root) == {"ok": True, "spy": True}
    assert seen == [(root, None)]


def test_format_disable_first_push_scans_whole_tree(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path / "r")
    (root / "a.py").write_text(f"x = 1  {_NOQA}\n", encoding="utf-8")
    (root / "b.py").write_text("y = 2\n", encoding="utf-8")
    _commit_all(root)
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    orig = format_disable_gate.validate_process_base
    result = run_format_disable_check(root)
    assert format_disable_gate.validate_process_base is orig
    assert result["ok"] is False
    assert result["level"] == "fail"
    assert result["base"] == EMPTY_TREE
    assert result["findings"] == [{"path": "a.py", "line": 1, "text": _NOQA}]


def test_format_disable_first_push_clean_tree_ok(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path / "r")
    (root / "b.py").write_text("y = 2\n", encoding="utf-8")
    _commit_all(root)
    monkeypatch.setenv("PROCESS_BASE", "origin/main")
    result = run_format_disable_check(root, base_ref="origin/main")
    assert result["ok"] is True
    assert result["base"] == EMPTY_TREE


def test_format_disable_restores_ancestry_check_on_error(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path / "r")
    (root / "b.py").write_text("y = 2\n", encoding="utf-8")
    _commit_all(root)
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    orig = format_disable_gate.validate_process_base

    def boom(root_, base_ref):
        assert format_disable_gate.validate_process_base == gate_preflight._no_ancestry_check
        raise KeyError(base_ref)

    monkeypatch.setattr(format_disable_gate, "changed_scan_targets", boom)
    with pytest.raises(KeyError):
        run_format_disable_check(root)
    assert format_disable_gate.validate_process_base == orig
