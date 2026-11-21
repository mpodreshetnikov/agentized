"""Dogfood/template contracts for process format-disables (out of mutmut selection)."""

from __future__ import annotations

from pathlib import Path


def test_format_disables_hard_in_hooks_and_ci():
    """format-disables must hard-fail: exact CLI line, no || true."""
    root = Path(__file__).resolve().parents[2]
    expected = '"${CLI[@]}" process format-disables'
    paths = [
        root / ".githooks" / "pre-push",
        root / ".github" / "workflows" / "ci.yml",
        root / "templates" / "quality" / "pre-push",
        root / "templates" / "quality" / "ci.yml",
    ]
    found: dict[str, list[str]] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lines = [
            ln.strip()
            for ln in text.splitlines()
            if "format-disables" in ln and not ln.strip().startswith("#") and "echo " not in ln
        ]
        found[str(path.relative_to(root))] = lines
    assert found == {
        ".githooks/pre-push": [expected],
        ".github/workflows/ci.yml": [expected],
        "templates/quality/pre-push": [expected],
        "templates/quality/ci.yml": [expected],
    }
    for rel in (".github/workflows/ci.yml", "templates/quality/ci.yml"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "PROCESS_BASE:" in text
        soft = [ln for ln in text.splitlines() if "format-disables" in ln and "|| true" in ln]
        assert soft == []
