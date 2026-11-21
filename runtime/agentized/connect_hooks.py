"""AGE-52 safe harness install + connect dry-run (merge I/O; no connect.py edit)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__
from . import connect as connect_mod
from .hooks_install import (
    apply_harness_hook_merge,
    apply_marketplace_merge,
    summarize_hooks_refused,
)
from .managed import load_managed, save_managed
from .paths import DEFAULT_CONTEXT

_ORIG_CONNECT = connect_mod.connect


def install_cursor(
    root: Path,
    context_rel: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict:
    """Official project surfaces: .cursor/skills + merged .cursor/hooks.json."""
    skills_src = root / context_rel / "skills"
    hooks_dir = root / ".cursor" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    cursor_skills = root / ".cursor" / "skills"
    man = manifest if manifest is not None else load_managed(root, context_rel)
    skills_result = connect_mod._managed_copy_tree(
        root, context_rel, skills_src, cursor_skills, force=force, manifest=man
    )
    if manifest is None:
        save_managed(root, context_rel, man)
    local_note = []
    refreshed = connect_mod._refresh_local_plugin(root, "agentized-cursor", skills_src)
    if refreshed:
        local_note.append(refreshed)
    connect_mod._pin_hook_scripts(root, context_rel, hooks_dir)
    hooks_path = root / ".cursor" / "hooks.json"
    hooks_merge = apply_harness_hook_merge(root, "cursor", context_rel=context_rel, dry_run=dry_run)
    written = (
        skills_result.get("created", [])
        + skills_result.get("updated", [])
        + skills_result.get("unchanged", [])
        + skills_result.get("bootstrapped", [])
    )
    return {
        "skills_copied": written,
        "skills_managed": skills_result,
        "skipped_user": list(skills_result.get("skipped_user", [])),
        "hooks_json": str(hooks_path),
        "hooks_merge": hooks_merge,
        "plugin_path": local_note[0] if local_note else None,
        "local_plugin_hint": (
            "cp -R packages/agentized-cursor ~/.cursor/plugins/local/agentized "
            "или cursor-agent --plugin-dir packages/agentized-cursor"
        ),
    }


def install_claude(
    root: Path,
    context_rel: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict:
    """Official project surfaces: .claude/skills + merged .claude/settings.json."""
    skills_src = root / context_rel / "skills"
    claude_dir = root / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    man = manifest if manifest is not None else load_managed(root, context_rel)
    skills_result = connect_mod._managed_copy_tree(
        root, context_rel, skills_src, claude_dir / "skills", force=force, manifest=man
    )
    if manifest is None:
        save_managed(root, context_rel, man)
    connect_mod._pin_hook_scripts(root, context_rel, hooks_dir)
    connect_mod._refresh_local_plugin(root, "agentized-claude", skills_src)
    settings_path = claude_dir / "settings.json"
    hooks_merge = apply_harness_hook_merge(root, "claude", context_rel=context_rel, dry_run=dry_run)
    written = (
        skills_result.get("created", [])
        + skills_result.get("updated", [])
        + skills_result.get("unchanged", [])
        + skills_result.get("bootstrapped", [])
    )
    return {
        "skills_copied": written,
        "skills_managed": skills_result,
        "skipped_user": list(skills_result.get("skipped_user", [])),
        "settings": str(settings_path),
        "hooks_merge": hooks_merge,
        "plugin_hint": "claude --plugin-dir packages/agentized-claude",
    }


def install_codex(
    root: Path,
    context_rel: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict:
    """Official project surfaces: .agents/skills + merged .codex/hooks.json."""
    skills_src = root / context_rel / "skills"
    agents_skills = root / ".agents" / "skills"
    man = manifest if manifest is not None else load_managed(root, context_rel)
    skills_result = connect_mod._managed_copy_tree(
        root, context_rel, skills_src, agents_skills, force=force, manifest=man
    )
    if manifest is None:
        save_managed(root, context_rel, man)
    copied = (
        skills_result.get("created", [])
        + skills_result.get("updated", [])
        + skills_result.get("unchanged", [])
        + skills_result.get("bootstrapped", [])
    )
    codex_hooks = root / ".codex" / "hooks"
    codex_hooks.mkdir(parents=True, exist_ok=True)
    connect_mod._pin_hook_scripts(root, context_rel, codex_hooks)
    connect_mod._refresh_local_plugin(root, "agentized-codex", skills_src)
    hooks_path = root / ".codex" / "hooks.json"
    hooks_merge = apply_harness_hook_merge(root, "codex", context_rel=context_rel, dry_run=dry_run)
    marketplace_merge = apply_marketplace_merge(root, dry_run=dry_run)
    market_path = root / ".agents" / "plugins" / "marketplace.json"
    return {
        "skills_copied": copied,
        "skills_managed": skills_result,
        "skipped_user": list(skills_result.get("skipped_user", [])),
        "hooks_json": str(hooks_path),
        "hooks_merge": hooks_merge,
        "marketplace": str(market_path),
        "marketplace_merge": marketplace_merge,
        "plugin_hint": (
            "codex plugin marketplace add . && "
            "codex plugin install agentized@agentized-local  "
            "(или пользуйтесь project .codex/hooks.json + .agents/skills после connect)"
        ),
        "gap": (
            "У Codex нет стабильного --plugin-dir; hooks плагина могут требовать trust. "
            "Connect пишет официальные project hooks в .codex/hooks.json."
        ),
    }


def connect(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    harnesses: list[str] | None = None,
    coverage_pct: float | int | None = None,
    dry_run: bool = False,
) -> dict:
    harnesses = harnesses or ["cursor", "claude", "codex"]
    if dry_run:
        results: dict[str, Any] = {
            "skeleton": {"created": False, "path": context_rel, "files": []},
            "harnesses": {},
            "dry_run": True,
            "skipped_user": [],
            "state": {
                "version": __version__,
                "context": context_rel,
                "harnesses": harnesses,
                "agents_md_updated": False,
                "claude_md_updated": False,
                "coverage_pct": coverage_pct,
            },
            "idempotent": True,
        }
        if "cursor" in harnesses:
            results["harnesses"]["cursor"] = {
                "hooks_merge": apply_harness_hook_merge(
                    root, "cursor", context_rel=context_rel, dry_run=True
                ),
            }
        if "claude" in harnesses:
            results["harnesses"]["claude"] = {
                "hooks_merge": apply_harness_hook_merge(
                    root, "claude", context_rel=context_rel, dry_run=True
                ),
            }
        if "codex" in harnesses:
            results["harnesses"]["codex"] = {
                "hooks_merge": apply_harness_hook_merge(
                    root, "codex", context_rel=context_rel, dry_run=True
                ),
                "marketplace_merge": apply_marketplace_merge(root, dry_run=True),
            }
        ok, refused = summarize_hooks_refused(results["harnesses"])
        results["hooks_refused"] = refused
        results["ok"] = ok
        return results

    # install_* already rebound → original connect body merges instead of overwrite.
    result = _ORIG_CONNECT(
        root,
        context_rel=context_rel,
        harnesses=harnesses,
        coverage_pct=coverage_pct,
    )
    ok, refused = summarize_hooks_refused(result.get("harnesses") or {})
    result["hooks_refused"] = refused
    result["ok"] = ok
    result["dry_run"] = False
    return result


def wire_safe_connect() -> None:
    """Rebind connect module entrypoints to merge-safe implementations."""
    connect_mod.install_cursor = install_cursor
    connect_mod.install_claude = install_claude
    connect_mod.install_codex = install_codex
    connect_mod.connect = connect


wire_safe_connect()
