from __future__ import annotations

import json
from pathlib import Path

from agentized import architecture_gate as arch


def test_builtin_forbidden_edge(tmp_path: Path, monkeypatch):
    src = tmp_path / "runtime" / "agentized"
    src.mkdir(parents=True)
    (src / "mutation.py").write_text("import agentized.connect\nfrom agentized.connect import x\n", encoding="utf-8")
    (src / "connect.py").write_text("x = 1\n", encoding="utf-8")
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "readme.txt").write_text("nope\n", encoding="utf-8")
    monkeypatch.setattr(
        arch,
        "load_quality",
        lambda *a, **k: {
            "architecture": {
                "enabled": True,
                "mode": "warn",
                "tool": "builtin",
                "source_roots": ["runtime/agentized", "missing/root"],
                "forbidden_edges": [{"from": "agentized.mutation", "to": "agentized.connect"}],
            }
        },
    )
    assert arch.run_architecture_gate(tmp_path) == 0
    summary = json.loads(
        (tmp_path / "reports/architecture/architecture-summary.json").read_text(encoding="utf-8")
    )
    assert summary["findings"]
    assert summary["findings"][0]["kind"] == "forbidden_import"


def test_architecture_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        arch, "load_quality", lambda *a, **k: {"architecture": {"enabled": False}}
    )
    assert arch.run_architecture_gate(tmp_path) == 0


def test_architecture_hard_fails_on_findings(tmp_path: Path, monkeypatch):
    src = tmp_path / "runtime" / "agentized"
    src.mkdir(parents=True)
    (src / "mutation.py").write_text("import agentized.connect\n", encoding="utf-8")
    monkeypatch.setattr(
        arch,
        "load_quality",
        lambda *a, **k: {
            "architecture": {
                "enabled": True,
                "mode": "hard",
                "tool": "builtin",
                "source_roots": ["runtime/agentized"],
                "forbidden_edges": [{"from": "agentized.mutation", "to": "agentized.connect"}],
            }
        },
    )
    assert arch.run_architecture_gate(tmp_path) == 1


def test_architecture_missing_mode_defaults_hard_fails(tmp_path: Path, monkeypatch):
    """Omit mode → hard: architecture findings must fail the gate (exit 1)."""
    src = tmp_path / "runtime" / "agentized"
    src.mkdir(parents=True)
    (src / "mutation.py").write_text("import agentized.connect\n", encoding="utf-8")
    monkeypatch.setattr(
        arch,
        "load_quality",
        lambda *a, **k: {
            "architecture": {
                "enabled": True,
                # mode intentionally omitted
                "tool": "builtin",
                "source_roots": ["runtime/agentized"],
                "forbidden_edges": [{"from": "agentized.mutation", "to": "agentized.connect"}],
            }
        },
    )
    assert arch.run_architecture_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports/architecture/architecture-summary.json").read_text(encoding="utf-8")
    )
    assert summary["mode"] == "hard"
    assert summary["passed"] is False


def test_architecture_hard_pass_clean(tmp_path: Path, monkeypatch):
    src = tmp_path / "runtime" / "agentized"
    src.mkdir(parents=True)
    (src / "paths.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        arch,
        "load_quality",
        lambda *a, **k: {
            "architecture": {
                "enabled": True,
                "mode": "hard",
                "tool": "builtin",
                "source_roots": ["runtime/agentized"],
                "forbidden_edges": [{"from": "agentized.mutation", "to": "agentized.connect"}],
            }
        },
    )
    assert arch.run_architecture_gate(tmp_path) == 0


def test_module_name_and_imports_helpers(tmp_path: Path):
    src = tmp_path / "pkg"
    src.mkdir()
    init = src / "__init__.py"
    init.write_text("import os\nfrom pathlib import Path\n", encoding="utf-8")
    bad = src / "bad.py"
    bad.write_text("def (\n", encoding="utf-8")
    assert arch._module_name(tmp_path, init, ["pkg"]) == "pkg"
    assert arch._module_name(tmp_path, src / "x.py", ["other"]) is None
    assert arch._module_name(tmp_path, src, ["pkg"]) is None  # directory path not .py
    # non-py under root
    (src / "note.md").write_text("x\n", encoding="utf-8")
    assert arch._imports_of(init) == ["os", "pathlib"]
    assert arch._imports_of(bad) == []


def test_run_import_linter_missing_config(tmp_path: Path):
    rc, note = arch._run_import_linter(tmp_path, tmp_path / "nope.ini")
    assert rc == 0 and note == "no config"


def test_run_import_linter_with_exe(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".importlinter"
    cfg.write_text("[importlinter]\nroot_package = x\n", encoding="utf-8")

    class R:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(arch.shutil if hasattr(arch, "shutil") else __import__("shutil"), "which", lambda n: "/bin/lint-imports")
    # Patch where used inside function via import shutil locally — stub subprocess.run
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return R()

    monkeypatch.setattr(arch.subprocess, "run", fake_run)
    # Force which path by injecting into the function's local import — call after patching shutil in builtins path
    import shutil as sh

    monkeypatch.setattr(sh, "which", lambda n: "/usr/bin/lint-imports")
    rc, out = arch._run_import_linter(tmp_path, cfg)
    assert rc == 0
    assert "ok" in out
    assert calls["cmd"][0] == "/usr/bin/lint-imports"


def test_run_import_linter_python_fallback(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".importlinter"
    cfg.write_text("[importlinter]\nroot_package = x\n", encoding="utf-8")
    import shutil as sh

    monkeypatch.setattr(sh, "which", lambda n: None)

    class R:
        returncode = 2
        stdout = ""
        stderr = "fail"

    monkeypatch.setattr(arch.subprocess, "run", lambda *a, **k: R())
    rc, out = arch._run_import_linter(tmp_path, cfg)
    assert rc == 2
    assert "fail" in out


def test_import_linter_failure_records_finding(tmp_path: Path, monkeypatch):
    (tmp_path / ".importlinter").write_text("[importlinter]\nroot_package = x\n", encoding="utf-8")
    monkeypatch.setattr(
        arch,
        "load_quality",
        lambda *a, **k: {
            "architecture": {
                "enabled": True,
                "mode": "warn",
                "tool": "import-linter",
                "config": ".importlinter",
                "source_roots": ["runtime/agentized"],
                "forbidden_edges": [],
            }
        },
    )
    monkeypatch.setattr(arch, "_run_import_linter", lambda root, cfg: (1, "contract broken"))
    assert arch.run_architecture_gate(tmp_path) == 0
    summary = json.loads(
        (tmp_path / "reports/architecture/architecture-summary.json").read_text(encoding="utf-8")
    )
    assert summary["findings"][0]["kind"] == "import_linter"


def test_import_linter_missing_falls_back_builtin(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        arch,
        "load_quality",
        lambda *a, **k: {
            "architecture": {
                "enabled": True,
                "mode": "warn",
                "tool": "import-linter",
                "config": ".importlinter",
                "source_roots": ["runtime/agentized"],
                "forbidden_edges": [],
            }
        },
    )

    def boom(*a, **k):
        raise FileNotFoundError("lint-imports")

    monkeypatch.setattr(arch, "_run_import_linter", boom)
    assert arch.run_architecture_gate(tmp_path) == 0
    summary = json.loads(
        (tmp_path / "reports/architecture/architecture-summary.json").read_text(encoding="utf-8")
    )
    assert "not installed" in summary["toolNote"]


def test_architecture_main(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(arch, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(arch, "run_architecture_gate", lambda root, context="context": 0)
    assert arch.main(["--context", "context"]) == 0
    assert arch.main([]) == 0
