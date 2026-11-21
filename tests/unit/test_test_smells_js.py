"""JS/TS smell helpers (AGE-34)."""
from __future__ import annotations

from pathlib import Path

from agentized import test_smells as smells
from agentized import test_smells_js as js


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
    assert smells._expand_brace_glob("*.{a,b}") == ["*.a", "*.b"]
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
        " * expect(h).toBeTruthy()\n",
        encoding="utf-8",
    )
    findings = js.scan_js_ts_file(path, tmp_path)
    assert [f["line"] for f in findings] == [2, 3, 4, 5, 6, 7]
    assert smells._scan_js_ts_file(path, tmp_path) == findings
    assert js.JS_WEAK_PATTERNS[0] == (".toBeTruthy(", "weak_primary_oracle")
    assert js.TEST_FILE_SUFFIXES[-1] == ".cjs"
    assert "node_modules" in js.SKIP_DIR_PARTS
