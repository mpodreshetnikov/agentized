"""Lang→tool dispatch + changed-source helpers (AGE-34)."""
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any

_SOURCE_TESTISH_NAMES = frozenset({"test_smells.py"})

_EXT_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

MUTATION_TOOLS = {
    "python": frozenset({"mutmut"}),
    "javascript": frozenset({"stryker"}),
    "typescript": frozenset({"stryker"}),
}

ARCHITECTURE_TOOLS = {
    "python": frozenset({"import-linter", "builtin"}),
    "javascript": frozenset({"dependency-cruiser", "eslint-boundaries"}),
    "typescript": frozenset({"dependency-cruiser", "eslint-boundaries"}),
}

DEFAULT_EXCLUDE_GLOBS = (
    "node_modules/**",
    "vendor/**",
    "**/dist/**",
    "**/build/**",
    "**/.venv/**",
    "**/__pycache__/**",
    "mutants/**",
    "coverage/**",
    "reports/**",
    "**/*.min.js",
    "**/.git/**",
    "packages/**",
    "templates/**",
    "**/*.example*",
)

def _glob_excluded(rel: str, patterns: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        if pat.endswith("/**") and rel == pat[:-3]:
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
            return True
    return False

def language_for_path(rel: str) -> str | None:
    name = Path(rel).name.lower()
    if name.endswith(".d.ts"):
        return None
    return _EXT_LANG.get(Path(name).suffix)

def detect_languages(
    root: Path,
    *,
    exclude_globs: list[str] | None = None,
) -> dict[str, list[str]]:
    patterns = list(exclude_globs if exclude_globs is not None else DEFAULT_EXCLUDE_GLOBS)
    found: dict[str, list[str]] = {}
    if not root.exists():
        return found
    for path in root.rglob("*"):
        if path.is_file():
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = None
            if rel and not _glob_excluded(rel, patterns):
                lang = language_for_path(rel)
                if lang:
                    bucket = found.setdefault(lang, [])
                    if len(bucket) < 8:
                        bucket.append(rel)
    return found

def mutation_tool_for_language(mut_cfg: dict[str, Any], language: str) -> str | None:
    tools = mut_cfg.get("tools")
    if isinstance(tools, dict) and tools.get(language):
        return str(tools[language]).lower()
    single = mut_cfg.get("tool")
    if not single:
        return None
    single_s = str(single).lower()
    return single_s if single_s in (MUTATION_TOOLS.get(language) or frozenset()) else None

def architecture_tool_for_language(arch_cfg: dict[str, Any], language: str) -> str | None:
    tools = arch_cfg.get("tools")
    if isinstance(tools, dict) and tools.get(language):
        return str(tools[language]).lower()
    single = arch_cfg.get("tool")
    if not single:
        return None
    single_s = str(single).lower()
    return single_s if single_s in (ARCHITECTURE_TOOLS.get(language) or frozenset()) else None

def is_test_path(name: str) -> bool:
    """True for test files — not production modules like ``test_smells.py``."""
    name = name.replace("\\", "/")
    parts = name.split("/")
    base = parts[-1]
    if base in _SOURCE_TESTISH_NAMES:
        return False
    if "tests" in parts or "__tests__" in parts:
        return True
    if base.startswith("test_"):
        return True
    stem = Path(base).stem
    if stem.endswith("_test") or stem.endswith("-test"):
        return True
    if ".test." in base or ".spec." in base:
        return True
    return False

def git_changed_names(root: Path, base_ref: str) -> list[str]:
    cmds = [
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"],
        ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref],
    ]
    for cmd in cmds:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        if proc.returncode == 0:
            return [n.strip().replace("\\", "/") for n in proc.stdout.splitlines() if n.strip()]
    raise SystemExit("git diff failed")

def changed_source_files(root: Path, base_ref: str, prefixes: list[str]) -> list[str]:
    names = git_changed_names(root, base_ref)
    out = []
    for name in names:
        if is_test_path(name) or not language_for_path(name):
            continue
        for p in prefixes:
            root_p = p.removesuffix("/")
            if name == root_p or name.startswith(root_p + "/"):
                out.append(name)
                break
    return sorted(set(out))

def combine_gate_rc(mode: str, has_findings: bool, py_rc: int) -> int:
    if mode == "warn":
        return py_rc
    return 1 if has_findings else py_rc
