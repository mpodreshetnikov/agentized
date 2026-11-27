from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_QUALITY = ROOT / "scripts" / "quality"
RUNTIME = ROOT / "runtime"
for path in (RUNTIME, SCRIPT_QUALITY):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch, tmp_path_factory):
    """Global git user.email so connect() preflight passes on a bare runner.

    Repo-local config still wins; tests for a missing email point
    GIT_CONFIG_GLOBAL at /dev/null themselves.
    """
    cfg = tmp_path_factory.mktemp("gitcfg") / "gitconfig"
    cfg.write_text("[user]\n\temail = fixture@example.com\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
