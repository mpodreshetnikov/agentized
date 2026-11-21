"""JS/TS architecture runners (dependency-cruiser / eslint-boundaries)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

_DEFAULT_DC = ".dependency-cruiser.cjs"
_DEFAULT_SRC = "src"
_NPX_MISSING = "npx-missing"

def _npx() -> str | None:
    return shutil.which("npx")

def _run(cmd: list[str], root: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()[:2000]
    return int(proc.returncode), out

def run_dependency_cruiser(root: Path, section: dict[str, Any]) -> tuple[int, str]:
    config_name = str(section["js_config"]) if "js_config" in section else _DEFAULT_DC
    config = root / config_name
    source = str(section["js_source"]) if "js_source" in section else _DEFAULT_SRC
    if not config.is_file():
        return 1, f"missing:{config_name}"
    npx = _npx()
    if npx is None:
        return 1, _NPX_MISSING
    return _run(
        [npx, "--yes", "dependency-cruiser", "--config", str(config), source], root
    )

def run_eslint_boundaries(root: Path, section: dict[str, Any]) -> tuple[int, str]:
    cmd = list(section.get("eslint_boundaries_command") or [])
    if not cmd:
        npx = _npx()
        if npx is None:
            return 1, _NPX_MISSING
        cmd = [npx, "--yes", "eslint", "."]
        config = section.get("eslint_config")
        if config is not None:
            cmd.extend(["--config", str(config)])
    return _run(cmd, root)
