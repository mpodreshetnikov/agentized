"""Connect dry-run assembler (AGE-36) — outside mutation include_globs.

Wires pure helpers from connect_plan + hooks_install into a full inventory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .connect import (
    AGENTS_BLOCK_TEMPLATE,
    CLAUDE_BLOCK_TEMPLATE,
    _local_packages,
    _quality_templates_dir,
    _shared_hook_scripts,
    _shared_skills,
)
from .connect_plan import (
    plan_ensure_json,
    plan_pin_tree_action,
    plan_quality_action,
    plans_include_refuse,
)
from .connect_plan_io import (
    plan_hooks_path_action,
    plan_json_document_action,
    plan_marker_action,
    plan_template_action,
)

ALLOWED_ACTIONS = frozenset({"create", "update", "merge", "skip", "refuse"})
from .hooks_install import plan_harness_hooks
from .paths import CONNECT_MARKER_BEGIN, CONNECT_MARKER_END, DEFAULT_CONTEXT

PLUGIN_BY_HARNESS = {
    "cursor": "agentized-cursor",
    "claude": "agentized-claude",
    "codex": "agentized-codex",
}


def desired_codex_marketplace() -> dict[str, Any]:
    return {
        "name": "agentized-local",
        "plugins": [
            {
                "name": "agentized",
                "source": {"source": "local", "path": "./packages/agentized-codex"},
                "category": "Productivity",
            }
        ],
    }


def plan_connect_writes(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    harnesses: list[str] | None = None,
    coverage_pct: float | int | None = None,
) -> dict[str, Any]:
    """Inventory every connect write. Read-only: no filesystem or git-config mutations."""
    harnesses = harnesses or ["cursor", "claude", "codex"]
    agents_body = AGENTS_BLOCK_TEMPLATE.format(
        begin=CONNECT_MARKER_BEGIN,
        end=CONNECT_MARKER_END,
        context=context_rel,
    )
    claude_body = CLAUDE_BLOCK_TEMPLATE.format(
        begin=CONNECT_MARKER_BEGIN,
        end=CONNECT_MARKER_END,
        context=context_rel,
    )
    templates = _quality_templates_dir(root)
    skills_src = _shared_skills(root)
    hooks_src = _shared_hook_scripts(root)
    ctx_skills = root / context_rel / "skills"
    planned: list[dict[str, Any]] = []

    nav = root / context_rel / "NAV.md"
    planned.append(
        {
            "path": f"{context_rel}/NAV.md",
            "action": "create" if not nav.exists() else "skip",
            "kind": "context-skeleton",
        }
    )
    for rel in (f"{context_rel}/tasks/INDEX.md", f"{context_rel}/leases/INDEX.md"):
        planned.append(
            {
                "path": rel,
                "action": "create" if not (root / rel).exists() else "skip",
                "kind": "context-skeleton",
            }
        )

    planned.append(
        {
            "path": "AGENTS.md",
            "action": plan_marker_action(root / "AGENTS.md", agents_body, create=True),
            "kind": "marker-block",
        }
    )
    planned.append(
        {
            "path": "CLAUDE.md",
            "action": plan_marker_action(root / "CLAUDE.md", claude_body, create=False),
            "kind": "marker-block",
        }
    )

    planned.append(
        {
            "path": f"{context_rel}/skills/",
            "action": plan_pin_tree_action(ctx_skills, skills_src),
            "kind": "pin-skills",
        }
    )
    planned.append(
        {
            "path": f"{context_rel}/hooks/scripts/",
            "action": plan_pin_tree_action(root / context_rel / "hooks" / "scripts", hooks_src),
            "kind": "pin-hook-scripts",
        }
    )
    planned.append(
        {
            "path": f"{context_rel}/agents/reviewer.md",
            "action": plan_pin_tree_action(root / context_rel / "agents" / "reviewer.md"),
            "kind": "pin-reviewer",
        }
    )

    planned.append(
        {
            "path": f"{context_rel}/quality.json",
            "action": plan_quality_action(root, context_rel, coverage_pct=coverage_pct),
            "kind": "ensure-quality-config",
        }
    )
    for rel, kind in (
        (f"{context_rel}/env-check.json", "ensure-env-check-config"),
        (f"{context_rel}/process-control.json", "ensure-process-control-config"),
        (f"{context_rel}/reporting.json", "ensure-reporting-config"),
    ):
        planned.append(
            {
                "path": rel,
                "action": plan_ensure_json(root / rel),
                "kind": kind,
            }
        )

    planned.append(
        {
            "path": ".githooks/pre-push",
            "action": plan_template_action(templates / "pre-push", root / ".githooks" / "pre-push"),
            "kind": "quality-template",
        }
    )
    planned.append(
        {
            "path": ".github/workflows/ci.yml",
            "action": plan_template_action(
                templates / "ci.yml", root / ".github" / "workflows" / "ci.yml"
            ),
            "kind": "quality-template",
        }
    )
    planned.append(
        {
            "path": "core.hooksPath",
            "action": plan_hooks_path_action(root),
            "kind": "git-config",
            "value": ".githooks",
        }
    )
    planned.append(
        {
            "path": f"{context_rel}/.agentized/managed.json",
            "action": (
                "update"
                if (root / context_rel / ".agentized" / "managed.json").exists()
                else "create"
            ),
            "kind": "managed-manifest",
        }
    )
    planned.append(
        {
            "path": ".agentized/connect.json",
            "action": "update" if (root / ".agentized" / "connect.json").exists() else "create",
            "kind": "connect-state",
        }
    )

    harness_dirs = {
        "cursor": (
            (".cursor/skills/", ctx_skills),
            (".cursor/hooks/", root / context_rel / "hooks" / "scripts"),
            (".cursor/agents/", None),
        ),
        "claude": (
            (".claude/skills/", ctx_skills),
            (".claude/hooks/", root / context_rel / "hooks" / "scripts"),
            (".claude/agents/", None),
        ),
        "codex": (
            (".agents/skills/", ctx_skills),
            (".codex/hooks/", root / context_rel / "hooks" / "scripts"),
            (".codex/agents/", None),
        ),
    }
    for h in harnesses:
        for rel, src in harness_dirs.get(h, ()):
            planned.append(
                {
                    "path": rel,
                    "action": plan_pin_tree_action(root / rel.rstrip("/"), src),
                    "kind": "harness-pin",
                    "harness": h,
                }
            )

    if "codex" in harnesses:
        market_path = root / ".agents" / "plugins" / "marketplace.json"
        planned.append(
            {
                "path": ".agents/plugins/marketplace.json",
                "action": plan_json_document_action(market_path, desired_codex_marketplace()),
                "kind": "marketplace",
                "harness": "codex",
            }
        )

    local = _local_packages(root)
    if local is not None:
        for h in harnesses:
            name = PLUGIN_BY_HARNESS.get(h)
            if not name:
                continue
            plugin_src = local / name
            if not plugin_src.exists():
                continue
            planned.append(
                {
                    "path": f"packages/{name}/skills/",
                    "action": plan_pin_tree_action(plugin_src / "skills", skills_src),
                    "kind": "plugin-refresh",
                    "harness": h,
                }
            )
            planned.append(
                {
                    "path": f"packages/{name}/scripts/",
                    "action": plan_pin_tree_action(plugin_src / "scripts", hooks_src),
                    "kind": "plugin-refresh",
                    "harness": h,
                }
            )

    hook_plans = plan_harness_hooks(root, harnesses, context_rel=context_rel)
    for plan in hook_plans:
        planned.append(
            {
                "path": plan.get("path"),
                "action": plan.get("action"),
                "kind": "hooks-merge",
                "harness": plan.get("harness"),
                "changed": plan.get("changed"),
                **({"error": plan["error"]} if plan.get("error") else {}),
            }
        )

    bad = [p for p in planned if p.get("action") not in ALLOWED_ACTIONS]
    if bad:
        raise ValueError(f"dry-run actions must be create|update|merge|skip|refuse, got {bad}")

    refused = plans_include_refuse(planned) or plans_include_refuse(hook_plans)
    return {
        "dry_run": True,
        "scope": "all-connect-writes",
        "context": context_rel,
        "harnesses": harnesses,
        "coverage_pct": coverage_pct,
        "hook_plans": hook_plans,
        "planned_writes": planned,
        "refused": refused,
    }
