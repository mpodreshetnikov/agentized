from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bootstrap_path() -> Path | None:
    root = _repo_root()
    for rel in (
        "packages/shared/hooks/scripts/_bootstrap.py",
        "context/hooks/scripts/_bootstrap.py",
        ".cursor/hooks/_bootstrap.py",
    ):
        path = root / rel
        if path.is_file():
            return path
    return None


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_bootstrap_finds_runtime():
    path = _bootstrap_path()
    if path is None:
        pytest.skip("bootstrap script not present in this sandbox")
    mod = _load("_bootstrap", path)
    ws = mod.ensure_runtime_on_path(path)
    assert any((Path(p) / "agentized").is_dir() for p in sys.path)
    assert isinstance(ws, Path)


def test_process_guard_allows_without_paths(monkeypatch, tmp_path, capsys):
    root = _repo_root()
    candidates = [
        root / "packages/shared/hooks/scripts/process_guard.py",
        root / "context/hooks/scripts/process_guard.py",
        root / ".cursor/hooks/process_guard.py",
    ]
    script = next((p for p in candidates if p.is_file()), None)
    if script is None:
        pytest.skip("process_guard script not present in this sandbox")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    # sibling _bootstrap must be importable from the script directory
    mod = _load("process_guard", script)
    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["permission"] == "allow"
