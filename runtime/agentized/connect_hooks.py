"""AGE-52: rebind connect install_*/connect to merge-safe hooks wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__
from . import connect as connect_mod
from .hooks_install import (
    apply_harness_hook_merge,
    apply_marketplace_merge,
    install_claude,
    install_codex,
    install_cursor,
    summarize_hooks_refused,
)
from .paths import DEFAULT_CONTEXT

_ORIG_CONNECT = connect_mod.connect


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
    """Rebind connect module entrypoints to merge-safe implementations."""
    connect_mod.install_cursor = install_cursor
    connect_mod.install_claude = install_claude
    connect_mod.install_codex = install_codex
    connect_mod.connect = connect


wire_safe_connect()
