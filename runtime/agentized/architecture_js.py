"""JS/TS architecture runners (dependency-cruiser / eslint-boundaries)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def run_dependency_cruiser(root: Path, section: dict[str, Any]) -> tuple[int, str]:
    config = root / str(
        section.get("js_config") or section.get("config") or ".dependency-cruiser.cjs"
    )
    source = str(section.get("js_source") or "src")
    if not config.exists():
        return 1, f"missing dependency-cruiser config: {config.name}"
    npx = shutil.which("npx")
    if not npx:
        return 1, "npx not found — install Node to run dependency-cruiser"
    cmd = [npx, "--yes", "dependency-cruiser", "--config", str(config), source]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return proc.returncode or 0, ((proc.stdout or "") + (proc.stderr or "")).strip()[:2000]


def run_eslint_boundaries(root: Path, section: dict[str, Any]) -> tuple[int, str]:
    config = section.get("eslint_config")
    cmd = list(section.get("eslint_boundaries_command") or [])
    if not cmd:
        npx = shutil.which("npx")
        if not npx:
            return 1, "npx not found — install Node to run eslint-boundaries"
        cmd = [npx, "--yes", "eslint", "."]
        if config:
            cmd.extend(["--config", str(config)])
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return proc.returncode or 0, ((proc.stdout or "") + (proc.stderr or "")).strip()[:2000]
