from __future__ import annotations

import json
from pathlib import Path

from agentized.connect import harness_reviewer_opts, pin_reviewer_agents
from agentized.quality import default_quality_config, save_quality


def _src_reviewer(root: Path) -> None:
    agents = root / "packages" / "shared" / "agents"
    agents.mkdir(parents=True)
    (agents / "reviewer.md").write_text(
        "---\nname: reviewer\nmodel: ignore\nreadonly: true\n---\n\nBody here.\n",
        encoding="utf-8",
    )
    (root / "context").mkdir(parents=True, exist_ok=True)


def test_harness_opts_prefer_per_harness(tmp_path: Path):
    cfg = {
        "model": "legacy-should-not-win",
        "harnesses": {
            "cursor": {"model": "grok-4.7[reasoning_effort=medium]", "effort": "medium"},
            "codex": {"model": "gpt-6-astra", "effort": "medium"},
        },
    }
    assert harness_reviewer_opts(cfg, "cursor")["model"].startswith("grok-4.7")
    assert harness_reviewer_opts(cfg, "codex")["model"] == "gpt-6-astra"
    # missing harness falls back to legacy
    assert harness_reviewer_opts(cfg, "claude")["model"] == "legacy-should-not-win"


def test_pin_reviewer_writes_toml_not_codex_md(tmp_path: Path):
    _src_reviewer(tmp_path)
    cfg = default_quality_config()
    save_quality(tmp_path, cfg, "context")
    # stale Codex markdown must be removed
    codex_agents = tmp_path / ".codex" / "agents"
    codex_agents.mkdir(parents=True)
    (codex_agents / "reviewer.md").write_text("stale\n", encoding="utf-8")

    result = pin_reviewer_agents(tmp_path, "context")
    assert (tmp_path / ".cursor" / "agents" / "reviewer.md").exists()
    assert (tmp_path / ".claude" / "agents" / "reviewer.md").exists()
    claude = (tmp_path / ".claude" / "agents" / "reviewer.md").read_text(encoding="utf-8")
    assert "claude-fable-5-2" in claude
    assert "disallowedTools:" in claude
    assert "Caveman" in claude
    assert (tmp_path / ".codex" / "agents" / "reviewer.toml").exists()
    assert not (tmp_path / ".codex" / "agents" / "reviewer.md").exists()
    toml = (tmp_path / ".codex" / "agents" / "reviewer.toml").read_text(encoding="utf-8")
    assert 'model = "gpt-6-astra"' in toml
    assert "model_reasoning_effort" in toml
    assert result["models"]["cursor"].startswith("grok-4.7")
