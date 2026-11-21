"""JS/TS test-smell helpers + brace-glob expand (AGE-34)."""
from __future__ import annotations

from pathlib import Path

JS_WEAK_PATTERNS = (
    (".toBeTruthy(", "weak_primary_oracle"),
    (".toBeFalsy(", "weak_primary_oracle"),
    (".toBeDefined(", "weak_primary_oracle"),
    (".toBeUndefined(", "weak_primary_oracle"),
    ("assert.ok(", "weak_primary_oracle"),
    ("assert.equal(true", "weak_primary_oracle"),
)

TEST_FILE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
SKIP_DIR_PARTS = frozenset({"node_modules", ".git", "mutants", "coverage", "dist", "build"})


def expand_brace_glob(pattern: str) -> list[str]:
    """Expand `{a,b}` brace groups (enough for *.{test,spec}.{js,ts})."""
    if "{" not in pattern or "}" not in pattern:
        return [pattern]
    start = pattern.index("{")
    end = pattern.index("}", start)
    body = pattern[start + 1 : end]
    if "," not in body:
        return [pattern]
    prefix, suffix = pattern[:start], pattern[end + 1 :]
    out: list[str] = []
    for part in body.split(","):
        out.extend(expand_brace_glob(prefix + part + suffix))
    return out


def scan_js_ts_file(path: Path, root: Path) -> list[dict]:
    """Lightweight test-smell lint for JS/TS tests (Orbit weak-oracle patterns)."""
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [{"file": rel, "line": 1, "kind": "read_error", "detail": str(exc)}]
    findings: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        for needle, kind in JS_WEAK_PATTERNS:
            if needle in line:
                findings.append(
                    {
                        "file": rel,
                        "line": i,
                        "kind": kind,
                        "detail": (
                            f"JS/TS weak oracle ({needle.strip('(')}) — prefer exact value asserts"
                        ),
                    }
                )
                break
    return findings
