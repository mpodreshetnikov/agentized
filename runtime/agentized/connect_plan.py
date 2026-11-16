"""Pure connect dry-run action helpers (AGE-36) — mutation include_globs.

Assembler that inventories all paths lives in connect_dry_run (I/O wiring).
Accuracy rules from Lead #21 item 6 live here as testable decisions:
- quality.json may update (warn→hard / --coverage), never a false skip
- pin trees: skip when content identical to source
- refuse exit code for dry-run/uninstall
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .connect import QUALITY_MARKER
from .paths import CONNECT_MARKER_BEGIN, CONNECT_MARKER_END
from .quality import load_quality, quality_path

ALLOWED_ACTIONS = frozenset({"create", "update", "merge", "skip", "refuse"})


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digests(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    out: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        out[rel] = file_digest(path)
    return out


def trees_identical(src: Path, dst: Path) -> bool:
    return tree_digests(src) == tree_digests(dst)


def plan_pin_tree_action(dst: Path, src: Path | None = None) -> str:
    """Compare content → skip if identical; create if missing; else update."""
    if not dst.exists():
        return "create"
    if src is None or not src.exists():
        return "update"
    if src.is_file() and dst.is_file():
        return "skip" if src.read_bytes() == dst.read_bytes() else "update"
    if src.is_dir() and dst.is_dir():
        return "skip" if trees_identical(src, dst) else "update"
    return "update"


def plan_marker_action(path: Path, body: str, *, create: bool) -> str:
    if not path.exists():
        return "create" if create else "skip"
    existing = path.read_text(encoding="utf-8")
    if CONNECT_MARKER_BEGIN in existing and CONNECT_MARKER_END in existing:
        pre = existing.split(CONNECT_MARKER_BEGIN, 1)[0]
        post = existing.split(CONNECT_MARKER_END, 1)[1]
        new_text = pre.rstrip() + "\n\n" + body.rstrip() + "\n" + post.lstrip("\n")
        if not new_text.endswith("\n"):
            new_text += "\n"
        return "skip" if new_text == existing else "update"
    return "merge"


def plan_ensure_json(path: Path) -> str:
    return "create" if not path.exists() else "skip"


def plan_quality_action(
    root: Path,
    context_rel: str,
    coverage_pct: float | int | None = None,
) -> str:
    """quality.json: create / update (warn→hard or --coverage) / skip."""
    path = quality_path(root, context_rel)
    if not path.exists():
        return "create"
    data = load_quality(root, context_rel)
    for section_name in ("test_smells", "architecture"):
        section = data.get(section_name)
        if isinstance(section, dict) and str(section.get("mode") or "").lower() == "warn":
            return "update"
    if coverage_pct is not None:
        cov = data.get("coverage") or {}
        wanted = float(coverage_pct)
        if float(cov.get("lines", -1)) != wanted or float(cov.get("branches", -1)) != wanted:
            return "update"
    return "skip"


def plan_template_action(src: Path, dst: Path) -> str:
    if not src.exists():
        return "skip"
    if not dst.exists():
        return "create"
    existing = dst.read_text(encoding="utf-8")
    if QUALITY_MARKER not in existing:
        return "skip"
    body = src.read_text(encoding="utf-8")
    return "skip" if existing == body else "update"


def plan_hooks_path_action(root: Path) -> str:
    if not ((root / ".git").exists() or (root / ".git").is_file()):
        return "skip"
    proc = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    current = (proc.stdout or "").strip() if proc.returncode == 0 else ""
    wanted = ".githooks"
    if not current:
        return "create"
    norm = current.replace("\\", "/").rstrip("/")
    if norm in {wanted, str((root / wanted).resolve()).replace("\\", "/")}:
        return "skip"
    return "skip"


def plan_json_document_action(path: Path, desired: dict[str, Any]) -> str:
    text = json.dumps(desired, indent=2) + "\n"
    if not path.exists():
        return "create"
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        return "update"
    return "skip" if existing == text else "update"


def plans_include_refuse(planned: list[dict[str, Any]]) -> bool:
    return any(item.get("action") == "refuse" for item in planned)


def refuse_exit_code(result: dict[str, Any]) -> int:
    """Non-zero when dry-run/uninstall result carries action=refuse."""
    return 1 if result.get("refused") else 0
