"""Hard gate: PR diffs must not add formatter/linter disable comments.

T-261121-8c84 / Maxim: fail closed when a PR *adds* ``# fmt: off``, ``# fmt: skip``,
``# noqa``-style (and close relatives) in Python sources. No allowlist unless Maxim
approves a follow-up sole-purpose PR.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .process_size import validate_process_base

DOC = "docs/QUALITY.md"

# Ban lexemes used to game format/size. Matched on added ``*.py`` diff lines only.
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

_HUNK_NEW = re.compile(r"\+(\d+)(?:,\d+)?")


def is_python_path(path: str) -> bool:
    """True for Python sources (``.py`` / ``.pyi``). Docs/tasks are out of scope."""
    lowered = path.lower()
    return lowered.endswith(".py") or lowered.endswith(".pyi")


def line_has_disable(text: str) -> bool:
    """True when *text* contains a banned formatter/linter disable comment."""
    return _DISABLE_RE.search(text) is not None


def parse_unified_added_hits(diff_text: str) -> list[tuple[str, int, str]]:
    """Return ``(path, new_lineno, line)`` for added Python lines with disables."""
    findings: list[tuple[str, int, str]] = []
    path = ""
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            rest = raw[4:]
            if rest.startswith("b/"):
                path = rest[2:]
            elif rest == "/dev/null":
                path = ""
            else:
                path = rest
            continue
        if raw.startswith("@@"):
            match = _HUNK_NEW.search(raw)
            new_line = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            content = raw[1:]
            if path and is_python_path(path) and line_has_disable(content):
                findings.append((path, new_line, content))
            if new_line > 0:
                new_line += 1
            continue
        if raw.startswith("-") and not raw.startswith("---"):
            continue
        if raw.startswith(" ") and new_line > 0:
            new_line += 1
    return findings


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )


def diff_unified(root: Path, base_ref: str) -> str:
    """``git diff -U0`` vs base (triple-dot, then two-dot). Fail closed on git errors."""
    triple = f"{base_ref}...HEAD"
    proc = _run_git(root, ["git", "diff", "--unified=0", triple])
    if proc.returncode != 0:
        proc = _run_git(root, ["git", "diff", "--unified=0", base_ref])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(
            f"format-disable-gate: git diff failed for {base_ref!r}: {detail}. See {DOC}."
        )
    return proc.stdout


def format_findings_message(base: str, findings: list[tuple[str, int, str]]) -> str:
    """Human-readable failure (or empty findings → still a count header)."""
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
    """Canonical format-disable gate: base ancestry + added-line scan. No allowlist."""
    base = base_ref or os.environ.get("PROCESS_BASE") or "origin/main"
    try:
        validate_process_base(root, base)
        diff = diff_unified(root, base)
        findings = parse_unified_added_hits(diff)
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
