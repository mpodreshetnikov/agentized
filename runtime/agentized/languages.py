"""Fail-closed language coverage (AGE-24 part a).

Detect source languages (exclude vendored/generated). Refuse ``detect: false``,
illegal ``languages.supported`` entries, empty ``supported`` / ``exclude_globs``,
unsupported / unknown source languages, and incomplete gates. JS/TS additionally
require verified AGE-34 runners (no silent pass on config alone).
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from . import languages_text as _text
from .paths import DEFAULT_CONTEXT
from .quality import load_quality

# Wide map: anything not in DEFAULT_SUPPORTED is unsupported → refuse.
_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".vue": "vue",
    ".svelte": "svelte",
    ".scala": "scala",
    ".sc": "scala",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".lua": "lua",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".r": "r",
    ".jl": "julia",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".nim": "nim",
    ".zig": "zig",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".fs": "fsharp",
    ".fsx": "fsharp",
    ".vb": "vb",
    ".pl": "perl",
    ".pm": "perl",
    ".tcl": "tcl",
    ".m": "objective-c",
    ".mm": "objective-c",
}

# Non-source / config / docs — ignored (not unknown refuse).
_NON_SOURCE_EXTS = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".json",
        ".jsonc",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        ".lock",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".map",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".html",
        ".htm",
        ".xml",
        ".csv",
        ".tsv",
        ".pdf",
        ".zip",
        ".gz",
        ".tgz",
        ".whl",
        ".egg",
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".o",
        ".a",
        ".class",
        ".jar",
        ".war",
        ".log",
        ".sum",
        ".mod",
        ".proto",
        ".graphql",
        ".gql",
        ".env",
        ".example",
        ".sample",
        ".dist",
        ".bak",
        ".orig",
        ".rej",
        ".patch",
        ".diff",
        ".editorconfig",
        ".gitignore",
        ".gitattributes",
        ".dockerignore",
        ".npmrc",
        ".nvmrc",
        ".prettierrc",
        ".eslintrc",
        ".babelrc",
        ".tag",
        ".cache",
        ".tmp",
        ".temp",
        ".swp",
        ".swo",
        ".ds_store",
    }
)

SUPPORTED_GATES = ("tests", "coverage", "mutation", "smells", "architecture")

_LANG_EXTS: dict[str, tuple[str, ...]] = {
    "python": (".py", ".pyi"),
    "javascript": (".js", ".mjs", ".cjs", ".jsx"),
    "typescript": (".ts", ".tsx"),
}

MUTATION_TOOLS: dict[str, frozenset[str]] = {
    "python": frozenset({"mutmut"}),
    "javascript": frozenset({"stryker"}),
    "typescript": frozenset({"stryker"}),
}

ARCHITECTURE_TOOLS: dict[str, frozenset[str]] = {
    "python": frozenset({"import-linter", "builtin"}),
    "javascript": frozenset({"dependency-cruiser", "eslint-boundaries"}),
    "typescript": frozenset({"dependency-cruiser", "eslint-boundaries"}),
}

DEFAULT_SUPPORTED = ("python", "javascript", "typescript")

# Defaults MUST NOT exclude packages/** or templates/** — dogfood-only in
# context/quality.json (Maxim Lead reject batch 2).
DEFAULT_EXCLUDE_GLOBS = (
    "node_modules/**",
    "vendor/**",
    "third_party/**",
    "dist/**",
    "build/**",
    "out/**",
    "**/dist/**",
    "**/build/**",
    "**/out/**",
    ".venv/**",
    "venv/**",
    "**/.venv/**",
    "**/venv/**",
    "**/__pycache__/**",
    "**/.tox/**",
    "**/site-packages/**",
    "mutants/**",
    "coverage/**",
    "reports/**",
    "**/*.min.js",
    "**/generated/**",
    "**/.git/**",
    "target/**",
    "**/target/**",
    "Pods/**",
    "**/Pods/**",
    ".cursor/**",
    ".claude/**",
    ".codex/**",
    ".agents/**",
    "context/hooks/**",
    ".pytest_cache/**",
    "**/.pytest_cache/**",
    ".mypy_cache/**",
    "**/.mypy_cache/**",
    ".ruff_cache/**",
    "**/.ruff_cache/**",
    ".tox/**",
    ".coverage",
    "htmlcov/**",
    "**/*.example",
    "**/*.example.*",
    "**/*.example.cjs",
    "**/*.example.mjs",
)

_EXT_IN_GLOB = re.compile(r"\.([a-z0-9]+)(?=$|[,}/])", re.IGNORECASE)

_STRYKER_MARKERS = ("_run_stryker_gate", "def _run_stryker")
_JS_ARCH_MARKERS = ("_run_dependency_cruiser", "_run_eslint_boundaries")


def default_languages_config() -> dict[str, Any]:
    return {
        "supported": list(DEFAULT_SUPPORTED),
        "exclude_globs": list(DEFAULT_EXCLUDE_GLOBS),
    }


def _glob_excluded(rel: str, patterns: list[str]) -> bool:
    rel = rel.replace(chr(92), "/")
    for pat in patterns:
        if pat:
            if fnmatch.fnmatch(rel, pat):
                return True
            if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
                return True
            if pat.endswith("/**"):
                prefix = pat[:-3]
                if prefix.startswith("**/"):
                    prefix = prefix[3:]
                if rel == prefix or rel.startswith(prefix + "/"):
                    return True
            if "/**/*." in pat:
                head, _sep, ext = pat.partition("/**/*.")
                if head and ext and rel.startswith(head + "/") and rel.endswith("." + ext):
                    return True
    return False

def language_for_path(rel: str) -> str | None:
    name = Path(str(rel)).name.lower()
    if not name or name.startswith("."):
        return None
    if name.endswith(".d.ts"):
        return None
    for ext, lang in _EXT_LANG.items():
        if name.endswith(ext):
            return lang
    if "." not in name:
        return None
    ext = "." + name.split(".")[-1]
    if ext in _NON_SOURCE_EXTS:
        return None
    return "unknown"


def detect_languages(
    root: Path,
    *,
    exclude_globs: list[str] | None = None,
) -> dict[str, list[str]]:
    if exclude_globs is None:
        raise ValueError("exclude_globs is required (empty/missing refused by check_language_coverage)")
    patterns = list(exclude_globs)
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


def validate_supported_list(supported: list[str]) -> list[str]:
    return sorted(lang for lang in supported if lang not in _LANG_EXTS)


def _module_has_lang(root: Path, module: dict[str, Any], language: str) -> bool:
    exts = _LANG_EXTS.get(language) or ()
    for src in module.get("source") or []:
        base = root / str(src)
        if base.is_file():
            name = base.name.lower()
            if not name.endswith(".d.ts") and any(name.endswith(ext) for ext in exts):
                return True
        elif base.is_dir():
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                name = path.name.lower()
                if name.endswith(".d.ts"):
                    continue
                if any(name.endswith(ext) for ext in exts):
                    return True
    return False


def _globs_cover(globs: list[str], language: str) -> bool:
    """True when include_globs mention a real extension for language. Empty ≠ covered."""
    if not globs:
        return False
    wanted = {ext.lstrip(".") for ext in (_LANG_EXTS.get(language) or ())}
    if not wanted:
        return False
    found: set[str] = set()
    for raw in globs:
        g = str(raw).lower()
        found.update(_EXT_IN_GLOB.findall(g))
        for m in re.finditer(r"\.\{([a-z0-9_,]+)\}", g):
            found.update(part.strip() for part in m.group(1).split(",") if part.strip())
    return bool(wanted & found)


def _file_contains_any(path: Path, markers: tuple[str, ...]) -> bool:
    if not path.is_file():
        return False
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return any(marker.encode("ascii", "ignore") in data for marker in markers)


def stryker_runner_present(root: Path) -> bool:
    """AGE-34 Stryker entrypoints: mutation module, marker, or project wrapper."""
    if _file_contains_any(root / "runtime" / "agentized" / "mutation.py", _STRYKER_MARKERS):
        return True
    if _file_contains_any(root / "agentized" / "mutation.py", _STRYKER_MARKERS):
        return True
    if (root / "scripts" / "quality" / "stryker-runner").is_file():
        return True
    if (root / "scripts" / "quality" / "run-mutation-js.cjs").is_file():
        return True
    return (root / "run-mutation-js.cjs").is_file()


def js_architecture_runner_present(root: Path) -> bool:
    if _file_contains_any(
        root / "runtime" / "agentized" / "architecture_gate.py", _JS_ARCH_MARKERS
    ):
        return True
    if _file_contains_any(root / "agentized" / "architecture_gate.py", _JS_ARCH_MARKERS):
        return True
    if (root / "scripts" / "quality" / "architecture-runner").is_file():
        return True
    return (root / "scripts" / "quality" / "run-architecture-js.cjs").is_file()


def js_ts_runners_verified(root: Path, language: str, cfg: dict[str, Any]) -> bool:
    """JS/TS may pass only when AGE-34 runners exist and are configured."""
    if language not in ("javascript", "typescript"):
        return True
    mut = cfg.get("mutation")
    if not isinstance(mut, dict):
        mut = {}
    if mutation_tool_for_language(mut, language) != "stryker":
        return False
    if not stryker_runner_present(root):
        return False
    arch = cfg.get("architecture")
    if not isinstance(arch, dict):
        arch = {}
    arch_tool = architecture_tool_for_language(arch, language)
    if not arch_tool or arch_tool not in (ARCHITECTURE_TOOLS.get(language) or frozenset()):
        return False
    if not js_architecture_runner_present(root):
        return False
    if arch_tool == "dependency-cruiser" and not (arch.get("js_config") or arch.get("config")):
        return False
    return True


def missing_gates_for_language(root: Path, language: str, cfg: dict[str, Any]) -> list[str]:
    """Return SUPPORTED_GATES entries not satisfied for language."""
    missing: list[str] = []
    modules = [m for m in (cfg.get("modules") or []) if isinstance(m, dict)]
    covering = [m for m in modules if _module_has_lang(root, m, language)]
    if not covering or not all(m.get("test_command") for m in covering):
        missing.append(SUPPORTED_GATES[0])
    if not covering or not all(m.get("coverage_lcov") or m.get("coverage_json") for m in covering):
        missing.append(SUPPORTED_GATES[1])

    mut = cfg.get("mutation")
    if not isinstance(mut, dict):
        mut = {}
    tool = mutation_tool_for_language(mut, language)
    allowed = MUTATION_TOOLS.get(language) or frozenset()
    globs = list(mut.get("include_globs") or [])
    mut_enabled = mut.get("enabled")
    if mut_enabled is None:
        mut_enabled = True
    if not (tool and tool in allowed and mut_enabled and _globs_cover(globs, language)):
        missing.append(SUPPORTED_GATES[2])

    smells = cfg.get("test_smells")
    if not isinstance(smells, dict):
        smells = {}
    smell_globs = list(smells.get("include_globs") or [])
    if not (bool(smells.get("enabled")) and _globs_cover(smell_globs, language)):
        missing.append(SUPPORTED_GATES[3])

    arch = cfg.get("architecture")
    if not isinstance(arch, dict):
        arch = {}
    arch_tool = architecture_tool_for_language(arch, language)
    allowed_arch = ARCHITECTURE_TOOLS.get(language) or frozenset()
    arch_ok = False
    if bool(arch.get("enabled")) and arch_tool and arch_tool in allowed_arch:
        if language == "python":
            arch_ok = arch_tool == "builtin" or bool(arch.get("config"))
        elif arch_tool == "dependency-cruiser":
            arch_ok = bool(arch.get("js_config") or arch.get("config"))
        else:
            arch_ok = True
    if not arch_ok:
        missing.append(SUPPORTED_GATES[4])

    if language in ("javascript", "typescript") and not js_ts_runners_verified(root, language, cfg):
        for gate in (SUPPORTED_GATES[2], SUPPORTED_GATES[4]):
            if gate not in missing:
                missing.append(gate)
    return missing


def check_language_coverage(
    root: Path,
    *,
    context: str = DEFAULT_CONTEXT,
    cfg: dict[str, Any] | None = None,
    require_gates: bool = True,
) -> dict[str, Any]:
    if cfg is None:
        cfg = load_quality(root, context)
    section = cfg.get("languages")
    if not isinstance(section, dict):
        section = {}
    if section.get("detect") is False:
        return _text.result(ok=False, message=_text.msg_detect_false())

    supported_raw = section.get("supported")
    if not isinstance(supported_raw, list) or len(supported_raw) == 0:
        return _text.result(ok=False, message=_text.msg_supported_missing())
    supported = [str(x) for x in supported_raw]

    exclude_raw = section.get("exclude_globs")
    if not isinstance(exclude_raw, list) or len(exclude_raw) == 0:
        return _text.result(ok=False, message=_text.msg_exclude_missing())
    exclude = [str(x) for x in exclude_raw]

    illegal = validate_supported_list(supported)
    if illegal:
        msg = _text.msg_illegal_supported(illegal, list(DEFAULT_SUPPORTED), list(SUPPORTED_GATES))
        return _text.result(ok=False, unsupported=illegal, message=msg)

    detected = detect_languages(root, exclude_globs=exclude)
    unsupported = sorted(lang for lang in detected if lang not in supported)
    missing_gates: dict[str, list[str]] = {}
    if require_gates:
        for lang in sorted(detected):
            if lang in supported and lang in _LANG_EXTS:
                bad = missing_gates_for_language(root, lang, cfg)
                if bad:
                    missing_gates[lang] = bad

    if unsupported or missing_gates:
        msg = _text.msg_coverage_incomplete(
            unsupported, missing_gates, detected, SUPPORTED_GATES
        )
        return _text.result(
            ok=False,
            detected=detected,
            unsupported=unsupported,
            missing_gates=missing_gates,
            message=msg,
        )

    return _text.result(ok=True, detected=detected, message=_text.msg_ok(detected))
