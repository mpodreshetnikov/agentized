"""Read-only connect dry-run planner (AGE-36).

Inventories every connect write as create|update|merge|skip|refuse without
touching the tree or git config. Accuracy rules from Lead #21 item 6:
- quality.json may update (warn→hard / --coverage), never a false skip
- include marketplace.json + local plugin refresh paths
- pin trees: skip when content identical to source
- honor --coverage in dry-run
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .connect import (
    AGENTS_BLOCK_TEMPLATE,
    CLAUDE_BLOCK_TEMPLATE,
    QUALITY_MARKER,
    _local_packages,
    _quality_templates_dir,
    _shared_hook_scripts,
    _shared_skills,
)
from .hooks_install import plan_harness_hooks
from .paths import CONNECT_MARKER_BEGIN, CONNECT_MARKER_END, DEFAULT_CONTEXT
from .quality import load_quality, quality_path

ALLOWED_ACTIONS = frozenset({"create", "update", "merge", "skip", "refuse"})

PLUGIN_BY_HARNESS = {
    "cursor": "agentized-cursor",
    "claude": "agentized-claude",
    "codex": "agentized-codex",
}


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digests(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    out: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
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


def plan_marker_action(path: Path, body: str, *, create: bool) -> str:
    if not path.exists():
        return "create" if create else "skip"
    existing = path.read_text(encoding="utf-8")
    if CONNECT_MARKER_BEGIN in existing and CONNECT_MARKER_END in existing:
        pre = existing.split(CONNECT_MARKER_BEGIN, 1)[0]
        post = existing.split(CONNECT_MARKER_END, 1)[1]
        new_text = pre.rstrip() + "\n\n" + body.rstrip() + "\n" + post.lstrip("\n")
        if not new_text.endswith("\n"):
            new_text += "\n"
        return "skip" if new_text == existing else "update"
    return "merge"


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
        if float(cov.get("lines", -1)) != wanted or float(cov.get("branches", -1)) != wanted:
            return "update"
    return "skip"


def plan_template_action(src: Path, dst: Path) -> str:
    if not src.exists():
        return "skip"
    if not dst.exists():
        return "create"
    existing = dst.read_text(encoding="utf-8")
    if QUALITY_MARKER not in existing:
        return "skip"
    body = src.read_text(encoding="utf-8")
    return "skip" if existing == body else "update"


def plan_hooks_path_action(root: Path) -> str:
    if not ((root / ".git").exists() or (root / ".git").is_file()):
        return "skip"
    proc = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    current = (proc.stdout or "").strip() if proc.returncode == 0 else ""
    wanted = ".githooks"
    if not current:
        return "create"
    norm = current.replace("\\", "/").rstrip("/")
    if norm in {wanted, str((root / wanted).resolve()).replace("\\", "/")}:
        return "skip"
    return "skip"


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


def plan_json_document_action(path: Path, desired: dict[str, Any]) -> str:
    text = json.dumps(desired, indent=2) + "\n"
    if not path.exists():
        return "create"
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        return "update"
    return "skip" if existing == text else "update"


def plans_include_refuse(planned: list[dict[str, Any]]) -> bool:
    return any(item.get("action") == "refuse" for item in planned)


def refuse_exit_code(result: dict[str, Any]) -> int:
    """Non-zero when dry-run/uninstall result carries action=refuse."""
    return 1 if result.get("refused") else 0


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

    # Marketplace + local plugin refresh (Lead #21 item 6).
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
