"""Fail-closed process-control JSON load and PR size helpers (AGE-35 / AGE-40)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT

DOC = "docs/process-control.md"
HARD_CAP = 1500
# Exact lowercase codec — avoid utf-8/UTF-8 lexeme mutants surviving decode.
_CONFIG_ENCODING = "utf-8"
# Git empty-tree OID — first-push baseline when origin/main is not fetched yet.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def validate_size_fields(cfg: dict[str, Any], *, path: Path | None = None) -> tuple[int, float]:
    """Require reviewable_lines int 1..1500 and warn_at_pct number 1..100."""
    where = f" in {path}" if path is not None else ""
    raw_limit = cfg.get("reviewable_lines")
    if isinstance(raw_limit, bool) or type(raw_limit) is not int:
        raise ValueError(
            f"process-control: reviewable_lines must be an int 1..{HARD_CAP}{where}, "
            f"got {raw_limit!r}. See {DOC}."
        )
    if raw_limit < 1 or raw_limit > HARD_CAP:
        raise ValueError(
            f"process-control: reviewable_lines must be an int 1..{HARD_CAP}{where}, "
            f"got {raw_limit!r}. See {DOC}."
        )
    raw_warn = cfg.get("warn_at_pct")
    if isinstance(raw_warn, bool) or not isinstance(raw_warn, (int, float)):
        raise ValueError(
            f"process-control: warn_at_pct must be a number 1..100{where}, "
            f"got {raw_warn!r}. See {DOC}."
        )
    warn_pct = float(raw_warn)
    if warn_pct < 1 or warn_pct > 100:
        raise ValueError(
            f"process-control: warn_at_pct must be a number 1..100{where}, "
            f"got {raw_warn!r}. See {DOC}."
        )
    return raw_limit, warn_pct


def load_process_config_file(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    """Load process-control JSON. Missing file → copy of defaults; invalid → raise."""
    cfg = dict(defaults)
    if not path.exists():
        validate_size_fields(cfg, path=path)
        return cfg
    try:
        data = json.loads(path.read_bytes().decode(_CONFIG_ENCODING))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise ValueError(f"process-control: invalid JSON in {path}: {exc}. See {DOC}.") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"process-control: {path} must be a JSON object, got {type(data).__name__}. See {DOC}."
        )
    cfg.update({k: data[k] for k in data})
    validate_size_fields(cfg, path=path)
    return cfg


def parse_numstat(stdout: str) -> int:
    """Sum added lines from ``git diff --numstat`` stdout (tab-separated)."""
    total = 0
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            total += int(parts[0])
        except ValueError:
            continue
    return total


def is_connect_bootstrap_path(path: str, context_rel: str = DEFAULT_CONTEXT) -> bool:
    """True for paths Agentized connect installs (AGE-85 baseline exemption only)."""
    # Do NOT use str.lstrip("./") — that strips every leading '.'/'/' char
    # (".githooks/x" → "githooks/x"). Only drop an optional "./" prefix.
    rel = path.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    if rel == "AGENTS.md":
        return True
    prefixes = (
        ".githooks/",
        ".github/workflows/",
        ".cursor/",
        ".claude/",
        ".codex/",
        ".agents/",
        ".agentized/",
        f"{context_rel}/",
    )
    return rel.startswith(prefixes)


def parse_numstat_excluding_bootstrap(stdout: str, context_rel: str = DEFAULT_CONTEXT) -> int:
    """Sum insertions excluding connect bootstrap paths (AGE-85)."""
    kept = [
        line
        for line in stdout.splitlines()
        if not is_connect_bootstrap_path(line.split("\t")[-1], context_rel)
    ]
    return parse_numstat("\n".join(kept))


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_numstat(root: Path, spec: str) -> subprocess.CompletedProcess[str]:
    return _run_git(root, ["git", "diff", "--numstat", spec])


def _managed_rel(context_rel: str) -> str:
    return f"{context_rel}/.agentized/managed.json"


def head_has_connect_managed(root: Path, context_rel: str = DEFAULT_CONTEXT) -> bool:
    return (root / _managed_rel(context_rel)).is_file()


def _ref_has_path(root: Path, ref: str, rel: str) -> bool:
    return _run_git(root, ["git", "cat-file", "-e", f"{ref}:{rel}"]).returncode == 0


def ref_exists(root: Path, ref: str) -> bool:
    return _run_git(root, ["git", "rev-parse", "--verify", ref]).returncode == 0


def _numstat_stdout(root: Path, base_ref: str) -> str:
    triple = f"{base_ref}...HEAD"
    proc = _run_numstat(root, triple)
    if proc.returncode != 0:
        proc = _run_numstat(root, base_ref)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(
            f"process-control: git diff failed for {base_ref!r}: {detail}. See {DOC}."
        )
    return proc.stdout


def diff_insertions(root: Path, base_ref: str) -> int:
    """Count insertions vs base_ref. Git errors raise (fail closed)."""
    return parse_numstat(_numstat_stdout(root, base_ref))


def diff_insertions_excluding_bootstrap(
    root: Path, base_ref: str, context_rel: str = DEFAULT_CONTEXT
) -> int:
    """Insertions vs base, ignoring connect-installed bootstrap paths."""
    return parse_numstat_excluding_bootstrap(_numstat_stdout(root, base_ref), context_rel)


def validate_process_base(root: Path, base_ref: str) -> None:
    """Refuse HEAD / @ and bases that are not ancestors of origin/main."""
    cleaned = (base_ref or "").strip()
    if cleaned in {"", "@"} or cleaned.upper() == "HEAD":
        raise ValueError(
            f"process-control: base ref must not be HEAD (got {base_ref!r}). "
            f"Use origin/main or the PR base sha. See {DOC}."
        )
    main = _run_git(root, ["git", "rev-parse", "--verify", "origin/main"])
    if main.returncode != 0:
        detail = (main.stderr or main.stdout or "").strip() or f"exit {main.returncode}"
        raise RuntimeError(
            f"process-control: origin/main unavailable for base check: {detail}. See {DOC}."
        )
    anc = _run_git(root, ["git", "merge-base", "--is-ancestor", cleaned, "origin/main"])
    if anc.returncode != 0:
        raise ValueError(
            f"process-control: base {base_ref!r} must be an ancestor of origin/main. See {DOC}."
        )


def limit_from_base_ref(root: Path, base_ref: str, context_rel: str) -> int | None:
    """Read reviewable_lines from base ref config (blocks self-raising the limit)."""
    spec = f"{base_ref}:{context_rel}/process-control.json"
    proc = _run_git(root, ["git", "show", spec])
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("reviewable_lines")
    if isinstance(raw, bool) or type(raw) is not int:
        return None
    if raw < 1 or raw > HARD_CAP:
        return None
    return raw


def classify_size(insertions: int, limit: int, warn_pct: float) -> tuple[str, bool, int]:
    """Return (level, ok, warn_at). Inclusive limit: over only when insertions > limit."""
    warn_at = int(limit * warn_pct / 100.0)
    if insertions > limit:
        return "over", False, warn_at
    if insertions >= warn_at:
        return "warn", True, warn_at
    return "ok", True, warn_at


def size_check(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    base_ref: str | None = None,
) -> dict[str, Any]:
    """Canonical PR size gate (AGE-40): base ancestry, field validation, base-limit cap.

    AGE-85: when establishing a connect baseline (HEAD has
    ``{context}/.agentized/managed.json`` but the size base does not), count only
    non-bootstrap insertions. Not a generic bypass — user paths still gate.
    """
    # Lazy import: process_control imports helpers from this module.
    from .process_control import load_process_config

    base = base_ref or os.environ.get("PROCESS_BASE") or "origin/main"
    baseline_note = ""
    try:
        cfg = load_process_config(root, context_rel)
        limit, warn_pct = validate_size_fields(cfg)
        managed_rel = _managed_rel(context_rel)
        head_managed = head_has_connect_managed(root, context_rel)
        # First push to empty remote: origin/main missing, connect just installed.
        if base == "origin/main" and head_managed and not ref_exists(root, base):
            insertions = diff_insertions_excluding_bootstrap(root, EMPTY_TREE, context_rel)
            baseline_note = " connect-baseline (no origin/main; bootstrap paths excluded)"
        else:
            validate_process_base(root, base)
            base_limit = limit_from_base_ref(root, base, context_rel)
            if base_limit is not None:
                limit = min(limit, base_limit)
            base_has_managed = _ref_has_path(root, base, managed_rel)
            if head_managed and not base_has_managed:
                insertions = diff_insertions_excluding_bootstrap(root, base, context_rel)
                baseline_note = " connect-baseline (bootstrap paths excluded)"
            else:
                insertions = diff_insertions(root, base)
    except (RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "level": "error",
            "insertions": 0,
            "limit": 0,
            "warn_at": 0,
            "base": base,
            "message": str(exc),
        }
    level, ok, warn_at = classify_size(insertions, limit, warn_pct)
    return {
        "ok": ok,
        "level": level,
        "insertions": insertions,
        "limit": limit,
        "warn_at": warn_at,
        "base": base,
        "message": (
            f"process-control: PR size {insertions} insertions vs {base}"
            f"{baseline_note} "
            f"(warn ≥{warn_at} = {warn_pct}% of {limit}; over >{limit}; ≤{limit} OK). See {DOC}."
        ),
    }
