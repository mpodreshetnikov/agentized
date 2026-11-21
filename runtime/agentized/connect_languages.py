"""Connect-time language refuse (full-cover globs; connect.py untouched).

Dogfood-only excludes (packages/**, templates/**) stay in this repo's
context/quality.json — never written by connect (Lead / Self-Review).
"""

from __future__ import annotations

from pathlib import Path


class ConnectRefused(Exception):
    """Fail-closed connect refusal (language coverage, etc.)."""

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


def refuse_incomplete_languages(root: Path, context_rel: str) -> None:
    from agentized.languages import check_language_coverage
    from agentized.quality import load_quality, quality_path

    qpath = quality_path(root, context_rel)
    lang_check = check_language_coverage(
        root,
        context=context_rel,
        cfg=load_quality(root, context_rel),
        require_gates=qpath.is_file(),
    )
    # Missing/false ok → refuse (fail-closed; only explicit True passes).
    if lang_check.get("ok") is not True:
        raise ConnectRefused(lang_check["message"], details=lang_check)
