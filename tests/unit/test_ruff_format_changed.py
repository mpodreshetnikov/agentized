"""Script-level contracts for scripts/quality/ruff_format_changed.sh (AGE-48)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "quality" / "ruff_format_changed.sh"


def test_ruff_format_changed_script_exists_and_executable():
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111


def test_ruff_format_changed_bad_base_exits_1(tmp_path: Path):
    """Invalid BASE must fail closed (exit 1), never succeed via || true."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    proc = subprocess.run(
        ["bash", str(SCRIPT), "0000000000000000000000000000000000000000"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "invalid base" in (proc.stderr + proc.stdout).lower() or proc.returncode == 1


def test_ruff_format_changed_missing_arg_exits_1():
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1


def test_ci_invokes_ruff_format_changed_script_no_inline_pip():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/quality/ruff_format_changed.sh" in ci
    assert "pip install 'ruff" not in ci
    assert 'pip install "ruff' not in ci
    ruff_step = ci.split("Ruff format (changed files)")[1].split("Mechanical checks")[0]
    assert "|| true" not in ruff_step
    # Dogfood only — template must not carry the gate (AGE-48 decision).
    template = (ROOT / "templates" / "quality" / "ci.yml").read_text(encoding="utf-8")
    assert "ruff_format_changed" not in template
    assert "Ruff format" not in template


def test_requirements_pins_exact_ruff():
    req = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "ruff==0.17.6" in req
    assert "ruff>=" not in req
