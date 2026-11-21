"""High-signal oracles that kill mutmut survivors on secrets_gate (AGE-29)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentized.secrets_gate import (
    MAX_DISABLE_DAYS,
    _FALSEY,
    _findings_from_report,
    _is_disabled_flag,
    _mode,
    _quality_templates_dir,
    _resolve_gitleaks,
    _write_summary,
    disable_decision_valid,
    main,
    persist_secrets_policy,
    run_secrets_gate,
    secrets_section,
)


def test_mode_oracle_non_string_and_case():
    assert _mode({}) == "hard"
    assert _mode({"mode": None}) == "hard"
    assert _mode({"mode": 1}) == "hard"
    assert _mode({"mode": "WARN"}) == "warn"
    assert _mode({"mode": "soft"}) == "hard"
    assert _mode({"mode": ""}) == "hard"


def test_is_disabled_flag_oracle_matrix():
    assert _is_disabled_flag(False) is True
    assert _is_disabled_flag(True) is False
    assert _is_disabled_flag(0) is True
    assert _is_disabled_flag(1) is False
    assert _is_disabled_flag("FALSE") is True
    assert _is_disabled_flag(" no ") is True
    assert _is_disabled_flag("yes") is False
    assert _FALSEY == frozenset({"false", "0", "no"})


def test_disable_decision_oracle_clock_and_aliases():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert disable_decision_valid(
        {"disable_decision": {"reason": "tmp", "approved_by": "Maxim", "expires": "2026-01-10T00:00:00Z"}},
        now=now,
    )
    assert disable_decision_valid(
        {"disable_decision": {"reason": "tmp", "approved_by": "Maxim", "expiry": "2026-01-10T00:00:00+00:00"}},
        now=now,
    )
    assert disable_decision_valid(
        {"disable_decision": {"reason": "tmp", "approved_by": "Maxim", "expires_at": "2026-01-10T00:00:00"}},
        now=now,
    )
    assert not disable_decision_valid(
        {"disable_decision": {"reason": "tmp", "approved_by": "Maxim", "expires": "2026-01-01T00:00:00Z"}},
        now=now,
    )
    assert not disable_decision_valid(
        {
            "disable_decision": {
                "reason": "tmp",
                "approved_by": "Maxim",
                "expires": (now + timedelta(days=MAX_DISABLE_DAYS + 1)).isoformat(),
            }
        },
        now=now,
    )


def test_write_summary_passed_oracle(tmp_path: Path):
    path = tmp_path / "s.json"
    hard = _write_summary(path, mode="hard", binary="/bin/gitleaks", config_rel=".gitleaks.toml",
                          findings=[{"file": "a", "kind": "leak", "detail": "x"}], tool_rc=1, tool_note="n")
    assert hard["passed"] is False and hard["schemaVersion"] == 1
    warn = _write_summary(path, mode="warn", binary=None, config_rel=None,
                          findings=[{"file": "a", "kind": "leak", "detail": "x"}], tool_rc=1, tool_note="n")
    assert warn["passed"] is True
    clean = _write_summary(path, mode="hard", binary="g", config_rel=None, findings=[], tool_rc=0, tool_note="")
    assert clean["passed"] is True


def test_findings_from_report_oracle(tmp_path: Path):
    report = tmp_path / "r.json"
    report.write_text(json.dumps([
        {"File": "a.env", "RuleID": "generic-api-key", "Description": "d" * 300},
        "skip-me",
        {"file": "b.env", "Rule": "r2", "Secret": "sekrit"},
    ]), encoding="utf-8")
    found = _findings_from_report(report, "note")
    assert len(found) == 2
    assert found[0]["kind"] == "generic-api-key" and len(found[0]["detail"]) == 240
    assert found[1]["detail"] == "sekrit"
    report.write_text("{bad", encoding="utf-8")
    assert _findings_from_report(report, "fallback")[0]["detail"] == "fallback"
    assert _findings_from_report(tmp_path / "missing.json", "")[0]["detail"].startswith("gitleaks exit 1")


def test_resolve_and_templates_oracle(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda name: f"/bin/{name}")
    assert _resolve_gitleaks({}) == "/bin/gitleaks"
    assert _resolve_gitleaks({"binary": "custom"}) == "/bin/custom"
    custom = tmp_path / "gl"
    custom.write_text("x", encoding="utf-8")
    assert _resolve_gitleaks({"binary": str(custom)}) == str(custom)
    empty = tmp_path / "templates" / "quality"
    empty.mkdir(parents=True)
    installed = _quality_templates_dir(tmp_path)
    assert installed.name == "quality"
    (empty / "ci.yml").write_text("x\n", encoding="utf-8")
    assert _quality_templates_dir(tmp_path) == empty


def test_secrets_section_and_warn_disabled(tmp_path: Path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "secrets": {"enabled": False, "mode": "warn", "binary": "/x"},
        "modules": [],
    }) + "\n", encoding="utf-8")
    sec = secrets_section(tmp_path)
    assert sec["enabled"] is False and sec["mode"] == "warn" and sec["binary"] == "/x"
    assert sec["tool"] == "gitleaks"
    assert run_secrets_gate(tmp_path) == 0
    summary = json.loads((tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(encoding="utf-8"))
    assert summary["findings"][0]["kind"] == "disabled_without_decision"
    assert summary["passed"] is True


def test_tool_error_and_main(tmp_path: Path, monkeypatch):
    from agentized import secrets_gate as sg
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "secrets": {"enabled": True, "mode": "hard"},
        "modules": [],
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: "gitleaks")
    class _Proc:
        returncode = 2
        stdout = ""
        stderr = "boom"
    monkeypatch.setattr("agentized.secrets_gate.subprocess.run", lambda *a, **k: _Proc())
    assert run_secrets_gate(tmp_path) == 1
    summary = json.loads((tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(encoding="utf-8"))
    assert summary["findings"][0]["kind"] == "tool_error"
    monkeypatch.setattr(sg, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(sg.shutil, "which", lambda *_: None)
    assert main([]) == 1


def test_persist_no_mechanical_gate(tmp_path: Path):
    from agentized.quality import load_quality
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "gates": {"pre_push": ["module_tests"], "ci": ["module_tests"]},
        "modules": [],
    }) + "\n", encoding="utf-8")
    info = persist_secrets_policy(tmp_path, "context")
    assert "secrets" in info["upgraded_modes"]
    cfg = load_quality(tmp_path)
    assert cfg["gates"]["ci"][0] == "secrets" and cfg["gates"]["pre_push"][0] == "secrets"
