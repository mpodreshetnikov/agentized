"""JS/TS smell helpers (AGE-34)."""
from __future__ import annotations

from pathlib import Path

from agentized import js_smells as js


def test_brace_scan_constants_and_read_error(tmp_path: Path, monkeypatch):
    assert js.expand_brace_glob("plain.py") == ["plain.py"]
    assert js.expand_brace_glob("a{b}c") == ["a{b}c"]
    assert js.expand_brace_glob("*.{test,spec}.ts") == ["*.test.ts", "*.spec.ts"]
    assert js.expand_brace_glob("**/*.{test,spec}.{js,ts}") == [
        "**/*.test.js",
        "**/*.test.ts",
        "**/*.spec.js",
        "**/*.spec.ts",
    ]
    assert len(js.JS_WEAK_PATTERNS) == 6
    assert js.TEST_FILE_SUFFIXES[0] == ".py" and js.TEST_FILE_SUFFIXES[-1] == ".cjs"
    assert "node_modules" in js.SKIP_DIR_PARTS
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
    )
    got = js.scan_js_ts_file(path, tmp_path)
    assert [f["line"] for f in got] == [2, 3, 4, 5, 6, 7]
    assert all(f["file"] == "foo.test.ts" and f["kind"] == "weak_primary_oracle" for f in got)
    assert got[0]["detail"] == ".toBeTruthy("
