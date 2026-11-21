"""Hard gate: PR diffs must not add formatter/linter disable comments.

T-261121-8c84 / Maxim: fail closed when a PR adds formatter/linter disable
*comments* in Python sources (fmt off/skip/on, noqa-style, and close relatives).
No allowlist unless Maxim approves a follow-up sole-purpose PR.

Detection uses the tokenize module so string/docstring mentions do not count —
only real COMMENT tokens. Existing disables on the base are grandfathered;
only net-new comment tokens vs base fail the gate.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import tokenize
from collections import Counter
from pathlib import Path
from typing import Any

from .process_size import validate_process_base

DOC = "docs/QUALITY.md"

# Ban lexemes used to game format/size. Matched on COMMENT token strings only.
_DISABLE_RE = re.compile(
    r"(?:"
    r"#\s*fmt\s*:\s*(?:off|skip|on)\b"
    r"|#\s*noqa\b"
    r"|#\s*ruff\s*:\s*noqa\b"
    r"|#\s*flake8\s*:\s*noqa\b"
    r"|#\s*isort\s*:\s*(?:skip|off)\b"
    r"|#\s*yapf\s*:\s*disable\b"
    r")",
    re.IGNORECASE,
)


def is_python_path(path: str) -> bool:
    """True for Python sources (``.py`` / ``.pyi``). Docs/tasks are out of scope."""
    lowered = path.lower()
    return lowered.endswith(".py") or lowered.endswith(".pyi")


def line_has_disable(text: str) -> bool:
    """True when *text* contains a banned formatter/linter disable lexeme."""
    return _DISABLE_RE.search(text) is not None


def disable_comments_in_source(src: str) -> list[tuple[int, str]]:
    """Return ``(lineno, comment)`` for banned COMMENT tokens in *src*.

    Tokenize errors fail closed: the whole file is treated as one synthetic
    finding so a broken/unparseable added file cannot sneak past the gate.
    """
    out: list[tuple[int, str]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT and line_has_disable(tok.string):
                out.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError):
        if line_has_disable(src):
            out.append((0, "<untokenizeable source with disable lexeme>"))
    return out


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )


def changed_python_files(root: Path, base_ref: str) -> list[str]:
    """Paths of added/changed Python files vs base (ACMR). Fail closed on git errors."""
    triple = f"{base_ref}...HEAD"
    proc = _run_git(
        root,
        ["git", "diff", "--name-only", "--diff-filter=ACMR", triple],
    )
    if proc.returncode != 0:
        proc = _run_git(
            root,
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref],
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(
            f"format-disable-gate: git diff failed for {base_ref!r}: {detail}. See {DOC}."
        )
    return [p for p in proc.stdout.splitlines() if p and is_python_path(p)]


def git_show_text(root: Path, rev: str, path: str) -> str | None:
    """Return file text at *rev*:*path*, or None if missing."""
    proc = _run_git(root, ["git", "show", f"{rev}:{path}"])
    if proc.returncode != 0:
        return None
    return proc.stdout


def read_head_text(root: Path, path: str) -> str:
    """Read working-tree / HEAD file; missing file → empty string."""
    full = root / path
    if full.is_file():
        return full.read_text(encoding="utf-8")
    shown = git_show_text(root, "HEAD", path)
    return shown if shown is not None else ""


def new_disable_findings(root: Path, base_ref: str, path: str) -> list[tuple[str, int, str]]:
    """Net-new banned COMMENT tokens in *path* vs base (multiset difference)."""
    head_src = read_head_text(root, path)
    base_src = git_show_text(root, base_ref, path) or ""
    head_comments = disable_comments_in_source(head_src)
    base_comments = disable_comments_in_source(base_src)
    # Compare by comment text multiset; report head locations for leftovers.
    remaining = Counter(text for _, text in base_comments)
    findings: list[tuple[str, int, str]] = []
    for lineno, text in head_comments:
        if remaining[text] > 0:
            remaining[text] -= 1
            continue
        findings.append((path, lineno, text))
    return findings


def format_findings_message(base: str, findings: list[tuple[str, int, str]]) -> str:
    """Human-readable failure header (+ per-finding lines when present)."""
    header = (
        f"format-disable-gate: PR adds {len(findings)} formatter/linter disable "
        f"comment(s) vs {base} (no allowlist). Remove them or get Maxim approval. "
        f"See {DOC}."
    )
    if not findings:
        return header
    body = "\n".join(f"  {path}:{lineno}: {text.rstrip()}" for path, lineno, text in findings)
    return f"{header}\n{body}"


def format_disable_check(
    root: Path,
    *,
    base_ref: str | None = None,
) -> dict[str, Any]:
    """Canonical format-disable gate: base ancestry + net-new COMMENT scan."""
    base = base_ref or os.environ.get("PROCESS_BASE") or "origin/main"
    try:
        validate_process_base(root, base)
        paths = changed_python_files(root, base)
        findings: list[tuple[str, int, str]] = []
        for path in paths:
            findings.extend(new_disable_findings(root, base, path))
    except (RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "level": "error",
            "base": base,
            "findings": [],
            "message": str(exc),
        }
    if findings:
        return {
            "ok": False,
            "level": "fail",
            "base": base,
            "findings": [{"path": p, "line": n, "text": t} for p, n, t in findings],
            "message": format_findings_message(base, findings),
        }
    return {
        "ok": True,
        "level": "ok",
        "base": base,
        "findings": [],
        "message": (
            f"format-disable-gate: no new fmt/noqa-style disable comments vs {base}. See {DOC}."
        ),
    }
