from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentized.secrets_gate import (
    MAX_DISABLE_DAYS,
    _build_cmd,
    _mode,
    apply_secrets_connect,
    disable_decision_valid,
    persist_secrets_policy,
    pin_gitleaks_config,
    run_secrets_gate,
)


def _require_gitleaks() -> str:
    exe = shutil.which("gitleaks")
    if exe:
        return exe
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
        pytest.fail("gitleaks must be installed in CI for secrets gate tests")
    pytest.skip("gitleaks not installed locally")


def _quality(root: Path, secrets: dict) -> None:
    (root / "context").mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "coverage": {"lines": 80, "branches": 80},
        "modules": [],
        "secrets": secrets,
        "gates": {"ci": ["secrets"]},
    }
    (root / "context" / "quality.json").write_text(
        json.dumps(payload) + "\n", encoding="utf-8"
    )


def test_mode_defaults_and_invalid():
    assert _mode({}) == "hard"
    assert _mode({"mode": "warn"}) == "warn"
    assert _mode({"mode": "soft"}) == "hard"


def test_build_cmd_includes_config_when_present(tmp_path: Path):
    cfg = tmp_path / ".gitleaks.toml"
    cfg.write_text("title='t'\n", encoding="utf-8")
    report = tmp_path / "r.json"
    cmd = _build_cmd("gitleaks", tmp_path, config_path=cfg, report_path=report)
    assert cmd[0] == "gitleaks"
    assert cmd[1] == "detect"
    assert "--source" in cmd and str(tmp_path) in cmd
    assert "--config" in cmd and str(cfg) in cmd
    assert "--report-path" in cmd and str(report) in cmd
    assert cmd.count("--exit-code") == 1
    assert cmd[cmd.index("--exit-code") + 1] == "1"


def test_build_cmd_skips_missing_config(tmp_path: Path):
    missing = tmp_path / "nope.toml"
    report = tmp_path / "r.json"
    cmd = _build_cmd("gitleaks", tmp_path, config_path=missing, report_path=report)
    assert cmd.count("--config") == 0
    assert [x for x in cmd if x.endswith("nope.toml")] == []
    assert cmd[0:2] == ["gitleaks", "detect"]


def test_disabled_without_decision_hard_fails(tmp_path: Path):
    _quality(tmp_path, {"enabled": False, "mode": "hard"})
    assert run_secrets_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["findings"][0]["kind"] == "disabled_without_decision"
    assert summary["passed"] is False


def _decision(*, days: float = 7, approved_by: str = "Maxim", reason: str = "fixture") -> dict:
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {"reason": reason, "approved_by": approved_by, "expires": expires}


def test_disabled_with_valid_decision_skips(tmp_path: Path):
    _quality(
        tmp_path,
        {
            "enabled": False,
            "mode": "hard",
            "disable_decision": _decision(days=7),
        },
    )
    assert run_secrets_gate(tmp_path) == 0
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["toolNote"] == "disabled_by_decision"
    assert summary["findings"] == []


def test_disable_decision_valid_rules():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    too_far = (datetime.now(timezone.utc) + timedelta(days=MAX_DISABLE_DAYS + 1)).isoformat()
    edge = (datetime.now(timezone.utc) + timedelta(days=MAX_DISABLE_DAYS)).isoformat()
    cases = [
        ({}, False),
        ({"disable_decision": {"reason": "x", "approved_by": "Maxim"}}, False),
        (
            {
                "disable_decision": {
                    "reason": "x",
                    "approved_by": "Maxim",
                    "expires": "not-a-date",
                }
            },
            False,
        ),
        (
            {
                "disable_decision": {
                    "reason": "x",
                    "approved_by": "Maxim",
                    "expires": past,
                }
            },
            False,
        ),
        (
            {"disable_decision": {"reason": "x", "expires": future}},
            False,
        ),  # missing approved_by
        (
            {
                "disable_decision": {
                    "reason": "x",
                    "approved_by": "Maxim",
                    "expires": too_far,
                }
            },
            False,
        ),
        (
            {
                "disable_decision": {
                    "reason": "x",
                    "approved_by": "Maxim",
                    "expires": future,
                }
            },
            True,
        ),
        (
            {
                "disable_decision": {
                    "reason": "x",
                    "approved_by": "Maxim",
                    "expires": edge,
                }
            },
            True,
        ),
    ]
    assert [disable_decision_valid(cfg) for cfg, _ in cases] == [want for _, want in cases]
    assert MAX_DISABLE_DAYS == 14


def test_missing_binary_hard_fails(tmp_path: Path, monkeypatch):
    _quality(tmp_path, {"enabled": True, "mode": "hard"})
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: None)
    rc = run_secrets_gate(tmp_path)
    assert rc == 1
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["passed"] is False
    assert summary["mode"] == "hard"
    assert summary["findings"][0]["kind"] == "missing_binary"
    assert summary["binary"] is None


def test_missing_binary_warn_passes(tmp_path: Path, monkeypatch):
    _quality(tmp_path, {"enabled": True, "mode": "warn"})
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: None)
    rc = run_secrets_gate(tmp_path)
    assert rc == 0
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["passed"] is True
    assert summary["findings"][0]["kind"] == "missing_binary"


def test_clean_detect_passes(tmp_path: Path, monkeypatch):
    _quality(tmp_path, {"enabled": True, "mode": "hard", "config": ".gitleaks.toml"})
    (tmp_path / ".gitleaks.toml").write_text("title='t'\n", encoding="utf-8")
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: "/usr/bin/gitleaks")

    class _Proc:
        returncode = 0
        stdout = "No leaks found"
        stderr = ""

    monkeypatch.setattr(
        "agentized.secrets_gate.subprocess.run",
        lambda *a, **k: _Proc(),
    )
    assert run_secrets_gate(tmp_path) == 0
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["passed"] is True
    assert summary["findings"] == []
    assert summary["toolRc"] == 0
    assert summary["binary"] == "/usr/bin/gitleaks"


def test_leaks_hard_fail_from_report(tmp_path: Path, monkeypatch):
    _quality(tmp_path, {"enabled": True, "mode": "hard"})
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: "gitleaks")

    def _run(cmd, cwd, capture_output, text):  # noqa: ARG001
        report = Path(cmd[cmd.index("--report-path") + 1])
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                [
                    {
                        "File": "secrets.env",
                        "RuleID": "aws-access-key",
                        "Description": "AWS Access Key",
                    }
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        class _Proc:
            returncode = 1
            stdout = ""
            stderr = "leaks found"

        return _Proc()

    monkeypatch.setattr("agentized.secrets_gate.subprocess.run", _run)
    assert run_secrets_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["passed"] is False
    assert summary["findings"][0]["file"] == "secrets.env"
    assert summary["findings"][0]["kind"] == "aws-access-key"
    assert summary["findings"][0]["detail"] == "AWS Access Key"


def test_leak_without_report_uses_stderr(tmp_path: Path, monkeypatch):
    _quality(tmp_path, {"enabled": True, "mode": "hard"})
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: "gitleaks")

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "WRN leaks found: 2"

    monkeypatch.setattr(
        "agentized.secrets_gate.subprocess.run",
        lambda *a, **k: _Proc(),
    )
    assert run_secrets_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["findings"][0]["kind"] == "leak"
    assert "WRN leaks found: 2" in summary["findings"][0]["detail"]


def test_tool_error_hard_fails(tmp_path: Path, monkeypatch):
    _quality(tmp_path, {"enabled": True, "mode": "hard"})
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: "gitleaks")

    class _Proc:
        returncode = 2
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(
        "agentized.secrets_gate.subprocess.run",
        lambda *a, **k: _Proc(),
    )
    assert run_secrets_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["findings"][0]["kind"] == "tool_error"
    assert summary["findings"][0]["detail"] == "boom"


def test_custom_binary_path(tmp_path: Path, monkeypatch):
    _quality(
        tmp_path,
        {"enabled": True, "mode": "hard", "binary": str(tmp_path / "bin" / "gitleaks")},
    )
    custom = tmp_path / "bin" / "gitleaks"
    custom.parent.mkdir(parents=True)
    custom.write_text("#!/bin/sh\n", encoding="utf-8")
    seen: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _run(cmd, cwd, capture_output, text):  # noqa: ARG001
        seen.append(list(cmd))
        return _Proc()

    monkeypatch.setattr("agentized.secrets_gate.subprocess.run", _run)
    assert run_secrets_gate(tmp_path) == 0
    assert seen[0][0] == str(custom)


def test_custom_binary_via_which(tmp_path: Path, monkeypatch):
    _quality(tmp_path, {"enabled": True, "mode": "hard", "binary": "my-gitleaks"})
    monkeypatch.setattr(
        "agentized.secrets_gate.shutil.which",
        lambda name: "/opt/my-gitleaks" if name == "my-gitleaks" else None,
    )
    seen: list[str] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _run(cmd, cwd, capture_output, text):  # noqa: ARG001
        seen.append(cmd[0])
        return _Proc()

    monkeypatch.setattr("agentized.secrets_gate.subprocess.run", _run)
    assert run_secrets_gate(tmp_path) == 0
    assert seen == ["/opt/my-gitleaks"]


def test_leak_report_skips_non_dict_and_truncates(tmp_path: Path, monkeypatch):
    _quality(tmp_path, {"enabled": True, "mode": "hard"})
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: "gitleaks")

    def _run(cmd, cwd, capture_output, text):  # noqa: ARG001
        report = Path(cmd[cmd.index("--report-path") + 1])
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                [
                    "skip-me",
                    {
                        "File": "a.env",
                        "RuleID": "generic-api-key",
                        "Description": "X" * 300,
                    },
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        class _Proc:
            returncode = 1
            stdout = ""
            stderr = ""

        return _Proc()

    monkeypatch.setattr("agentized.secrets_gate.subprocess.run", _run)
    assert run_secrets_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(summary["findings"]) == 1
    assert summary["findings"][0]["file"] == "a.env"
    assert len(summary["findings"][0]["detail"]) == 240


def test_bad_json_report_falls_back(tmp_path: Path, monkeypatch):
    _quality(tmp_path, {"enabled": True, "mode": "hard"})
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: "gitleaks")

    def _run(cmd, cwd, capture_output, text):  # noqa: ARG001
        report = Path(cmd[cmd.index("--report-path") + 1])
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("{not-json", encoding="utf-8")

        class _Proc:
            returncode = 1
            stdout = ""
            stderr = "leaks found: 1"

        return _Proc()

    monkeypatch.setattr("agentized.secrets_gate.subprocess.run", _run)
    assert run_secrets_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["findings"][0]["kind"] == "leak"
    assert "leaks found: 1" in summary["findings"][0]["detail"]


def test_main_entrypoint(tmp_path: Path, monkeypatch):
    from agentized import secrets_gate as sg

    _quality(tmp_path, {"enabled": True, "mode": "hard"})
    monkeypatch.setattr(sg, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(sg.shutil, "which", lambda *_: None)
    assert sg.main(["--context", "context"]) == 1


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "root"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_real_gitleaks_detects_planted_secrets(tmp_path: Path):
    """Integration: real gitleaks + pinned config must catch planted tokens."""
    _require_gitleaks()
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    # Build fixtures at runtime so the commit has no contiguous secret literals
    # (GitHub push protection); values still match default gitleaks rules.
    github = "ghp_" + "wWHhP5N9XzvB6c3dEfGhIjKlMnOpQrStUvWx"
    stripe = "sk_live_" + "51Hq" + ("abcdefghijklmnopqrstuvwxyz" * 2) + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
    (repo / "leak.txt").write_text(f"{github}\n{stripe}\n", encoding="utf-8")
    subprocess.run(["git", "add", "leak.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "plant"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    # Inline pinned config (useDefault=true) — do not read templates/ (absent in mutmut sandbox).
    (repo / ".gitleaks.toml").write_text(
        'title = "Agentized"\n\n[extend]\nuseDefault = true\n\n'
        "[allowlist]\npaths = [\n  '''^(coverage|reports|mutants|\\.venv)/''',\n]\n",
        encoding="utf-8",
    )
    _quality(repo, {"enabled": True, "mode": "hard", "config": ".gitleaks.toml"})
    assert run_secrets_gate(repo) == 1
    summary = json.loads(
        (repo / "reports" / "secrets" / "secrets-summary.json").read_text(encoding="utf-8")
    )
    assert summary["toolRc"] == 1
    assert len(summary["findings"]) >= 1
    assert summary["passed"] is False


def test_real_gitleaks_clean_repo_passes(tmp_path: Path):
    _require_gitleaks()
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "ok.txt").write_text("hello agentized\n", encoding="utf-8")
    subprocess.run(["git", "add", "ok.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "clean"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / ".gitleaks.toml").write_text(
        'title = "Agentized"\n\n[extend]\nuseDefault = true\n',
        encoding="utf-8",
    )
    _quality(repo, {"enabled": True, "mode": "hard", "config": ".gitleaks.toml"})
    assert run_secrets_gate(repo) == 0
    summary = json.loads(
        (repo / "reports" / "secrets" / "secrets-summary.json").read_text(encoding="utf-8")
    )
    assert summary["toolRc"] == 0
    assert summary["findings"] == []
    assert summary["passed"] is True


def test_persist_secrets_injects_and_force_enables(tmp_path: Path):
    """AGE-29 reconnect policy: inject missing secrets; force-enable without decision."""
    from agentized.quality import load_quality

    ctx = tmp_path / "context"
    ctx.mkdir(parents=True)
    path = ctx / "quality.json"
    path.write_text(
        json.dumps(
            {
                "coverage": {"lines": 80, "branches": 80},
                "test_smells": {"mode": "hard", "enabled": True},
                "architecture": {"mode": "hard"},
                "gates": {
                    "pre_push": ["mechanical", "module_tests", "coverage"],
                    "ci": ["mechanical", "module_tests", "coverage"],
                },
                "modules": [{"id": "keep", "source": ["src"]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    info = persist_secrets_policy(tmp_path, "context")
    assert "secrets" in info["upgraded_modes"]
    cfg = load_quality(tmp_path)
    assert cfg["secrets"]["mode"] == "hard"
    assert cfg["secrets"]["tool"] == "gitleaks"
    assert cfg["gates"]["ci"][0:2] == ["mechanical", "secrets"]
    assert cfg["gates"]["pre_push"][0:2] == ["mechanical", "secrets"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["secrets"]["mode"] == "hard"
    again = persist_secrets_policy(tmp_path, "context")
    assert again["upgraded_modes"] == []

    path.write_text(
        json.dumps(
            {
                "coverage": {"lines": 80, "branches": 80},
                "secrets": {"enabled": False, "mode": "warn", "tool": "gitleaks"},
                "modules": [{"id": "keep", "source": ["src"]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    forced = persist_secrets_policy(tmp_path, "context")
    assert "secrets_enabled" in forced["upgraded_modes"]
    assert "secrets" in forced["upgraded_modes"]
    from agentized.secrets_gate import secrets_section
    secrets = secrets_section(tmp_path)
    assert secrets["enabled"] is True
    assert secrets["mode"] == "hard"

    path.write_text(
        json.dumps(
            {
                "coverage": {"lines": 80, "branches": 80},
                "secrets": {
                    "enabled": False,
                    "mode": "hard",
                    "tool": "gitleaks",
                    "disable_decision": _decision(days=1, reason="temp fixture"),
                },
                "modules": [{"id": "keep", "source": ["src"]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    kept = persist_secrets_policy(tmp_path, "context")
    assert kept["upgraded_modes"] == []
    # quality.py normalize does not merge secrets; use secrets_section / raw disk.
    from agentized.secrets_gate import secrets_section

    kept_secrets = secrets_section(tmp_path)
    assert kept_secrets["enabled"] is False
    assert kept_secrets["disable_decision"]["approved_by"] == "Maxim"
    assert json.loads(path.read_text(encoding="utf-8"))["secrets"]["enabled"] is False


def test_persist_secrets_noop_without_quality_file(tmp_path: Path):
    assert persist_secrets_policy(tmp_path, "context") == {
        "upgraded_modes": [],
        "created": False,
    }


def test_pin_gitleaks_toml_managed(tmp_path: Path):
    from agentized.managed import load_managed

    (tmp_path / "context").mkdir(parents=True)
    tpl = tmp_path / "templates" / "quality" / "gitleaks.toml.example"
    tpl.parent.mkdir(parents=True)
    tpl.write_text(
        'title = "Agentized"\n\n[extend]\nuseDefault = true\n',
        encoding="utf-8",
    )
    first = pin_gitleaks_config(tmp_path, "context")
    assert first == "created"
    dst = tmp_path / ".gitleaks.toml"
    assert dst.is_file()
    assert "useDefault = true" in dst.read_text(encoding="utf-8")
    assert ".gitleaks.toml" in load_managed(tmp_path, "context")["files"]

    second = pin_gitleaks_config(tmp_path, "context")
    assert second == "unchanged"

    dst.write_text("# user custom\n", encoding="utf-8")
    third = pin_gitleaks_config(tmp_path, "context")
    assert third == "skipped_user"
    assert dst.read_text(encoding="utf-8") == "# user custom\n"


def test_pin_gitleaks_missing_src(tmp_path: Path):
    (tmp_path / "context").mkdir(parents=True)
    tpl_dir = tmp_path / "templates" / "quality"
    tpl_dir.mkdir(parents=True)
    # Non-empty local templates/quality so we do not fall back to installed root.
    (tpl_dir / "ci.yml").write_text("name: x\n", encoding="utf-8")
    assert pin_gitleaks_config(tmp_path, "context") == "missing-src"


def test_apply_secrets_connect_combines(tmp_path: Path):
    (tmp_path / "context").mkdir(parents=True)
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps({"coverage": {"lines": 80, "branches": 80}, "modules": []}) + "\n",
        encoding="utf-8",
    )
    tpl = tmp_path / "templates" / "quality" / "gitleaks.toml.example"
    tpl.parent.mkdir(parents=True)
    tpl.write_text("[extend]\nuseDefault = true\n", encoding="utf-8")
    out = apply_secrets_connect(tmp_path, "context")
    assert "secrets" in out["upgraded_modes"]
    assert out["gitleaks_config"] == "created"
    assert (tmp_path / ".gitleaks.toml").is_file()
