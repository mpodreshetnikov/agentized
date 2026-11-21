"""AGE-52: rebind connect install_*/connect to merge-safe hooks wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

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

_HOOK_REL = {
    "cursor": Path(".cursor") / "hooks.json",
    "claude": Path(".claude") / "settings.json",
    "codex": Path(".codex") / "hooks.json",
}


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
    return apply_harness_hook_merge(root, harness, context_rel=context_rel)


def _wrap_install(
    orig: Callable[..., dict],
    harness: str,
    root: Path,
    context_rel: str,
    *,
    force: bool,
    manifest: dict[str, Any] | None,
    dry_run: bool,
) -> dict:
    path = root / _HOOK_REL[harness]
    saved = path.read_bytes() if path.is_file() else None
    out: dict[str, Any]
    if dry_run:
        out = {}
    else:
        out = orig(root, context_rel, force=force, manifest=manifest)
    out["hooks_merge"] = _merge_after_orig(
        root, harness, context_rel, dry_run=dry_run, saved=saved, path=path
    )
    return out


def install_cursor(
    root: Path,
    context_rel: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict:
    return _wrap_install(
        _ORIG_CURSOR,
        "cursor",
        root,
        context_rel,
        force=force,
        manifest=manifest,
        dry_run=dry_run,
    )


def install_claude(
    root: Path,
    context_rel: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict:
    return _wrap_install(
        _ORIG_CLAUDE,
        "claude",
        root,
        context_rel,
        force=force,
        manifest=manifest,
        dry_run=dry_run,
    )


def install_codex(
    root: Path,
    context_rel: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict:
    path = root / _HOOK_REL["codex"]
    saved = path.read_bytes() if path.is_file() else None
    market = root / ".agents" / "plugins" / "marketplace.json"
    market_saved = market.read_bytes() if market.is_file() else None
    if dry_run:
        out: dict[str, Any] = {}
    else:
        out = _ORIG_CODEX(root, context_rel, force=force, manifest=manifest)
    out["hooks_merge"] = _merge_after_orig(
        root, "codex", context_rel, dry_run=dry_run, saved=saved, path=path
    )
    if dry_run:
        out["marketplace_merge"] = apply_marketplace_merge(root, dry_run=True)
        return out
    if market_saved is not None:
        market.parent.mkdir(parents=True, exist_ok=True)
        market.write_bytes(market_saved)
    out["marketplace_merge"] = apply_marketplace_merge(root)
    return out


def connect(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    harnesses: list[str] | None = None,
    coverage_pct: float | int | None = None,
    dry_run: bool = False,
) -> dict:
    chosen = list(harnesses) if harnesses is not None else ["cursor", "claude", "codex"]
    if dry_run:
        results: dict[str, Any] = {"harnesses": {}, "dry_run": True}
        for name in chosen:
            entry: dict[str, Any] = {
                "hooks_merge": apply_harness_hook_merge(
                    root, name, context_rel=context_rel, dry_run=True
                ),
            }
            if name == "codex":
                entry["marketplace_merge"] = apply_marketplace_merge(root, dry_run=True)
            results["harnesses"][name] = entry
        ok, refused = summarize_hooks_refused(results["harnesses"])
        results["hooks_refused"] = refused
        results["ok"] = ok
        return results

    result = _ORIG_CONNECT(
        root,
        context_rel=context_rel,
        harnesses=chosen,
        coverage_pct=coverage_pct,
    )
    harness_map = result.get("harnesses")
    if not isinstance(harness_map, dict):
        harness_map = {}
    ok, refused = summarize_hooks_refused(harness_map)
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
