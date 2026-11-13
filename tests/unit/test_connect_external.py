from __future__ import annotations

import subprocess
from pathlib import Path

from agentized.connect import (
    _repo_packages,
    _quality_templates_dir,
    connect,
    installed_agentized_root,
    pin_quality_templates,
)


def test_installed_root_is_this_checkout():
    root = installed_agentized_root()
    assert (root / "runtime" / "agentized").is_dir()
    assert (root / "packages" / "shared").is_dir()


def test_repo_packages_falls_back_to_installed(tmp_path: Path):
    # foreign repo without packages/
    (tmp_path / "context").mkdir()
    assert _repo_packages(tmp_path) == installed_agentized_root() / "packages"
    # local packages/shared wins
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    assert _repo_packages(tmp_path) == tmp_path / "packages"


def test_quality_templates_fallback(tmp_path: Path):
    assert _quality_templates_dir(tmp_path) == installed_agentized_root() / "templates" / "quality"
    local = tmp_path / "templates" / "quality"
    local.mkdir(parents=True)
    (local / "pre-push").write_text("x\n", encoding="utf-8")
    assert _quality_templates_dir(tmp_path) == local


def test_connect_external_repo_uses_installed_assets(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (ctx / "tasks").mkdir()
    (ctx / "leases").mkdir()
    monkeypatch.chdir(tmp_path)
    result = connect(tmp_path, context_rel="context", harnesses=["cursor"], coverage_pct=80)
    # skills/hooks come from installed Agentized packages/
    assert (ctx / "skills" / "navigate" / "SKILL.md").exists()
    assert (ctx / "skills" / "communication-autonomy" / "SKILL.md").exists()
    assert (ctx / "skills" / "acceptance-artifacts" / "SKILL.md").exists()
    assert (ctx / "hooks" / "scripts" / "process_guard.py").exists()
    assert (ctx / "hooks" / "scripts" / "_bootstrap.py").exists()
    assert (ctx / "process-control.json").exists()
    assert (tmp_path / ".cursor" / "hooks" / "process_guard.py").exists()
    assert "process_guard" in (tmp_path / ".cursor" / "hooks.json").read_text(encoding="utf-8")
    assert result["quality_templates"]["pre_push"] in {"created", "updated", "unchanged"}
    assert "AGENTIZED:QUALITY" in (tmp_path / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert "command -v agentized" in (tmp_path / ".githooks" / "pre-push").read_text(encoding="utf-8")
    # second pin stays stable
    again = pin_quality_templates(tmp_path)
    assert again["pre_push"] in {"unchanged", "updated", "skipped-user-file"}
