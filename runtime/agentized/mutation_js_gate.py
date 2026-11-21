"""Multi-language mutation entry (AGE-34): Stryker for JS/TS, mutmut for Python."""
from __future__ import annotations

import os
from pathlib import Path

from .gate_dispatch import (
    changed_source_files,
    language_for_path,
    mutation_tool_for_language,
)
from .mutation import _write_summary, run_mutation as run_mutmut
from .mutation_stryker import run_stryker_gate
from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality


def run_mutation(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    mut = cfg.get("mutation") or {}
    if not mut.get("enabled", True):
        return run_mutmut(root, context=context)

    base = os.environ.get("MUTATION_BASE") or mut.get("base_ref") or "origin/main"
    min_score = float(mut.get("min_score_covered", 100))
    prefixes = [
        str(src).replace("\\", "/")
        for module in cfg.get("modules") or []
        for src in module.get("source") or []
    ] or ["runtime/agentized"]

    changed = changed_source_files(root, base, prefixes)
    include_globs = list(mut.get("include_globs") or [])
    if include_globs:
        import fnmatch

        changed = [
            path
            for path in changed
            if any(fnmatch.fnmatch(path, pat) for pat in include_globs)
        ]

    by_lang: dict[str, list[str]] = {}
    for path in changed:
        lang = language_for_path(path) or "unknown"
        by_lang.setdefault(lang, []).append(path)

    js_files: list[str] = []
    js_langs: list[str] = []
    missing: list[str] = []
    for lang, files in sorted(by_lang.items()):
        if lang == "python":
            continue
        tool = mutation_tool_for_language(mut, lang)
        if tool == "stryker":
            js_files.extend(files)
            js_langs.append(lang)
            continue
        missing.append(f"{lang} ({len(files)} file(s))")

    if missing:
        path = _write_summary(
            root,
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
        print(
            "[mutation] FAIL: no runner for changed files: "
            + ", ".join(missing)
            + f" (see {path.relative_to(root)})",
            flush=True,
        )
        return 1

    if js_files:
        rc = run_stryker_gate(
            root,
            changed=sorted(set(js_files)),
            mut=mut,
            base=base,
            min_score=min_score,
            languages=sorted(js_langs),
            write_summary=_write_summary,
        )
        if rc != 0:
            return rc

    return run_mutmut(root, context=context)
