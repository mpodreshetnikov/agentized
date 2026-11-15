"""Mechanical contract: acceptance-artifacts skill encodes the human 5-block standard."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "packages" / "shared" / "skills" / "acceptance-artifacts" / "SKILL.md"
COMM = ROOT / "packages" / "shared" / "skills" / "communication-autonomy" / "SKILL.md"
CONNECT = ROOT / "runtime" / "agentized" / "connect.py"

# Required human-facing block titles (order matters for the default short report).
FIVE_BLOCKS = (
    "What the task was",
    "What was done",
    "Product result",
    "Side effects, consequences, risks",
    "Acceptance test plan",
)

# Phrases that must appear so connected projects inherit the bans / exceptions.
REQUIRED_PHRASES = (
    "Forbidden in the human report",
    "does not apply to human reports",
    "before/after",
    "mermaid",
    "Bare task/PR numbers",
    "Telegraph compression",
    "Process recap",
    "Self-check",
)


def test_acceptance_skill_has_five_human_blocks_and_bans():
    text = SKILL.read_text(encoding="utf-8")
    assert "`short` (default)" in text
    assert "`technical`" in text or "technical" in text
    positions = [text.index(block) for block in FIVE_BLOCKS]
    assert positions == sorted(positions), "5 human blocks must appear in order"
    for phrase in REQUIRED_PHRASES:
        assert phrase in text, f"missing ban/visual phrase: {phrase}"


def test_caveman_exempts_human_reports_in_related_pins():
    skill = SKILL.read_text(encoding="utf-8")
    comm = COMM.read_text(encoding="utf-8")
    connect = CONNECT.read_text(encoding="utf-8")
    assert "human-facing acceptance report" in skill
    assert "human-facing acceptance reports" in comm
    assert "human-facing acceptance reports" in connect
    # Caveman still exists for working agents — not removed wholesale.
    assert "ultracave" in skill and "ultracave" in comm


def test_context_and_plugin_mirrors_match_shared():
    shared = SKILL.read_text(encoding="utf-8")
    mirrors = [
        ROOT / "context" / "skills" / "acceptance-artifacts" / "SKILL.md",
        ROOT / "packages" / "agentized-cursor" / "skills" / "acceptance-artifacts" / "SKILL.md",
        ROOT / "packages" / "agentized-claude" / "skills" / "acceptance-artifacts" / "SKILL.md",
        ROOT / "packages" / "agentized-codex" / "skills" / "acceptance-artifacts" / "SKILL.md",
    ]
    for path in mirrors:
        assert path.read_text(encoding="utf-8") == shared, path
