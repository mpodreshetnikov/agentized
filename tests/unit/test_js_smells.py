"""JS/TS smell helpers + gate (AGE-34)."""
from __future__ import annotations

import json
from pathlib import Path

from agentized import js_smells as js
from agentized import js_smells_gate as gate


def test_brace_scan_constants_and_gate(tmp_path: Path, monkeypatch):
    assert js.expand_brace_glob("plain.py") == ["plain.py"]
    assert js.expand_brace_glob("a{b}c") == ["a{b}c"]
    assert js.expand_brace_glob("*.{test,spec}.ts") == ["*.test.ts", "*.spec.ts"]
    assert js.expand_brace_glob("**/*.{test,spec}.{js,ts}") == [
        "**/*.test.js",
        "**/*.test.ts",
        "**/*.spec.js",
        "**/*.spec.ts",
    ]
    assert js.JS_WEAK_PATTERNS == (
        (".toBeTruthy(", "weak_primary_oracle"),
        (".toBeFalsy(", "weak_primary_oracle"),
        (".toBeDefined(", "weak_primary_oracle"),
        (".toBeUndefined(", "weak_primary_oracle"),
        ("assert.ok(", "weak_primary_oracle"),
        ("assert.equal(true", "weak_primary_oracle"),
    )
    assert js.TEST_FILE_SUFFIXES == (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
    assert js.SKIP_DIR_PARTS == frozenset(
        {"node_modules", ".git", "mutants", "coverage", "dist", "build"}
    )
    path = tmp_path / "foo.test.ts"
    path.write_text(
        "// expect(x).toBeTruthy()\n"
        "expect(a).toBeTruthy()\n"
        "expect(b).toBeFalsy()\n"
        "expect(c).toBeDefined()\n"
        "expect(d).toBeUndefined()\n"
        "assert.ok(e)\n"
        "assert.equal(true, f)\n"
        "expect(g).toBe(1)\n"
        " * skip\n",
        encoding="utf-8",
    )
    assert [f["line"] for f in js.scan_js_ts_file(path, tmp_path)] == [2, 3, 4, 5, 6, 7]

    cases = [
        ("src/foo.test.ts", "**/*.{test,spec}.{js,ts}", True),
        ("src/foo.ts", "**/*.{test,spec}.{js,ts}", False),
        ("src/__tests__/x.ts", "**/__tests__/**/*.{js,ts}", True),
    ]
    assert [(r, p, gate.glob_match(r, p)) for r, p, _ in cases] == cases

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.test.ts").write_text(
        "expect(value).toBeTruthy();\n", encoding="utf-8"
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.test.js").write_text(
        "expect(1).toBeTruthy();\n", encoding="utf-8"
    )
    from datetime import datetime, timezone

    fixed = datetime(2020, 1, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(gate, "run_python_smells", lambda *a, **k: 0)
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
    assert gate.run_test_smells(tmp_path, now=lambda tz: fixed) == 1
    summary = json.loads(
        (tmp_path / "reports/test-smells/test-smells-js-summary.json").read_text()
    )
    assert summary["generatedAt"] == fixed.isoformat()
    assert summary["passed"] is False
    assert summary["filesScanned"] == 2
    assert summary["mode"] == "hard"

    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "test_smells": {
                "enabled": True,
                "mode": "warn",
                "include_globs": ["**/*.{test,spec}.ts"],
            }
        },
    )
    assert gate.run_test_smells(tmp_path, now=lambda tz: fixed) == 0
    summary = json.loads(
        (tmp_path / "reports/test-smells/test-smells-js-summary.json").read_text()
    )
    assert summary["passed"] is True
    monkeypatch.setattr(gate, "load_quality", lambda *a, **k: {"test_smells": {"enabled": False}})
    assert gate.run_test_smells(tmp_path) == 0
    monkeypatch.setattr(gate, "run_python_smells", lambda *a, **k: 4)
    monkeypatch.setattr(
        gate,
        "load_quality",
        lambda *a, **k: {
            "test_smells": {
                "enabled": True,
                "mode": "hard",
                "include_globs": ["**/*.nope.ts"],
            }
        },
    )
    assert gate.run_test_smells(tmp_path, now=lambda tz: fixed) == 4
