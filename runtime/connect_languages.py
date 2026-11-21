"""Connect-time language refuse + dogfood excludes (outside mutation include_globs).

Keep runtime/agentized/connect.py identical to main under full-cover globs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Dogfood-only excludes (Lead reject batch2 — not in DEFAULT_EXCLUDE_GLOBS).
MANAGED_LANG_EXCLUDES = ("packages/**", "templates/**")


class ConnectRefused(Exception):
    """Fail-closed connect refusal (language coverage, etc.)."""

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


def refuse_incomplete_languages(root: Path, context_rel: str) -> None:
    """AGE-24: refuse before connect writes. Gates only if quality.json exists."""
    from agentized.languages import check_language_coverage
    from agentized.quality import load_quality, quality_path

    qpath = quality_path(root, context_rel)
    lang_check = check_language_coverage(
        root,
        context=context_rel,
        cfg=load_quality(root, context_rel),
        require_gates=qpath.is_file(),
    )
    if not lang_check.get("ok", True):
        raise ConnectRefused(lang_check["message"], details=lang_check)


def merge_managed_language_excludes(root: Path, context_rel: str) -> dict[str, Any]:
    """Ensure packages/** + templates/** are in languages.exclude_globs after connect."""
    from agentized.quality import load_quality, save_quality

    data = load_quality(root, context_rel)
    lang = data.get("languages")
    if not isinstance(lang, dict):
        lang = {}
        data["languages"] = lang
    excludes = [str(x) for x in (lang.get("exclude_globs") or [])]
    dirty = False
    for pat in MANAGED_LANG_EXCLUDES:
        if pat not in excludes:
            excludes.append(pat)
            dirty = True
    if dirty:
        lang["exclude_globs"] = excludes
        if not lang.get("supported"):
            lang["supported"] = ["python", "javascript", "typescript"]
        save_quality(root, data, context_rel)
    return data
