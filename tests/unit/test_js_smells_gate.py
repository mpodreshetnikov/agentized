from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agentized import js_smells_gate as gate


def test_glob_iter_run_and_gate(tmp_path: Path, monkeypatch):
    assert gate.glob_match("a/b/c.test.ts", "**/*.{test,spec}.ts") is True
    assert gate.glob_match("foo.test.ts", "**/*.{test,spec}.ts") is True
    assert gate.glob_match("a/b/c.ts", "**/*.{test,spec}.ts") is False
    assert gate.glob_match("x/y", "**/y") is True
    assert gate.glob_match("src/__tests__/foo.ts", "**/__tests__/**/*.{js,ts}") is True
    assert gate.glob_match("__tests__/foo.ts", "**/__tests__/**/*.{js,ts}") is True
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.test.ts").write_text("expect(1).toBeTruthy()\n")
    (src / "b.spec.ts").write_text("expect(1).toBeTruthy()\n")
    (tmp_path / "root.test.ts").write_text("expect(1).toBeTruthy()\n")
    (src / "__tests__").mkdir()
    (src / "__tests__" / "shallow.ts").write_text("expect(1).toBeTruthy()\n")
    (tmp_path / "__tests__").mkdir()
    (tmp_path / "__tests__" / "top.ts").write_text("expect(1).toBeTruthy()\n")
    (src / "aaa.txt").write_text("nope\n")
    skipped = tmp_path / "src" / "node_modules"
    skipped.mkdir()
    (skipped / "nested.test.ts").write_text("expect(1).toBeTruthy()\n")
    (src / "dir.test.ts").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.test.js").write_text("expect(1).toBeTruthy()\n")
    got = gate.iter_js_test_files(tmp_path, ["**/*.{test,spec}.ts"])
    assert [p.name for p in got] == ["root.test.ts", "a.test.ts", "b.spec.ts"]
    assert all(p.is_file() for p in got)
    shallow = gate.iter_js_test_files(tmp_path, ["**/__tests__/**/*.{js,jsx,ts,tsx}"])
    assert {p.as_posix() for p in shallow} == {
        (src / "__tests__/shallow.ts").as_posix(),
        (tmp_path / "__tests__/top.ts").as_posix(),
    }
    findings, scanned = gate.run_js_smells(tmp_path, {})
    assert len(scanned) >= 1 and findings[0]["kind"] == "weak_primary_oracle"
    fixed = datetime(2021, 2, 3)
    loads: list = []
    pys: list = []
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda root, ctx: (
            loads.append((root, ctx))
            or {"test_smells": {"enabled": True, "include_globs": ["**/*.{test,spec}.ts"]}}
        ),
    )
    monkeypatch.setattr(
        gate, "run_python_smells", lambda root, **k: pys.append((root, k.get("context"))) or 0
    )
    assert gate.run_test_smells(tmp_path, context="c1", now=lambda: fixed) == 1
    assert loads[-1] == (tmp_path, "c1") and pys[-1] == (tmp_path, "c1")
    payload = json.loads((tmp_path / "reports/test-smells/test-smells-js-summary.json").read_text())
    assert payload == {
        "schemaVersion": 1,
        "mode": "hard",
        "generatedAt": fixed.isoformat(),
        "filesScanned": 3,
        "findings": payload["findings"],
        "passed": False,
    }
    assert payload["findings"]
    monkeypatch.setattr(gate, "load_quality", lambda *a, **k: {"test_smells": {"enabled": False}})
    monkeypatch.setattr(
        gate, "run_python_smells", lambda root, **k: pys.append((root, k.get("context"))) or 3
    )
    assert gate.run_test_smells(tmp_path, context="off") == 3
    assert pys[-1] == (tmp_path, "off")
    monkeypatch.setattr(gate, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda root, ctx: {"test_smells": {"enabled": True, "mode": "warn", "include_globs": []}},
    )
    findings, scanned = gate.run_js_smells(tmp_path, {"include_globs": ["src/a.test.ts"]})
    assert [p.name for p in scanned] == ["a.test.ts"]
    monkeypatch.setattr(gate, "run_python_smells", lambda root, **k: 2)
    monkeypatch.setattr(gate, "run_js_smells", lambda root, section: ([{"k": 1}], []))
    assert gate.run_test_smells(None, context="c2", now=lambda: fixed) == 2
    warn_payload = json.loads(
        (tmp_path / "reports/test-smells/test-smells-js-summary.json").read_text()
    )
    assert warn_payload["passed"] is True and warn_payload["mode"] == "warn"
