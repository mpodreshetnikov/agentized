"""Test-smells entry (AGE-34): Python AST gate + JS/TS weak-oracle scan."""
from __future__ import annotations

import fnmatch
import json
from datetime import datetime, timezone
from pathlib import Path

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality
from .test_smells import run_test_smells as run_python_smells
from .js_smells import SKIP_DIR_PARTS, expand_brace_glob, scan_js_ts_file

_JS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


def glob_match(rel: str, pattern: str) -> bool:
    for pat in expand_brace_glob(pattern):
        if fnmatch.fnmatch(rel, pat):
            return True
        if "**" not in pat:
            continue
        simplified = pat.replace("/**/", "/").replace("**/", "").replace("**", "*")
        if fnmatch.fnmatch(rel, simplified) or any(
            fnmatch.fnmatch(rel[i + 1 :], simplified) for i, ch in enumerate(rel) if ch == "/"
        ):
            return True
    return False


def iter_js_test_files(root: Path, globs: list[str]) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _JS_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP_DIR_PARTS for part in rel.split("/")):
            continue
        if any(glob_match(rel, g) for g in globs):
            out.append(path)
    return sorted(out)


def run_js_smells(root: Path, section: dict) -> tuple[list[dict], list[Path]]:
    globs = list(
        section.get("include_globs")
        or ["**/*.{test,spec}.{js,jsx,ts,tsx}", "**/__tests__/**/*.{js,jsx,ts,tsx}"]
    )
    files = iter_js_test_files(root, globs)
    findings: list[dict] = []
    for path in files:
        findings.extend(scan_js_ts_file(path, root))
    return findings, files


def run_test_smells(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg.get("test_smells") or {}
    if not section.get("enabled", False):
        return run_python_smells(root, context=context)

    py_rc = run_python_smells(root, context=context)
    findings, files = run_js_smells(root, section)
    mode = str(section.get("mode") or "hard").lower()
    out_dir = root / "reports" / "test-smells"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "mode": mode,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "filesScanned": len(files),
        "findings": findings,
        "passed": True if mode == "warn" else not findings,
    }
    (out_dir / "test-smells-js-summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    if findings:
        print(f"[test-smells-js] {len(findings)} finding(s) (mode={mode})")
        for item in findings[:40]:
            print(f"  {item['file']}:{item['line']} {item['kind']}: {item['detail']}")
        if mode == "warn":
            print("[test-smells-js] warn mode — not failing the gate")
            return 0 if py_rc == 0 else py_rc
        return 1
    return 0 if py_rc == 0 else py_rc
