from __future__ import annotations

import json
from pathlib import Path

from agentized import test_smells as smells


def test_weak_oracle_and_mock_call_only(tmp_path: Path, monkeypatch):
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_weak.py").write_text(
        "def test_weak():\n    x = 1\n    assert x\n    assert x is not None\n",
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
