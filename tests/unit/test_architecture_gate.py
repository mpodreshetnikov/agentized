from __future__ import annotations

import json
from pathlib import Path

from agentized import architecture_gate as arch


def test_builtin_forbidden_edge(tmp_path: Path, monkeypatch):
    src = tmp_path / "runtime" / "agentized"
    src.mkdir(parents=True)
    (src / "mutation.py").write_text("import agentized.connect\n", encoding="utf-8")
    (src / "connect.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        arch,
        "load_quality",
        lambda *a, **k: {
            "architecture": {
                "enabled": True,
                "mode": "warn",
                "tool": "builtin",
                "source_roots": ["runtime/agentized"],
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
