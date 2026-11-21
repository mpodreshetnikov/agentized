"""JS/TS smell helpers (AGE-34)."""
from __future__ import annotations

from pathlib import Path

from agentized import test_smells as smells
from agentized import test_smells_js as js


def test_expand_brace_glob_matrix():
    assert js.expand_brace_glob("plain.py") == ["plain.py"]
    assert js.expand_brace_glob("a{b}c") == ["a{b}c"]  # no comma → unchanged
    assert js.expand_brace_glob("*.{test,spec}.ts") == ["*.test.ts", "*.spec.ts"]
    assert js.expand_brace_glob("**/*.{test,spec}.{js,ts}") == [
        "**/*.test.js",
        "**/*.test.ts",
        "**/*.spec.js",
        "**/*.spec.ts",
    ]
    # Alias on test_smells stays wired.
    assert smells._expand_brace_glob("*.{a,b}") == ["*.a", "*.b"]


def test_scan_js_ts_weak_patterns(tmp_path: Path):
    path = tmp_path / "foo.test.ts"
    path.write_text(
        "\n".join(
            [
                "// expect(x).toBeTruthy()",
                "expect(a).toBeTruthy()",
                "expect(b).toBeFalsy()",
                "expect(c).toBeDefined()",
                "expect(d).toBeUndefined()",
                "assert.ok(e)",
                "assert.equal(true, f)",
                "expect(g).toBe(1)",
                " * expect(h).toBeTruthy()",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    findings = js.scan_js_ts_file(path, tmp_path)
    kinds = [f["kind"] for f in findings]
    assert kinds == ["weak_primary_oracle"] * 6
    assert [f["line"] for f in findings] == [2, 3, 4, 5, 6, 7]
    assert smells._scan_js_ts_file(path, tmp_path) == findings


def test_constants_pinned():
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
