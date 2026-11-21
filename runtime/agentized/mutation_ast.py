"""AST-equivalent exclusion for the incremental mutation gate (AGE-55).

Files whose ``ast.dump(ast.parse(x), include_attributes=False)`` matches the
base blob are dropped from the mutation set (format/wrap/quote noops). Missing
base, parse errors, and git/read errors stay in scope (fail-closed).

Wired from ``agentized quality check`` so ``mutation.py`` stays untouched
(whole-file mutation would otherwise re-open the full gate surface).
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from .paths import DEFAULT_CONTEXT


def ast_dump(source: str) -> str | None:
    """Stable AST fingerprint, or None on parse failure (fail-closed → keep)."""
    try:
        return ast.dump(ast.parse(source), include_attributes=False)
    except SyntaxError:
        return None


def git_show_blob(root: Path, ref: str, path: str) -> str | None:
    """Blob text at ref:path, or None on missing/git error (fail-closed → keep)."""
    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def read_workdir_blob(root: Path, path: str) -> str | None:
    """Working-tree file text, or None on read error (fail-closed → keep)."""
    try:
        return (root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def exclude_ast_equivalent(
    root: Path, base_ref: str, paths: list[str]
) -> tuple[list[str], list[str]]:
    """Drop AST-noop files; keep on missing base / parse / git errors.

    Returns ``(kept, excluded)`` preserving input order within each list.
    """
    kept: list[str] = []
    excluded: list[str] = []
    for path in paths:
        base_text = git_show_blob(root, base_ref, path)
        head_text = read_workdir_blob(root, path)
        if base_text is None or head_text is None:
            kept.append(path)
            continue
        base_key = ast_dump(base_text)
        head_key = ast_dump(head_text)
        if base_key is None or head_key is None:
            kept.append(path)
            continue
        if base_key == head_key:
            excluded.append(path)
        else:
            kept.append(path)
    return kept, excluded


def run_mutation(root: Path | None = None, *, context: str = DEFAULT_CONTEXT) -> int:
    """Run the mutation gate with AST-equivalent files excluded."""
    from . import mutation as m

    resolved = root if root is not None else m.find_repo_root()
    excluded_holder: list[str] = []

    orig_changed = m._changed_py_files
    orig_summary = m._write_summary

    def changed_with_ast(root_: Path, base_ref: str, prefixes: list[str]) -> list[str]:
        paths = orig_changed(root_, base_ref, prefixes)
        # include_globs still applied inside mutation.run_mutation after this.
        kept, excluded = exclude_ast_equivalent(resolved, base_ref, paths)
        excluded_holder.clear()
        excluded_holder.extend(excluded)
        if excluded:
            print(f"[mutation] AST-equivalent excluded ({len(excluded)}):")
            for name in excluded:
                print(f"  exclude {name}")
        return kept

    def write_summary_with_ast(root_: Path, payload: dict) -> Path:
        enriched = {**payload, "astExcludedFiles": list(excluded_holder)}
        return orig_summary(root_, enriched)

    m._changed_py_files = changed_with_ast
    m._write_summary = write_summary_with_ast
    try:
        return m.run_mutation(resolved, context=context)
    finally:
        m._changed_py_files = orig_changed
        m._write_summary = orig_summary


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    return run_mutation(context=context)


if __name__ == "__main__":
    raise SystemExit(main())
