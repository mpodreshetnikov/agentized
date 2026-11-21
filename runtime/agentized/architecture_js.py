"""JS/TS architecture runners (dependency-cruiser / eslint-boundaries)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def run_dependency_cruiser(root: Path, section: dict[str, Any]) -> tuple[int, str]:
    config_name = str(section.get("js_config") or section.get("config") or ".dependency-cruiser.cjs")
    config = root / config_name
    source = str(section.get("js_source") or "src")
    if not config.exists():
        return 1, f"missing:{config_name}"
    npx = shutil.which("npx")
    if not npx:
        return 1, "npx-missing"
    cmd = [npx, "--yes", "dependency-cruiser", "--config", str(config), source]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()[:2000]
    return proc.returncode or 0, out


def run_eslint_boundaries(root: Path, section: dict[str, Any]) -> tuple[int, str]:
    cmd = list(section.get("eslint_boundaries_command") or [])
    if not cmd:
        npx = shutil.which("npx")
        if not npx:
            return 1, "npx-missing"
        cmd = [npx, "--yes", "eslint", "."]
        config = section.get("eslint_config")
        if config:
            cmd.extend(["--config", str(config)])
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()[:2000]
    return proc.returncode or 0, out
