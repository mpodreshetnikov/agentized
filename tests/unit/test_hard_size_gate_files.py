"""Dogfood/template contracts: process size is a hard gate (no soft `|| true`).

Kept separate from test_process_control.py so mutmut's module-scoped test
selection does not require .githooks / .github / templates inside mutants/.
"""

from __future__ import annotations

from pathlib import Path


def test_size_gate_hard_in_hooks_and_ci():
    """Size must hard-fail: every process-size CLI line is exact, no `|| true`."""
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / ".githooks" / "pre-push",
        root / ".github" / "workflows" / "ci.yml",
        root / "templates" / "quality" / "pre-push",
        root / "templates" / "quality" / "ci.yml",
    ]
    expected = '"${CLI[@]}" process size'
    found: dict[str, list[str]] = {}
    for path in paths:
        lines = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if "process size" in ln and not ln.strip().startswith("#") and "echo " not in ln
        ]
        found[str(path.relative_to(root))] = lines
    assert found == {
        ".githooks/pre-push": [expected],
        ".github/workflows/ci.yml": [expected],
        "templates/quality/pre-push": [expected],
        "templates/quality/ci.yml": [expected],
    }
