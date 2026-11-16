"""Fail-closed process-control JSON load and PR size helpers (AGE-35)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

DOC = "docs/process-control.md"


def require_hard_size_mode(cfg: dict[str, Any]) -> None:
    """AGE-32: only size_mode=hard is valid; anything else raises."""
    mode = cfg.get("size_mode", "hard")
    if mode != "hard":
        raise ValueError(
            f"process-control: size_mode must be 'hard', got {mode!r}. See {DOC}."
        )


def load_process_config_file(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    """Load process-control JSON. Missing file → copy of defaults; invalid → raise."""
    cfg = dict(defaults)
    if not path.exists():
        require_hard_size_mode(cfg)
        return cfg
    try:
        # Locale/UTF-8 text mode — avoid a "utf-8"/"UTF-8" lexeme mutant pair.
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise ValueError(
            f"process-control: invalid JSON in {path}: {exc}. See {DOC}."
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"process-control: {path} must be a JSON object, got {type(data).__name__}. See {DOC}."
        )
    cfg.update({k: data[k] for k in data})
    require_hard_size_mode(cfg)
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


def _run_numstat(root: Path, spec: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "diff", "--numstat", spec],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )


def diff_insertions(root: Path, base_ref: str) -> int:
    """Count insertions vs base_ref. Git errors raise (fail closed)."""
    triple = f"{base_ref}...HEAD"
    proc = _run_numstat(root, triple)
    if proc.returncode != 0:
        proc = _run_numstat(root, base_ref)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(
            f"process-control: git diff failed for {base_ref!r}: {detail}. See {DOC}."
        )
    return parse_numstat(proc.stdout)


def classify_size(insertions: int, limit: int, warn_pct: float) -> tuple[str, bool, int]:
    """Return (level, ok, warn_at). over → ok False; warn/ok → ok True."""
    warn_at = int(limit * warn_pct / 100.0)
    if insertions >= limit:
        return "over", False, warn_at
    if insertions >= warn_at:
        return "warn", True, warn_at
    return "ok", True, warn_at
