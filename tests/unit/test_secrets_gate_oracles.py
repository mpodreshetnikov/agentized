"""High-signal oracles that kill mutmut survivors on secrets_gate (AGE-29)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentized.secrets_gate import (
    MAX_DISABLE_DAYS,
    _FALSEY,
    _build_cmd,
    _findings_from_report,
    _is_disabled_flag,
    _mode,
    _quality_templates_dir,
    _resolve_gitleaks,
    _write_summary,
    disable_decision_valid,
    main,
    persist_secrets_policy,
    pin_gitleaks_config,
    run_secrets_gate,
    secrets_section,
)


def test_mode_oracle_non_string_and_case():
    assert _mode({}) == "hard"
    assert _mode({"mode": None}) == "hard"
    assert _mode({"mode": 1}) == "hard"
    assert _mode({"mode": "WARN"}) == "warn"
    assert _mode({"mode": "Warn"}) == "warn"
    assert _mode({"mode": "hard"}) == "hard"
    assert _mode({"mode": "soft"}) == "hard"
    assert _mode({"mode": ""}) == "hard"


def test_is_disabled_flag_oracle_matrix():
    assert _is_disabled_flag(False) is True
    assert _is_disabled_flag(True) is False
    assert _is_disabled_flag(0) is True
    assert _is_disabled_flag(1) is False
    assert _is_disabled_flag("false") is True
    assert _is_disabled_flag("FALSE") is True
    assert _is_disabled_flag(" no ") is True
    assert _is_disabled_flag("0") is True
    assert _is_disabled_flag("yes") is False
    assert _is_disabled_flag("true") is False
    assert _FALSEY == frozenset({"false", "0", "no"})


def test_disable_decision_oracle_clock_and_aliases():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ok = {
        "disable_decision": {
            "reason": "tmp",
            "approved_by": "Maxim",
            "expires": "2026-01-10T00:00:00Z",
        }
    }
    assert disable_decision_valid(ok, now=now) is True
    # expiry alias
    alias = {
        "disable_decision": {
            "reason": "tmp",
            "approved_by": "Maxim",
            "expiry": "2026-01-10T00:00:00+00:00",
        }
    }
    assert disable_decision_valid(alias, now=now) is True
    # expires_at alias
    alias2 = {
        "disable_decision": {
            "reason": "tmp",
            "approved_by": "Maxim",
            "expires_at": "2026-01-10T00:00:00",
        }
    }
    assert disable_decision_valid(alias2, now=now) is True
    # exactly at clock → false
    edge = {
        "disable_decision": {
            "reason": "tmp",
            "approved_by": "Maxim",
            "expires": "2026-01-01T00:00:00Z",
        }
    }
    assert disable_decision_valid(edge, now=now) is False
    # >14d → false
    far = {
        "disable_decision": {
            "reason": "tmp",
            "approved_by": "Maxim",
            "expires": (now + timedelta(days=MAX_DISABLE_DAYS + 1)).isoformat(),
        }
    }
    assert disable_decision_valid(far, now=now) is False
    # blank approved_by
    assert (
        disable_decision_valid(
            {"disable_decision": {"reason": "x", "approved_by": "  ", "expires": "2026-01-10T00:00:00Z"}},
            now=now,
        )
        is False
    )


def test_write_summary_passed_oracle(tmp_path: Path):
    path = tmp_path / "s.json"
    hard = _write_summary(
        path,
        mode="hard",
        binary="/bin/gitleaks",
        config_rel=".gitleaks.toml",
        findings=[{"file": "a", "kind": "leak", "detail": "x"}],
        tool_rc=1,
        tool_note="n",
    )
    assert hard["passed"] is False
    assert hard["mode"] == "hard"
    assert hard["binary"] == "/bin/gitleaks"
    assert hard["tool"] == "gitleaks"
    assert hard["schemaVersion"] == 1
    warn = _write_summary(
        path,
        mode="warn",
        binary=None,
        config_rel=None,
        findings=[{"file": "a", "kind": "leak", "detail": "x"}],
        tool_rc=1,
        tool_note="n",
    )
    assert warn["passed"] is True
    clean = _write_summary(
        path,
        mode="hard",
        binary="g",
        config_rel=None,
        findings=[],
        tool_rc=0,
        tool_note="",
    )
    assert clean["passed"] is True
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["passed"] is True


def test_findings_from_report_oracle(tmp_path: Path):
    report = tmp_path / "r.json"
    report.write_text(
        json.dumps(
            [
                {
                    "File": "a.env",
                    "RuleID": "generic-api-key",
                    "Description": "d" * 300,
                },
                "skip-me",
                {"file": "b.env", "Rule": "r2", "Secret": "sekrit"},
            ]
        ),
        encoding="utf-8",
    )
    found = _findings_from_report(report, "note")
    assert len(found) == 2
    assert found[0]["file"] == "a.env"
    assert found[0]["kind"] == "generic-api-key"
    assert len(found[0]["detail"]) == 240
    assert found[1]["file"] == "b.env"
    assert found[1]["kind"] == "r2"
    assert found[1]["detail"] == "sekrit"
    # bad json → fallback note
    report.write_text("{bad", encoding="utf-8")
    assert _findings_from_report(report, "fallback") == [
        {"file": "", "kind": "leak", "detail": "fallback"}
    ]
    assert _findings_from_report(tmp_path / "missing.json", "") == [
        {"file": "", "kind": "leak", "detail": "gitleaks exit 1 (secrets detected)"}
    ]


def test_build_cmd_and_resolve_oracle(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".gitleaks.toml"
    cfg.write_text("title='t'\n", encoding="utf-8")
    report = tmp_path / "r.json"
    cmd = _build_cmd("gitleaks", tmp_path, config_path=cfg, report_path=report)
    assert cmd[:2] == ["gitleaks", "detect"]
    assert cmd[cmd.index("--exit-code") + 1] == "1"
    assert "--config" in cmd
    missing = tmp_path / "no.toml"
    cmd2 = _build_cmd("gitleaks", tmp_path, config_path=missing, report_path=report)
    assert "--config" not in cmd2

    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda name: f"/bin/{name}")
    assert _resolve_gitleaks({}) == "/bin/gitleaks"
    assert _resolve_gitleaks({"binary": "custom"}) == "/bin/custom"
    custom = tmp_path / "gl"
    custom.write_text("x", encoding="utf-8")
    assert _resolve_gitleaks({"binary": str(custom)}) == str(custom)
    assert _resolve_gitleaks({"binary": "   "}) == "/bin/gitleaks"


def test_quality_templates_dir_oracle(tmp_path: Path):
    empty = tmp_path / "templates" / "quality"
    empty.mkdir(parents=True)
    # empty local → fall through to installed
    installed = _quality_templates_dir(tmp_path)
    assert installed.name == "quality"
    (empty / "ci.yml").write_text("x\n", encoding="utf-8")
    assert _quality_templates_dir(tmp_path) == empty


def test_secrets_section_overlays_disk(tmp_path: Path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "quality.json").write_text(
        json.dumps(
            {
                "coverage": {"lines": 80, "branches": 80},
                "secrets": {"enabled": False, "mode": "warn", "binary": "/x"},
                "modules": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    sec = secrets_section(tmp_path)
    assert sec["enabled"] is False
    assert sec["mode"] == "warn"
    assert sec["binary"] == "/x"
    assert sec["tool"] == "gitleaks"  # default retained then overlaid


def test_disabled_warn_mode_returns_zero(tmp_path: Path):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "coverage": {"lines": 80, "branches": 80},
                "secrets": {"enabled": False, "mode": "warn"},
                "modules": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert run_secrets_gate(tmp_path) == 0
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["findings"][0]["kind"] == "disabled_without_decision"
    assert summary["passed"] is True  # warn


def test_tool_error_non_one_rc(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "coverage": {"lines": 80, "branches": 80},
                "secrets": {"enabled": True, "mode": "hard"},
                "modules": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: "gitleaks")

    class _Proc:
        returncode = 2
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(
        "agentized.secrets_gate.subprocess.run", lambda *a, **k: _Proc()
    )
    assert run_secrets_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["findings"][0]["kind"] == "tool_error"
    assert "boom" in summary["findings"][0]["detail"]


def test_main_without_context_flag(tmp_path: Path, monkeypatch):
    from agentized import secrets_gate as sg

    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(
        json.dumps(
            {
                "coverage": {"lines": 80, "branches": 80},
                "secrets": {"enabled": True, "mode": "hard"},
                "modules": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sg, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(sg.shutil, "which", lambda *_: None)
    assert main([]) == 1


def test_persist_inserts_secrets_before_mechanical_absent(tmp_path: Path):
    from agentized.quality import load_quality

    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "quality.json").write_text(
        json.dumps(
            {
                "coverage": {"lines": 80, "branches": 80},
                "gates": {"pre_push": ["module_tests"], "ci": ["module_tests"]},
                "modules": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    info = persist_secrets_policy(tmp_path, "context")
    assert "secrets" in info["upgraded_modes"]
    cfg = load_quality(tmp_path)
    assert cfg["gates"]["ci"][0] == "secrets"
    assert cfg["gates"]["pre_push"][0] == "secrets"


def test_pin_missing_src_when_local_empty_file_missing(tmp_path: Path):
    (tmp_path / "context").mkdir()
    tpl = tmp_path / "templates" / "quality"
    tpl.mkdir(parents=True)
    (tpl / "ci.yml").write_text("x\n", encoding="utf-8")
    assert pin_gitleaks_config(tmp_path, "context") == "missing-src"
