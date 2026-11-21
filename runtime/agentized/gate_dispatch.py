"""Lang→tool dispatch + changed-source helpers (AGE-34)."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any

_SOURCE_TESTISH_NAMES = frozenset({"test_smells.py"})
# fmt: off
_EXT_LANG = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
}
MUTATION_TOOLS = {
    "python": frozenset({"mutmut"}), "javascript": frozenset({"stryker"}), "typescript": frozenset({"stryker"}),
}
ARCHITECTURE_TOOLS = {
    "python": frozenset({"import-linter", "builtin"}),
    "javascript": frozenset({"dependency-cruiser", "eslint-boundaries"}),
    "typescript": frozenset({"dependency-cruiser", "eslint-boundaries"}),
}
# fmt: on
DEFAULT_EXCLUDE_GLOBS = (
    "**/node_modules/**",
    "**/vendor/**",
    "**/dist/**",
    "**/build/**",
    "**/.venv/**",
    "**/__pycache__/**",
    "**/mutants/**",
    "**/coverage/**",
    "**/reports/**",
    "**/*.min.js",
    "**/.git/**",
    "**/*.example*",
)


def match_starstar(rel: str, pattern: str) -> bool:
    rel, pats = rel.replace("\\", "/"), pattern.replace("\\", "/").split("/")
    parts = rel.split("/") if rel else []

    def rec(pi: int, pj: int) -> bool:
        if pj < len(pats) and pats[pj] == "**":
            start = pi
            return any(rec(k, pj + 1) for k in range(start, len(parts) + 1))
        if pj == len(pats):
            return pi == len(parts)
        if pi == len(parts):
            return False
        return fnmatch.fnmatch(parts[pi], pats[pj]) and rec(pi + 1, pj + 1)

    return rec(0, 0)


def _glob_excluded(rel: str, patterns: list[str]) -> bool:
    return any(match_starstar(rel, pat) for pat in patterns)


def language_for_path(rel: str) -> str | None:
    name = Path(rel).name.lower()
    return None if name.endswith(".d.ts") else _EXT_LANG.get(Path(name).suffix)


def detect_languages(root: Path, *, exclude_globs: list[str] | None = None) -> dict[str, list[str]]:
    patterns = list(exclude_globs if exclude_globs is not None else DEFAULT_EXCLUDE_GLOBS)
    found: dict[str, list[str]] = {}
    if not root.exists():
        return found
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _glob_excluded(rel, patterns):
            continue
        lang = language_for_path(rel)
        if lang:
            bucket = found.setdefault(lang, [])
            if len(bucket) < 8:
                bucket.append(rel)
    return found


def _tool_pick(cfg: dict[str, Any], language: str, allowed: dict) -> str | None:
    tools = cfg.get("tools")
    if isinstance(tools, dict) and tools.get(language):
        return str(tools[language]).lower()
    single = cfg.get("tool")
    if not single:
        return None
    single_s = str(single).lower()
    return single_s if single_s in (allowed.get(language) or frozenset()) else None


def mutation_tool_for_language(mut_cfg: dict[str, Any], language: str) -> str | None:
    return _tool_pick(mut_cfg, language, MUTATION_TOOLS)


def architecture_tool_for_language(arch_cfg: dict[str, Any], language: str) -> str | None:
    return _tool_pick(arch_cfg, language, ARCHITECTURE_TOOLS)


def is_test_path(name: str) -> bool:
    name = name.replace("\\", "/")
    parts, base = name.split("/"), name.split("/")[-1]
    if base in _SOURCE_TESTISH_NAMES:
        return False
    if "tests" in parts or "__tests__" in parts or base.startswith("test_"):
        return True
    stem = Path(base).stem
    return stem.endswith(("_test", "-test")) or ".test." in base or ".spec." in base


def git_changed_names(root: Path, base_ref: str) -> list[str]:
    cmds = [
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"],
        ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref],
    ]
    for cmd in cmds:
        proc = subprocess.run(cmd, check=False, cwd=root, capture_output=True, text=True)
        if proc.returncode == 0:
            return [n.strip().replace("\\", "/") for n in proc.stdout.splitlines() if n.strip()]
    raise SystemExit("git diff failed")


def changed_source_files(root: Path, base_ref: str, prefixes: list[str]) -> list[str]:
    out = []
    for name in git_changed_names(root, base_ref):
        if is_test_path(name) or not language_for_path(name):
            continue
        for p in prefixes:
            root_p = p.removesuffix("/")
            if name == root_p or name.startswith(root_p + "/"):
                out.append(name)
                break
    return sorted(set(out))


def combine_gate_rc(mode: str, has_findings: bool, py_rc: int) -> int:
    return py_rc if mode == "warn" else (1 if has_findings else py_rc)
