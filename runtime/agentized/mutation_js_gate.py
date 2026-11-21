"""Multi-language mutation entry (AGE-34): Stryker + mutmut."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .gate_dispatch import changed_source_files, language_for_path, mutation_tool_for_language
from .mutation import _write_summary
from .mutation_ast import run_mutation as run_mutmut
from .mutation_stryker import run_stryker_gate
from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

_DEFAULT_PREFIXES, _DEFAULT_BASE, _DEFAULT_MIN = ["runtime/agentized"], "origin/main", 100.0


def run_mutation(root: Path | None = None, *, context: str = DEFAULT_CONTEXT) -> int:
    resolved = find_repo_root() if root is None else root
    cfg = load_quality(resolved, context)
    mut = cfg.get("mutation") or {}
    if mut.get("enabled") is False:
        return run_mutmut(resolved, context=context)
    base = os.environ.get("MUTATION_BASE") or mut.get("base_ref") or _DEFAULT_BASE
    min_score = float(mut["min_score_covered"]) if "min_score_covered" in mut else _DEFAULT_MIN
    prefixes = [
        str(src).replace("\\", "/")
        for module in (cfg.get("modules") or [])
        for src in (module.get("source") or [])
    ] or list(_DEFAULT_PREFIXES)
    changed = changed_source_files(resolved, base, prefixes)
    include_globs = list(mut.get("include_globs") or [])
    if include_globs:
        changed = [p for p in changed if any(fnmatch.fnmatch(p, pat) for pat in include_globs)]
    by_lang: dict[str, list[str]] = {}
    for path in changed:
        by_lang.setdefault(language_for_path(path) or "unknown", []).append(path)
    js_files: list[str] = []
    js_langs: list[str] = []
    missing: list[str] = []
    for lang, files in sorted(by_lang.items()):
        if lang == "python":
            continue
        if mutation_tool_for_language(mut, lang) == "stryker":
            js_files.extend(files)
            js_langs.append(lang)
        else:
            missing.append(f"{lang}:{len(files)}")
    if missing:
        _write_summary(
            resolved,
            {
                "schemaVersion": 1,
                "mode": "incremental",
                "base": base,
                "gate": "hard",
                "passed": False,
                "reasons": ["no_mutation_runner"],
                "missingRunners": missing,
                "changedFiles": changed,
            },
        )
        return 1
    if js_files:
        rc = run_stryker_gate(
            resolved,
            changed=sorted(set(js_files)),
            mut=mut,
            base=base,
            min_score=min_score,
            languages=sorted(js_langs),
            write_summary=_write_summary,
        )
        if rc != 0:
            return rc
    return run_mutmut(resolved, context=context)
