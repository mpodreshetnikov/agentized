"""Managed-file manifest: content-hash pin for connect auto-update.

Manifest path: ``{context}/.agentized/managed.json`` (committed with Context).

Rules on connect / pin (per relative path):
- no file → write desired content, record sha256
- file hash == manifest hash (untouched since last Agentized write) → overwrite
  with new desired content, update hash (harness auto-update)
- file hash != manifest hash → user edit → skip, status ``skipped_user``
- no manifest entry but file exists (pre-manifest / legacy) → **bootstrap**:
  record hash of *current* bytes, do not overwrite this run (``bootstrapped``).
  Later connects then follow the untouched→update / edited→skip rules.

``force=True`` (e.g. ``agentized review set``) always overwrites and records.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MANAGED_DIRNAME = ".agentized"
MANAGED_FILENAME = "managed.json"
MANAGED_VERSION = 1


def managed_path(root: Path, context_rel: str) -> Path:
    return root / context_rel / MANAGED_DIRNAME / MANAGED_FILENAME


def content_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_managed(root: Path, context_rel: str) -> dict[str, Any]:
    path = managed_path(root, context_rel)
    if not path.exists():
        return {"version": MANAGED_VERSION, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": MANAGED_VERSION, "files": {}}
    if not isinstance(data, dict):
        return {"version": MANAGED_VERSION, "files": {}}
    files = data.get("files")
    if not isinstance(files, dict):
        files = {}
    clean: dict[str, str] = {}
    for key, val in files.items():
        if isinstance(val, str):
            clean[str(key)] = val
        elif isinstance(val, dict) and isinstance(val.get("sha256"), str):
            clean[str(key)] = val["sha256"]
    return {"version": int(data.get("version") or MANAGED_VERSION), "files": clean}


def save_managed(root: Path, context_rel: str, data: dict[str, Any]) -> Path:
    path = managed_path(root, context_rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": int(data.get("version") or MANAGED_VERSION),
        "files": dict(sorted((data.get("files") or {}).items())),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def rel_key(root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def managed_write_bytes(
    root: Path,
    context_rel: str,
    path: Path,
    data: bytes,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
) -> str:
    """Write managed bytes. Returns status; updates ``manifest`` in place when given.

    When ``manifest`` is provided the caller must ``save_managed`` once at the end.
    """
    man = manifest if manifest is not None else load_managed(root, context_rel)
    files: dict[str, str] = man.setdefault("files", {})
    key = rel_key(root, path)
    desired_hash = content_sha256(data)
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)

    def _persist() -> None:
        if manifest is None:
            save_managed(root, context_rel, man)

    if force:
        path.write_bytes(data)
        files[key] = desired_hash
        _persist()
        return "updated" if existed else "created"

    if not existed:
        path.write_bytes(data)
        files[key] = desired_hash
        _persist()
        return "created"

    existing = path.read_bytes()
    existing_hash = content_sha256(existing)
    recorded = files.get(key)

    if recorded is None:
        # Legacy / pre-manifest: adopt current bytes, do not clobber this run.
        files[key] = existing_hash
        _persist()
        if existing_hash == desired_hash:
            return "unchanged"
        return "bootstrapped"

    if existing_hash != recorded:
        return "skipped_user"

    if existing_hash == desired_hash:
        files[key] = desired_hash
        _persist()
        return "unchanged"

    path.write_bytes(data)
    files[key] = desired_hash
    _persist()
    return "updated"


def managed_write_text(
    root: Path,
    context_rel: str,
    path: Path,
    body: str,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
) -> str:
    return managed_write_bytes(
        root,
        context_rel,
        path,
        body.encode("utf-8"),
        force=force,
        manifest=manifest,
    )


def managed_copy_file(
    root: Path,
    context_rel: str,
    src: Path,
    dst: Path,
    *,
    force: bool = False,
    manifest: dict[str, Any] | None = None,
) -> str:
    return managed_write_bytes(
        root,
        context_rel,
        dst,
        src.read_bytes(),
        force=force,
        manifest=manifest,
    )
