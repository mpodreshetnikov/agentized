"""Language → gate-tool dispatch for mutation / architecture (AGE-34).

Self-contained so the JS/TS gates PR can land from main without AGE-24.
AGE-24 owns connect refuse / SUPPORTED_GATES; this module only maps
extensions → tools for runners.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

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
    "**/*.example",
    "**/*.example.*",
)


def _glob_excluded(rel: str, patterns: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
            return True
        if pat.endswith("/**"):
            prefix = pat[: -len("/**")]
            if prefix.startswith("**/"):
                prefix = prefix[3:]
            if rel == prefix or rel.startswith(prefix + "/"):
                return True
    return False


def language_for_path(rel: str) -> str | None:
    name = rel.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(".d.ts"):
        return None
    for ext, lang in _EXT_LANG.items():
        if name.endswith(ext):
            return lang
    return None


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
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if _glob_excluded(rel, patterns):
            continue
        lang = language_for_path(rel)
        if not lang:
            continue
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
