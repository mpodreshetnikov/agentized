"""Text helper tests for AGE-28 (outside mutation gate)."""
from __future__ import annotations

from agentized.spec_approval_text import parse_approvers, parse_tags, section_body


def test_section_tags_approvers():
    text = "# t\n\n## Spec\n\nBody\nline2\n\n## Approval\n\napproved-by: A\n"
    assert section_body(text, "## Spec") == "Body\nline2"
    assert section_body(text, "## Missing") is None
    assert parse_tags("A, b  C") == {"a", "b", "c"}
    assert parse_approvers("approved-by: X\nApproved-By: Y\napproved-by:\n") == ["X", "Y"]
