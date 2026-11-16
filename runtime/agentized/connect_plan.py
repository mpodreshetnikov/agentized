"""Pure connect dry-run decisions (AGE-36) — mutation include_globs.

Lead #21 item 6 accuracy:
- quality.json may update (warn→hard / --coverage), never a false skip
- pin trees: skip when content identical to source
- refuse exit for dry-run/uninstall
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .quality import load_quality, quality_path


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digests(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".pyc" or any(part == "__pycache__" for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
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
        lines = float(cov["lines"]) if "lines" in cov else -1.0
        branches = float(cov["branches"]) if "branches" in cov else -1.0
        if lines != wanted or branches != wanted:
            return "update"
    return "skip"


def plans_include_refuse(planned: list[dict[str, Any]]) -> bool:
    return any(item.get("action") == "refuse" for item in planned)


def refuse_exit_code(result: dict[str, Any]) -> int:
    """Non-zero when dry-run/uninstall result carries action=refuse."""
    return 1 if result.get("refused") else 0
