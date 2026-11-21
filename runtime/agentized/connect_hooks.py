"""AGE-52: rebind connect install_*/connect to merge-safe hooks wiring."""

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
from .paths import DEFAULT_CONTEXT

_ORIG_CONNECT = connect_mod.connect
_ORIG_CURSOR = connect_mod.install_cursor
_ORIG_CLAUDE = connect_mod.install_claude
_ORIG_CODEX = connect_mod.install_codex


def _merge_after_orig(
    root: Path,
    harness: str,
    context_rel: str,
    *,
    dry_run: bool,
    saved: bytes | None,
    path: Path,
) -> dict[str, Any]:
    if dry_run:
        return apply_harness_hook_merge(root, harness, context_rel=context_rel, dry_run=True)
    if saved is not None:
        path.write_bytes(saved)
    return apply_harness_hook_merge(root, harness, context_rel=context_rel, dry_run=False)


def install_cursor(
    root: Path,
    context_rel: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict:
    path = root / ".cursor" / "hooks.json"
    saved = path.read_bytes() if path.exists() else None
    if dry_run:
        out: dict[str, Any] = {
            "skills_copied": [],
            "skills_managed": {},
            "skipped_user": [],
            "hooks_json": str(path),
            "plugin_path": None,
            "local_plugin_hint": "cursor-agent --plugin-dir packages/agentized-cursor",
        }
    else:
        out = _ORIG_CURSOR(root, context_rel, force=force, manifest=manifest)
    out["hooks_merge"] = _merge_after_orig(
        root, "cursor", context_rel, dry_run=dry_run, saved=saved, path=path
    )
    return out


def install_claude(
    root: Path,
    context_rel: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict:
    path = root / ".claude" / "settings.json"
    saved = path.read_bytes() if path.exists() else None
    if dry_run:
        out: dict[str, Any] = {
            "skills_copied": [],
            "skills_managed": {},
            "skipped_user": [],
            "settings": str(path),
            "plugin_hint": "claude --plugin-dir packages/agentized-claude",
        }
    else:
        out = _ORIG_CLAUDE(root, context_rel, force=force, manifest=manifest)
    out["hooks_merge"] = _merge_after_orig(
        root, "claude", context_rel, dry_run=dry_run, saved=saved, path=path
    )
    return out


def install_codex(
    root: Path,
    context_rel: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict:
    path = root / ".codex" / "hooks.json"
    saved = path.read_bytes() if path.exists() else None
    market = root / ".agents" / "plugins" / "marketplace.json"
    market_saved = market.read_bytes() if market.exists() else None
    if dry_run:
        out: dict[str, Any] = {
            "skills_copied": [],
            "skills_managed": {},
            "skipped_user": [],
            "hooks_json": str(path),
            "marketplace": str(market),
            "plugin_hint": "codex plugin marketplace add .",
            "gap": "Codex: project .codex/hooks.json (no stable --plugin-dir).",
        }
    else:
        out = _ORIG_CODEX(root, context_rel, force=force, manifest=manifest)
    out["hooks_merge"] = _merge_after_orig(
        root, "codex", context_rel, dry_run=dry_run, saved=saved, path=path
    )
    if dry_run:
        out["marketplace_merge"] = apply_marketplace_merge(root, dry_run=True)
    else:
        if market_saved is not None:
            market.parent.mkdir(parents=True, exist_ok=True)
            market.write_bytes(market_saved)
        out["marketplace_merge"] = apply_marketplace_merge(root, dry_run=False)
    return out


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
    connect_mod.install_cursor = install_cursor
    connect_mod.install_claude = install_claude
    connect_mod.install_codex = install_codex
    connect_mod.connect = connect


wire_safe_connect()
