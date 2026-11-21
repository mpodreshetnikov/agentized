"""Dogfood CI contract for process format-disables (kept out of mutmut selection)."""

from __future__ import annotations

from pathlib import Path


def test_ci_invokes_format_disables_hard():
    """format-disables must hard-fail in dogfood CI (exact CLI line, no || true)."""
    root = Path(__file__).resolve().parents[2]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lines = [
        ln.strip()
        for ln in ci.splitlines()
        if "format-disables" in ln and not ln.strip().startswith("#") and "echo " not in ln
    ]
    assert lines == ['"${CLI[@]}" process format-disables']
    soft = [ln for ln in ci.splitlines() if "format-disables" in ln and "|| true" in ln]
    assert soft == []
    assert "PROCESS_BASE:" in ci
