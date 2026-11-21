"""JS/TS smell helpers + gate (AGE-34)."""
from __future__ import annotations

import json
from pathlib import Path

from agentized import test_smells_js as js
from agentized import test_smells_js_gate as gate


def test_brace_scan_and_constants(tmp_path: Path):
    assert js.expand_brace_glob("plain.py") == ["plain.py"]
    assert js.expand_brace_glob("a{b}c") == ["a{b}c"]
    assert js.expand_brace_glob("*.{test,spec}.ts") == ["*.test.ts", "*.spec.ts"]
    assert js.expand_brace_glob("**/*.{test,spec}.{js,ts}") == [
        "**/*.test.js",
        "**/*.test.ts",
        "**/*.spec.js",
        "**/*.spec.ts",
    ]
    path = tmp_path / "foo.test.ts"
    path.write_text(
        "// expect(x).toBeTruthy()\n"
        "expect(a).toBeTruthy()\n"
        "expect(b).toBeFalsy()\n"
        "expect(c).toBeDefined()\n"
        "expect(d).toBeUndefined()\n"
        "assert.ok(e)\n"
        "assert.equal(true, f)\n"
        "expect(g).toBe(1)\n",
        encoding="utf-8",
    )
    findings = js.scan_js_ts_file(path, tmp_path)
    assert [f["line"] for f in findings] == [2, 3, 4, 5, 6, 7]
    assert js.JS_WEAK_PATTERNS[0][0] == ".toBeTruthy("
    assert "node_modules" in js.SKIP_DIR_PARTS


def test_smells_js_gate_finds_weak_oracle(tmp_path: Path, monkeypatch):
    tests = tmp_path / "src"
    tests.mkdir()
    (tests / "foo.test.ts").write_text(
        "test('x', () => { expect(value).toBeTruthy(); });\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "test_smells": {
                "enabled": True,
                "mode": "hard",
                "include_globs": ["**/*.{test,spec}.{js,jsx,ts,tsx}"],
            }
        },
    )
    monkeypatch.setattr(gate, "run_python_smells", lambda *a, **k: 0)
    assert gate.run_test_smells(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports/test-smells/test-smells-js-summary.json").read_text()
    )
    assert any(f["kind"] == "weak_primary_oracle" for f in summary["findings"])
