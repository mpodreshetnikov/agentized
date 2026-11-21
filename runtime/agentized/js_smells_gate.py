"""Test-smells entry (AGE-34): Python + JS/TS weak-oracle scan."""
from __future__ import annotations

import fnmatch
import json
from datetime import datetime
from pathlib import Path

from .gate_dispatch import combine_gate_rc
from .js_smells import SKIP_DIR_PARTS, expand_brace_glob, scan_js_ts_file
from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality
from .test_smells import run_test_smells as run_python_smells

_JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
_DEFAULT_GLOBS = (
    "**/*.{test,spec}.{js,jsx,ts,tsx}",
    "**/__tests__/**/*.{js,jsx,ts,tsx}",
)


def glob_match(rel: str, pattern: str) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in expand_brace_glob(pattern))


def iter_js_test_files(root: Path, globs: list[str]) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _JS_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if SKIP_DIR_PARTS.intersection(rel.split("/")):
            continue
        if any(glob_match(rel, g) for g in globs):
            out.append(path)
    return sorted(out)


def run_js_smells(root: Path, section: dict) -> tuple[list[dict], list[Path]]:
    globs = list(section["include_globs"]) if "include_globs" in section else list(_DEFAULT_GLOBS)
    files = iter_js_test_files(root, globs)
    findings: list[dict] = []
    for path in files:
        findings.extend(scan_js_ts_file(path, root))
    return findings, files


def run_test_smells(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
    now=None,
) -> int:
    resolved = find_repo_root() if root is None else root
    cfg = load_quality(resolved, context)
    section = cfg.get("test_smells") or {}
    if section.get("enabled") is not True:
        return run_python_smells(resolved, context=context)

    py_rc = run_python_smells(resolved, context=context)
    findings, files = run_js_smells(resolved, section)
    mode = str(section.get("mode", "hard"))
    stamp = (now or datetime.now)().isoformat()
    out_dir = resolved / "reports" / "test-smells"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "mode": mode,
        "generatedAt": stamp,
        "filesScanned": len(files),
        "findings": findings,
        "passed": mode == "warn" or not findings,
    }
    (out_dir / "test-smells-js-summary.json").write_text(json.dumps(payload) + "\n")
    return combine_gate_rc(mode, bool(findings), py_rc)
