"""CLI cmd_quality show (kept out of mutmut module selection — needs agentized_cli)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

pytest.importorskip("agentized_cli")


def test_cmd_quality_show_no_unboundlocal(tmp_path: Path, monkeypatch, capsys):
    """quality show must use module-scope load_quality (no local-import UnboundLocalError).

    Regression: a local ``from agentized.quality import load_quality`` inside the
    ``check`` branch made ``load_quality`` local for the whole ``cmd_quality``, so
    ``show`` crashed before that import ran (fresh nested connect → quality show).
    """
    from agentized_cli import cmd_quality

    monkeypatch.setattr("agentized_cli.find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        "agentized_cli.load_state",
        lambda root: {"context": "context"},  # noqa: ARG005
    )
    (tmp_path / "context").mkdir(exist_ok=True)

    args = argparse.Namespace(quality_cmd="show", context=None)
    assert cmd_quality(args) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["version"] == 1
    assert "coverage" in data
    assert float(data["coverage"]["lines"]) > 0


def test_cmd_quality_show_after_ensure_quality(tmp_path: Path, monkeypatch, capsys):
    """Fresh nested quality.json from ensure_quality_config → show still works."""
    from agentized.connect import ensure_quality_config
    from agentized_cli import cmd_quality

    monkeypatch.setattr("agentized_cli.find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        "agentized_cli.load_state",
        lambda root: {"context": "context"},  # noqa: ARG005
    )
    (tmp_path / "context").mkdir(exist_ok=True)
    info = ensure_quality_config(tmp_path, "context")
    assert info["created"] is True
    assert (tmp_path / "context" / "quality.json").is_file()

    args = argparse.Namespace(quality_cmd="show", context=None)
    assert cmd_quality(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["coverage"]["lines"] == 80.0
    assert data["test_smells"]["mode"] == "hard"
