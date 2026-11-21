"""Hard gate: PR must not add formatter/linter/coverage/mutation disables.

T-261121-8c84 / Maxim: fail closed on net-new disable *comments* and config
exclude/omit keys used to game format, size, coverage, or mutation. No allowlist
unless Maxim approves a sole-purpose follow-up.

HEAD blob only (no working-tree fallback). Renames use the old path for base.
Non-UTF-8 blobs fail closed and name the file.
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

from .process_size import _run_git, validate_process_base

DOC = "docs/QUALITY.md"
DEFAULT_BASE = "origin/main"
_FILE_ENCODING = "utf-8"
_DIFF_FILTER = "ACMR"
_UNTTOKEN_MSG = "<untokenizeable source with disable lexeme>"
_HEAD = "HEAD"

# Python / pyw comment disables (tokenize COMMENT tokens).
_PY_DISABLE_RE = re.compile(
    r"(?:"
    r"#\s*fmt\s*:\s*(?:off|skip|on)\b"
    r"|#\s*noqa\b"
    r"|#\s*ruff\s*:\s*noqa\b"
    r"|#\s*flake8\s*:\s*noqa\b"
    r"|#\s*isort\s*:\s*(?:skip|off)\b"
    r"|#\s*yapf\s*:\s*disable\b"
    r"|#\s*pragma\s*:\s*no\s+(?:cover|mutate)\b"
    r"|#\s*type\s*:\s*ignore\b"
    r"|#\s*pylint\s*:\s*disable\b"
    r"|#\s*mypy\s*:\s*ignore-errors\b"
    r"|#\s*pyright\s*:\s*ignore\b"
    r")",
    re.IGNORECASE,
)

# JS/TS comment disables (// and /* */ regions).
_JS_DISABLE_RE = re.compile(
    r"(?:"
    r"eslint-disable(?:(?:-next)?-line)?\b"
    r"|prettier-ignore\b"
    r"|@ts-(?:ignore|nocheck|expect-error)\b"
    r"|stryker\s+disable\b"
    r")",
    re.IGNORECASE,
)
_JS_LINE_COMMENT = re.compile(r"//.*$")
_JS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

# Config keys that dodge format/lint/coverage/mutation gates.
_CONFIG_DISABLE_RE = re.compile(
    r"(?:"
    r"per-file-ignores"
    r"|extend-exclude"
    r"|^\s*exclude\s*="
    r"|^\s*omit\s*="
    r"|paths_to_exclude"
    r"|excluded_lines"
    r"|disable_mutation"
    r"|ignorePatterns"
    r"|disableComments"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_PY_SUFFIXES = (".py", ".pyi", ".pyw")
_JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_CONFIG_NAMES = frozenset(
    {
        "pyproject.toml",
        "setup.cfg",
        ".coveragerc",
        "tox.ini",
        ".mutmut.toml",
        "mutmut_config.py",
        "stryker.config.mjs",
        "stryker.config.js",
        "stryker.conf.json",
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.json",
        ".eslintrc.yml",
        ".eslintrc.yaml",
        "eslint.config.js",
        "eslint.config.mjs",
        ".prettierrc",
        ".prettierrc.js",
        ".prettierrc.cjs",
        ".prettierrc.json",
        ".prettierrc.yml",
        ".prettierrc.yaml",
    }
)


def is_python_path(path: str) -> bool:
    """True for ``.py`` / ``.pyi`` / ``.pyw``."""
    lowered = path.lower()
    return any(lowered.endswith(s) for s in _PY_SUFFIXES)


def is_js_path(path: str) -> bool:
    """True for JS/TS sources."""
    lowered = path.lower()
    return any(lowered.endswith(s) for s in _JS_SUFFIXES)


def is_config_path(path: str) -> bool:
    """True for known lint/coverage/mutation config basenames."""
    return Path(path).name.lower() in _CONFIG_NAMES


def is_scannable_path(path: str) -> bool:
    return is_python_path(path) or is_js_path(path) or is_config_path(path)


def line_has_disable(text: str) -> bool:
    """True when *text* contains a banned Python disable lexeme."""
    return _PY_DISABLE_RE.search(text) is not None


def line_has_js_disable(text: str) -> bool:
    return _JS_DISABLE_RE.search(text) is not None


def line_has_config_disable(text: str) -> bool:
    return _CONFIG_DISABLE_RE.search(text) is not None


def disable_comments_in_source(src: str) -> list[tuple[int, str]]:
    """Banned COMMENT tokens in Python source (docstrings/strings ignored)."""
    out: list[tuple[int, str]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT and line_has_disable(tok.string):
                out.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError):
        if line_has_disable(src):
            out.append((0, _UNTTOKEN_MSG))
    return out


def js_disable_comments_in_source(src: str) -> list[tuple[int, str]]:
    """Banned lexemes inside ``//`` or ``/* */`` comments (not string-aware deeply)."""
    out: list[tuple[int, str]] = []
    # Block comments may span lines — attribute to start line.
    for match in _JS_BLOCK_COMMENT.finditer(src):
        chunk = match.group(0)
        if line_has_js_disable(chunk):
            lineno = src[: match.start()].count("\n") + 1
            out.append((lineno, chunk.splitlines()[0][:120]))
    for lineno, line in enumerate(src.splitlines(), 1):
        m = _JS_LINE_COMMENT.search(line)
        if m is None:
            continue
        comment = m.group(0)
        if line_has_js_disable(comment):
            out.append((lineno, comment.rstrip()))
    return out


def config_disable_lines(src: str) -> list[tuple[int, str]]:
    """Banned config keys / omit lines (whole matching lines)."""
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(src.splitlines(), 1):
        if line_has_config_disable(line):
            out.append((lineno, line.rstrip()))
    return out


def disables_in_file(path: str, src: str) -> list[tuple[int, str]]:
    """Dispatch by path kind."""
    if is_python_path(path):
        return disable_comments_in_source(src)
    if is_js_path(path):
        return js_disable_comments_in_source(src)
    if is_config_path(path):
        return config_disable_lines(src)
    return []


def _run_git_bytes(root: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        cwd=str(root),
        capture_output=True,
        check=False,
    )


def git_show_text(root: Path, rev: str, path: str) -> str | None:
    """Return UTF-8 file text at *rev*:*path*, or None if missing.

    Non-UTF-8 content raises ``RuntimeError`` naming *path*.
    """
    proc = _run_git_bytes(root, ["git", "show", f"{rev}:{path}"])
    if proc.returncode != 0:
        return None
    try:
        return proc.stdout.decode(_FILE_ENCODING)
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"format-disable-gate: non-UTF-8 file {path!r} at {rev}: {exc}. See {DOC}."
        ) from exc


def read_head_text(root: Path, path: str) -> str:
    """Read HEAD blob only (no working-tree fallback). Missing → empty string."""
    shown = git_show_text(root, _HEAD, path)
    if shown is None:
        return ""
    return shown


def parse_name_status(stdout: str) -> list[tuple[str, str | None]]:
    """Parse ``git diff --name-status`` into ``(head_path, base_path|None)``.

    Renames (``R*``) and copies (``C*``) map head → old path for base lookup.
    """
    rows: list[tuple[str, str | None]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") or status.startswith("C"):
            if len(parts) < 3:
                continue
            old, new = parts[1], parts[2]
            rows.append((new, old))
            continue
        if len(parts) < 2:
            continue
        path = parts[1]
        if status.startswith("A"):
            rows.append((path, None))
        else:
            rows.append((path, path))
    return rows


def changed_scan_targets(root: Path, base_ref: str) -> list[tuple[str, str | None]]:
    """Scannable ``(head_path, base_path|None)`` with rename follow. Fail closed."""
    triple = f"{base_ref}...{_HEAD}"
    proc = _run_git(
        root,
        [
            "git",
            "diff",
            "--name-status",
            "--find-renames",
            f"--diff-filter={_DIFF_FILTER}",
            triple,
        ],
    )
    if proc.returncode != 0:
        proc = _run_git(
            root,
            [
                "git",
                "diff",
                "--name-status",
                "--find-renames",
                f"--diff-filter={_DIFF_FILTER}",
                base_ref,
            ],
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(
            f"format-disable-gate: git diff failed for {base_ref!r}: {detail}. See {DOC}."
        )
    return [
        (head, base)
        for head, base in parse_name_status(proc.stdout)
        if head and is_scannable_path(head)
    ]


def changed_python_files(root: Path, base_ref: str) -> list[str]:
    """Compat: head paths of changed Python sources (incl. renames)."""
    return [h for h, _ in changed_scan_targets(root, base_ref) if is_python_path(h)]


def new_disable_findings(
    root: Path, base_ref: str, head_path: str, base_path: str | None
) -> list[tuple[str, int, str]]:
    """Net-new disables in *head_path* vs base blob at *base_path* (or empty)."""
    head_src = read_head_text(root, head_path)
    if base_path is None:
        base_src = ""
    else:
        base_raw = git_show_text(root, base_ref, base_path)
        base_src = "" if base_raw is None else base_raw
    # Scanner kind follows head path (rename destination).
    head_hits = disables_in_file(head_path, head_src)
    base_hits = disables_in_file(head_path, base_src)
    # Compare by disable text multiset; report head locations for leftovers.
    remaining = Counter(text for _, text in base_hits)
    findings: list[tuple[str, int, str]] = []
    for lineno, text in head_hits:
        if remaining[text] > 0:
            remaining[text] -= 1
            continue
        findings.append((head_path, lineno, text))
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
    """Canonical format-disable gate: base ancestry + net-new disable scan."""
    base = base_ref or os.environ.get("PROCESS_BASE") or DEFAULT_BASE
    try:
        validate_process_base(root, base)
        targets = changed_scan_targets(root, base)
        findings: list[tuple[str, int, str]] = []
        for head_path, base_path in targets:
            findings.extend(new_disable_findings(root, base, head_path, base_path))
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
