"""Harness hook install I/O + apply (AGE-52 / #21B)."""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any
from . import connect as connect_mod
from .hooks_merge import (
    HooksShapeError,
    collect_owned_commands,
    merge_claude_settings,
    merge_codex_hooks,
    merge_cursor_hooks,
    merge_marketplace_plugins,
    plan_json_change,
)

HOOKS_OWNED_FILENAME = "hooks_owned.json"
JSON_TEXT_ENCODING = "utf-8"
JSON_INDENT = 2
ENSURE_ASCII = False
HARNESS_HOOK_REL = {
    "cursor": (".cursor", "hooks.json"),
    "claude": (".claude", "settings.json"),
    "codex": (".codex", "hooks.json"),
}


def _merge_table(root: Path):
    return {
        "cursor": (lambda: desired_cursor_hooks(root), merge_cursor_hooks),
        "claude": (lambda: desired_claude_hooks(root), merge_claude_settings),
        "codex": (lambda: desired_codex_document(root), merge_codex_hooks),
    }


class HooksJsonError(ValueError):
    """Broken or non-object JSON; refuse writes (bytes unchanged)."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"invalid harness JSON at {path}: {reason}")


def harness_hook_path(root: Path, harness: str) -> Path:
    return root.joinpath(*HARNESS_HOOK_REL[harness])


def _json_payload(data: dict) -> bytes:
    opts = {"ensure_ascii": ENSURE_ASCII, "indent": JSON_INDENT}
    if opts["ensure_ascii"] is not False:
        raise RuntimeError("ENSURE_ASCII must be False")
    return bytes(json.dumps(data, **opts) + "\n", JSON_TEXT_ENCODING)


def _decode_json_bytes(data: bytes) -> str:
    return str(data, JSON_TEXT_ENCODING)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def read_json_object(path: Path) -> dict:
    """Missing → {}. Broken / non-object → HooksJsonError."""
    if not path.exists():
        return {}
    try:
        raw = _decode_json_bytes(path.read_bytes())
    except OSError as exc:
        raise HooksJsonError(path, f"unreadable ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise HooksJsonError(path, f"not utf-8 ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HooksJsonError(path, f"broken JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise HooksJsonError(path, f"top-level must be object, got {type(data).__name__}")
    return data


def write_json(path: Path, data: dict) -> bool:
    """Atomic write if content would change. Parent dirs must already exist."""
    payload = _json_payload(data)
    if path.exists() and path.read_bytes() == payload:
        return False
    _atomic_write_bytes(path, payload)
    return True


def hooks_owned_path(root: Path, context_rel: str) -> Path:
    return root / context_rel / ".agentized" / HOOKS_OWNED_FILENAME


def load_hooks_owned(root: Path, context_rel: str) -> dict[str, list[str]]:
    """Load ownership manifest. Missing → {}. Bad shape/UTF-8 → HooksJsonError."""
    path = hooks_owned_path(root, context_rel)
    if not path.exists():
        return {}
    try:
        raw = _decode_json_bytes(path.read_bytes())
    except OSError as exc:
        raise HooksJsonError(path, f"unreadable ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise HooksJsonError(path, f"not utf-8 ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HooksJsonError(path, f"broken JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise HooksJsonError(path, f"top-level must be object, got {type(data).__name__}")
    out: dict[str, list[str]] = {}
    for harness, cmds in data.items():
        if not isinstance(cmds, list) or not all(isinstance(c, str) for c in cmds):
            raise HooksJsonError(path, f"values must be list[str] (bad key {harness!r})")
        out[str(harness)] = list(cmds)
    return out


def save_hooks_owned(root: Path, owned: dict[str, list[str]], context_rel: str) -> Path:
    path = hooks_owned_path(root, context_rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: list(v) for k, v in sorted(owned.items()) if v}
    _atomic_write_bytes(path, _json_payload(clean))
    return path


def _prev_owned(root: Path, harness: str, context_rel: str) -> frozenset[str]:
    return frozenset(load_hooks_owned(root, context_rel).get(harness) or [])


def _record_owned(root: Path, harness: str, after_doc: dict, *, context_rel: str) -> None:
    all_owned = load_hooks_owned(root, context_rel)
    cmds = collect_owned_commands(after_doc, harness=harness)
    unique: list[str] = []
    seen: set[str] = set()
    for c in cmds:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    all_owned[harness] = unique
    save_hooks_owned(root, all_owned, context_rel)


def _desired_bundle_path(root: Path | None = None) -> Path:
    """Repo packages/shared/hooks if present, else Agentized install (like quality templates)."""
    rel = Path("packages") / "shared" / "hooks" / "harness_desired.json"
    if root is not None:
        local = root / rel
        if local.is_file():
            return local
    bundled = Path(__file__).resolve().parents[2] / rel
    if bundled.is_file():
        return bundled
    raise HooksJsonError(
        (root / rel) if root is not None else bundled,
        "harness_desired.json missing (local and installed)",
    )


def _load_desired_bundle(root: Path | None = None) -> dict[str, Any]:
    path = _desired_bundle_path(root)
    data = json.loads(path.read_bytes())
    if not isinstance(data, dict):
        raise ValueError("harness_desired.json must be an object")
    return data


def _require_desired_section(key: str, root: Path | None = None) -> dict:
    bundle = _load_desired_bundle(root)
    if key not in bundle:
        raise KeyError(f"harness_desired.json missing section: {key}")
    section = bundle[key]
    if not isinstance(section, dict):
        raise ValueError(f"harness_desired.json section {key!r} must be an object")
    return dict(section)


def desired_cursor_hooks(root: Path | None = None) -> dict[str, list]:
    return _require_desired_section("cursor_hooks", root)


def desired_claude_hooks(root: Path | None = None) -> dict[str, list]:
    return _require_desired_section("claude_hooks", root)


def desired_codex_document(root: Path | None = None) -> dict:
    return _require_desired_section("codex", root)


def refuse_plan(path: Path, harness: str, exc: Exception) -> dict[str, Any]:
    reason = getattr(exc, "reason", None) or str(exc)
    return {
        "path": str(getattr(exc, "path", path)),
        "harness": harness,
        "action": "refuse",
        "changed": False,
        "wrote": False,
        "error": str(exc),
        "reason": reason,
    }


def summarize_hooks_refused(
    harnesses: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    refused: list[dict[str, Any]] = []
    for name, h in harnesses.items():
        merge = h.get("hooks_merge") if isinstance(h, dict) else None
        if isinstance(merge, dict) and merge.get("action") == "refuse":
            refused.append(
                {
                    "harness": name,
                    "path": merge.get("path"),
                    "reason": merge.get("reason"),
                    "error": merge.get("error"),
                }
            )
        market = h.get("marketplace_merge") if isinstance(h, dict) else None
        if isinstance(market, dict) and market.get("action") == "refuse":
            refused.append(
                {
                    "harness": name,
                    "path": market.get("path"),
                    "reason": market.get("reason"),
                    "error": market.get("error"),
                }
            )
    return (not refused, refused)


def apply_harness_hook_merge(
    root: Path, harness: str, *, context_rel: str, dry_run: bool = False
) -> dict[str, Any]:
    """Merge+write one harness. Broken JSON/shape/owned → refuse (no write)."""
    table = _merge_table(root)
    if harness not in table:
        raise ValueError(f"unknown harness: {harness}")
    path = harness_hook_path(root, harness)
    try:
        before = read_json_object(path)
        prev = _prev_owned(root, harness, context_rel)
        desired_fn, merge_fn = table[harness]
        after = merge_fn(before, desired_fn(), previously_owned=prev)
    except (HooksJsonError, HooksShapeError) as exc:
        return refuse_plan(path, harness, exc)
    plan = plan_json_change(str(path), before, after)
    plan["harness"] = harness
    if dry_run:
        plan["wrote"] = False
        plan["dry_run"] = True
        return plan
    path.parent.mkdir(parents=True, exist_ok=True)
    wrote = write_json(path, after)
    _record_owned(root, harness, after, context_rel=context_rel)
    plan["wrote"] = wrote
    return plan


def apply_marketplace_merge(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Merge agentized plugin into .agents/plugins/marketplace.json by name."""
    market_path = root / ".agents" / "plugins" / "marketplace.json"
    ours = {
        "name": "agentized-local",
        "plugins": [
            {
                "name": "agentized",
                "source": {"source": "local", "path": "./packages/agentized-codex"},
                "category": "Productivity",
            }
        ],
    }
    try:
        before = read_json_object(market_path)
        after = merge_marketplace_plugins(before, ours)
    except (HooksJsonError, HooksShapeError) as exc:
        return refuse_plan(market_path, "codex", exc)
    plan = plan_json_change(str(market_path), before, after)
    plan["harness"] = "codex"
    plan["kind"] = "marketplace"
    if dry_run:
        plan["wrote"] = False
        plan["dry_run"] = True
        return plan
    market_path.parent.mkdir(parents=True, exist_ok=True)
    plan["wrote"] = write_json(market_path, after)
    return plan
