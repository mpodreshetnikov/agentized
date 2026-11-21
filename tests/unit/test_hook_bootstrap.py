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


def test_process_guard_broken_json_deny_exit_2(monkeypatch, tmp_path, capsys):
    """Broken process-control.json → deny JSON + exit 2 (fail closed)."""
    root = _repo_root()
    script = root / "packages/shared/hooks/scripts/process_guard.py"
    if not script.is_file():
        pytest.skip("process_guard script not present")
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "runtime").mkdir()
    payload = json.dumps({"tool_input": {"file_path": "runtime/x.py"}, "cwd": str(tmp_path)})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    # Ensure runtime import resolves to repo runtime, workspace is tmp_path
    mod = _load("process_guard_failclosed", script)

    def fake_ensure(here=None):  # noqa: ARG001
        runtime = root / "runtime"
        if str(runtime) not in sys.path:
            sys.path.insert(0, str(runtime))
        return tmp_path

    monkeypatch.setattr(mod, "ensure_runtime_on_path", fake_ensure)
    rc = mod.main()
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["permission"] == "deny"
    assert "claim check failed" in out["agent_message"] or "invalid JSON" in out["agent_message"]


def test_process_guard_array_json_deny_exit_2(monkeypatch, tmp_path, capsys):
    root = _repo_root()
    script = root / "packages/shared/hooks/scripts/process_guard.py"
    if not script.is_file():
        pytest.skip("process_guard script not present")
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text("[]\n", encoding="utf-8")
    payload = json.dumps({"tool_input": {"file_path": "runtime/x.py"}, "cwd": str(tmp_path)})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    mod = _load("process_guard_array", script)

    def fake_ensure(here=None):  # noqa: ARG001
        runtime = root / "runtime"
        if str(runtime) not in sys.path:
            sys.path.insert(0, str(runtime))
        return tmp_path

    monkeypatch.setattr(mod, "ensure_runtime_on_path", fake_ensure)
    assert mod.main() == 2
    out = json.loads(capsys.readouterr().out)
    assert out["permission"] == "deny"


def test_cursor_hooks_process_guard_fail_closed():
    root = _repo_root()
    data = json.loads((root / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    pre = data["hooks"]["preToolUse"]
    guard = next(h for h in pre if "process_guard" in h["command"])
    assert guard == {
        "command": ".cursor/hooks/process_guard.py",
        "matcher": "Write|Edit",
        "failClosed": True,
    }
    pkg = json.loads(
        (root / "packages/agentized-cursor/hooks/hooks.json").read_text(encoding="utf-8")
    )
    pkg_guard = next(h for h in pkg["hooks"]["preToolUse"] if "process_guard" in h["command"])
    assert pkg_guard == {
        "command": "./scripts/process_guard.py",
        "matcher": "Write|Edit",
        "failClosed": True,
    }
