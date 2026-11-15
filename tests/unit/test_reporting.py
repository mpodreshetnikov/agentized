from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentized.reporting import (
    ensure_reporting_config,
    load_reporting,
    save_reporting,
    set_reporting_level,
)


def test_reporting_defaults_and_set(tmp_path: Path):
    (tmp_path / "context").mkdir()
    info = ensure_reporting_config(tmp_path, "context")
    assert info["created"] is True
    cfg = load_reporting(tmp_path, "context")
    assert cfg["level"] == "short"
    # no clobber
    assert ensure_reporting_config(tmp_path, "context")["created"] is False
    set_reporting_level(tmp_path, "technical", context_rel="context")
    assert load_reporting(tmp_path, "context")["level"] == "technical"


def test_reporting_corrupt_and_invalid(tmp_path: Path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    path = ctx / "reporting.json"
    path.write_text("{not-json", encoding="utf-8")
    assert load_reporting(tmp_path, "context")["level"] == "short"
    path.write_text(json.dumps({"level": "nope"}), encoding="utf-8")
    assert load_reporting(tmp_path, "context")["level"] == "short"
    path.write_text("[]\n", encoding="utf-8")
    assert load_reporting(tmp_path, "context")["level"] == "short"
    with pytest.raises(ValueError):
        set_reporting_level(tmp_path, "nope", context_rel="context")
    with pytest.raises(ValueError):
        save_reporting(tmp_path, {"level": "nope"}, "context")
