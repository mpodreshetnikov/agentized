"""Locate Agentized runtime for hooks in dogfood or external repos.

Safe to import from hook scripts before `agentized` is on sys.path.
Never raises — returns workspace Path even when runtime is unavailable.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def ensure_runtime_on_path(here: Path | None = None) -> Path:
    """Insert runtime/ onto sys.path when found; return workspace root guess."""
    here = (here or Path(__file__)).resolve()
    workspace = Path.cwd()
    candidates: list[Path] = []
    env = os.environ.get("AGENTIZED_ROOT")
    if env:
        candidates.append(Path(env).expanduser().resolve())
    which = shutil.which("agentized")
    if which:
        # ./bin/agentized or PATH entry → repo root is parent of bin/
        candidates.append(Path(which).resolve().parent.parent)
    for parent in [here.parent, *here.parents]:
        candidates.append(parent)
        if (parent / "AGENTS.md").exists():
            workspace = parent
    for root in candidates:
        runtime = root / "runtime"
        if (runtime / "agentized").is_dir():
            path = str(runtime)
            if path not in sys.path:
                sys.path.insert(0, path)
            # Prefer cwd / AGENTS.md tree as workspace; runtime may be installed elsewhere.
            if (workspace / "AGENTS.md").exists() or (workspace / "context").is_dir():
                return workspace
            return root
    return workspace
