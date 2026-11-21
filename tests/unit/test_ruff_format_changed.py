"""Script-level contracts for scripts/quality/ruff_format_changed.sh (AGE-48)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "quality" / "ruff_format_changed.sh"
BAD_BASE = "0000000000000000000000000000000000000000"


def test_ruff_format_changed_script_exists_and_executable():
    assert SCRIPT.resolve() == (ROOT / "scripts" / "quality" / "ruff_format_changed.sh").resolve()
    assert SCRIPT.is_file()
    # At least one execute bit set (owner/group/other).
    assert (SCRIPT.stat().st_mode & 0o111) != 0


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
        ["bash", str(SCRIPT), BAD_BASE],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    err_lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("invalid base")]
    assert err_lines == [f"invalid base commit: {BAD_BASE}"]


def test_ruff_format_changed_missing_arg_exits_1():
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    first = proc.stderr.splitlines()[0]
    assert first.startswith("usage:")
    assert first.endswith("<base-sha-or-ref>")


def test_ci_invokes_ruff_format_changed_script_no_inline_pip():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    invoke_lines = [
        ln.strip()
        for ln in ci.splitlines()
        if "ruff_format_changed.sh" in ln and not ln.strip().startswith("#")
    ]
    assert invoke_lines == ['./scripts/quality/ruff_format_changed.sh "${BASE}"']
    pip_ruff_lines = [
        ln.strip()
        for ln in ci.splitlines()
        if "pip install" in ln and "ruff" in ln and not ln.strip().startswith("#")
    ]
    assert pip_ruff_lines == []
    ruff_step = ci.split("Ruff format (changed files)")[1].split("Mechanical checks")[0]
    soft_fail = [ln for ln in ruff_step.splitlines() if "|| true" in ln]
    assert soft_fail == []
    # Dogfood only — template must not carry the gate (AGE-48 decision).
    template = (ROOT / "templates" / "quality" / "ci.yml").read_text(encoding="utf-8")
    template_ruff = [
        ln for ln in template.splitlines() if "ruff_format_changed" in ln or "Ruff format" in ln
    ]
    assert template_ruff == []


def test_requirements_pins_exact_ruff():
    req = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in req.splitlines() if ln.strip().startswith("ruff")]
    assert lines == ["ruff==0.17.6"]
