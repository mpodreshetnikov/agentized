from __future__ import annotations

import json
from pathlib import Path

from agentized import test_smells as smells


def test_weak_oracle_and_mock_call_only(tmp_path: Path, monkeypatch):
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_weak.py").write_text(
        "def test_weak():\n    x = 1\n    assert x\n    assert x is not None\n    assert not y\n",
        encoding="utf-8",
    )
    (tests / "test_mock_only.py").write_text(
        "def test_mock_only(m):\n    m.assert_called_once()\n",
        encoding="utf-8",
    )
    (tests / "test_ok.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )
    (tests / "test_patch.py").write_text(
        "from unittest.mock import patch\n"
        "@patch('agentized.quality.load_quality')\n"
        "def test_patched(m):\n"
        "    assert 1 == 1\n",
        encoding="utf-8",
    )
    (tests / "test_eq_none.py").write_text(
        "def test_eq_none():\n    x = None\n    assert x == None\n",
        encoding="utf-8",
    )
    (tests / "broken.py").write_text("def (\n", encoding="utf-8")
    monkeypatch.setattr(
        smells,
        "load_quality",
        lambda *a, **k: {
            "test_smells": {
                "enabled": True,
                "mode": "warn",
                "include_globs": ["tests/unit/**/*.py"],
            }
        },
    )
    assert smells.run_test_smells(tmp_path) == 0
    summary = json.loads(
        (tmp_path / "reports/test-smells/test-smells-summary.json").read_text(encoding="utf-8")
    )
    kinds = {f["kind"] for f in summary["findings"]}
    assert "weak_primary_oracle" in kinds
    assert "mock_call_only" in kinds
    assert "patch_decorator" in kinds
    assert "syntax_error" in kinds


def test_smells_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(smells, "load_quality", lambda *a, **k: {"test_smells": {"enabled": False}})
    assert smells.run_test_smells(tmp_path) == 0


def test_smells_hard_fails(tmp_path: Path, monkeypatch):
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_weak.py").write_text(
        "def test_weak():\n    assert True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        smells,
        "load_quality",
        lambda *a, **k: {
            "test_smells": {
                "enabled": True,
                "mode": "hard",
                "include_globs": ["tests/unit/**/*.py"],
            }
        },
    )
    assert smells.run_test_smells(tmp_path) == 1


def test_smells_hard_pass_clean(tmp_path: Path, monkeypatch):
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_ok.py").write_text("def test_ok():\n    assert 2 == 2\n", encoding="utf-8")
    monkeypatch.setattr(
        smells,
        "load_quality",
        lambda *a, **k: {
            "test_smells": {
                "enabled": True,
                "mode": "hard",
                "include_globs": ["tests/unit/**/*.py"],
            }
        },
    )
    assert smells.run_test_smells(tmp_path) == 0


def test_glob_match_variants():
    assert smells._glob_match("tests/unit/a.py", "tests/unit/**/*.py")
    assert smells._glob_match("a/b/c.py", "**/c.py")
    assert smells._glob_match("c.py", "**/c.py")
    assert smells._glob_match("tests/unit/a.py", "tests/unit/*.py")
    assert not smells._glob_match("docs/x.md", "tests/**/*.py")
    assert smells._glob_match("pkg/tests/test_a.py", "**/test_*.py")
    assert smells._glob_match("src/a/b.py", "src/**/b.py")
    assert not smells._glob_match("x.py", "plain")


def test_call_name_and_weak_helpers():
    import ast

    assert smells._call_name(ast.parse("foo.bar.baz", mode="eval").body) == "foo.bar.baz"
    assert smells._call_name(ast.parse("42", mode="eval").body) == ""
    node = ast.parse("assert x in y").body[0]
    assert smells._is_weak_assert(node)
    node2 = ast.parse("assert x == False").body[0]
    assert smells._is_weak_assert(node2)
    node3 = ast.parse("assert 1 + 1 == 2").body[0]
    assert not smells._is_weak_assert(node3)
    assert not smells._is_mock_assert_call(ast.parse("x = 1").body[0])


def test_count_and_int_bool_bypass_helpers():
    """Detector must catch membership/truthiness disguised as count/int/bool."""
    import ast

    weak_srcs = [
        'assert text.count("x") >= 1',
        'assert text.count("x") > 0',
        'assert text.count("CUSTOM") == 0',
        "assert int(flag) == 1",
        "assert int(flag) == 0",
        "assert bool(flag) == True",
        "assert bool(flag) == False",
    ]
    for src in weak_srcs:
        node = ast.parse(src).body[0]
        assert smells._is_weak_assert(node), src

    strong_srcs = [
        'assert text.count("x") == 1',  # exact multiplicity is an oracle
        'assert text.count("x") == 2',
        "assert int(n) == 3",
        'assert lines[0] == "[mutmut]"',
        'assert result["message"].startswith("agent-env-check: REFUSED")',
        "assert watched == [True, False, False, True]",
    ]
    for src in strong_srcs:
        node = ast.parse(src).body[0]
        assert not smells._is_weak_assert(node), src


def test_smells_hard_flags_count_and_int_bypasses(tmp_path: Path, monkeypatch):
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_count_bypass.py").write_text(
        "def test_count_bypass():\n"
        '    text = "hello"\n'
        '    assert text.count("h") >= 1\n'
        '    assert text.count("z") == 0\n',
        encoding="utf-8",
    )
    (tests / "test_int_bypass.py").write_text(
        "def test_int_bypass():\n    flag = True\n    assert int(flag) == 1\n",
        encoding="utf-8",
    )
    (tests / "test_exact_count_ok.py").write_text(
        'def test_exact_count_ok():\n    assert "aa".count("a") == 2\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        smells,
        "load_quality",
        lambda *a, **k: {
            "test_smells": {
                "enabled": True,
                "mode": "hard",
                "include_globs": ["tests/unit/**/*.py"],
            }
        },
    )
    assert smells.run_test_smells(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports/test-smells/test-smells-summary.json").read_text(encoding="utf-8")
    )
    names = {
        Path(f["file"]).name for f in summary["findings"] if f["kind"] == "weak_primary_oracle"
    }
    assert names == {"test_count_bypass.py", "test_int_bypass.py"}


def test_smells_missing_mode_defaults_hard_fails(tmp_path: Path, monkeypatch):
    """Omit mode → hard: findings must fail the gate (exit 1)."""
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_weak.py").write_text("def test_weak():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        smells,
        "load_quality",
        lambda *a, **k: {
            "test_smells": {
                "enabled": True,
                # mode intentionally omitted
                "include_globs": ["tests/unit/**/*.py"],
            }
        },
    )
    assert smells.run_test_smells(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports/test-smells/test-smells-summary.json").read_text(encoding="utf-8")
    )
    assert summary["mode"] == "hard"
    assert summary["passed"] is False


def test_smells_main(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(smells, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(smells, "run_test_smells", lambda root, context="context": 0)
    assert smells.main(["--context", "context"]) == 0
    assert smells.main([]) == 0


def test_smells_js_ts_weak_oracle(tmp_path: Path, monkeypatch):
    tests = tmp_path / "src"
    tests.mkdir()
    (tests / "foo.test.ts").write_text(
        "test('x', () => { expect(value).toBeTruthy(); });\n",
        encoding="utf-8",
    )
    (tests / "ok.spec.ts").write_text(
        "test('x', () => { expect(value).toBe(2); });\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        smells,
        "load_quality",
        lambda *a, **k: {
            "test_smells": {
                "enabled": True,
                "mode": "hard",
                "include_globs": ["**/*.{test,spec}.{js,jsx,ts,tsx}"],
            }
        },
    )
    assert smells.run_test_smells(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports/test-smells/test-smells-summary.json").read_text(encoding="utf-8")
    )
    assert any(f["kind"] == "weak_primary_oracle" for f in summary["findings"])

