"""High-signal oracles that kill mutmut survivors on secrets_gate (AGE-29)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentized import secrets_gate as sg
from agentized.paths import DEFAULT_CONTEXT
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
    apply_secrets_connect,
    disable_decision_valid,
    main,
    persist_secrets_policy,
    pin_gitleaks_config,
    run_secrets_gate,
    secrets_section,
)


def test_mode_and_disabled_flag_matrix():
    assert _mode({}) == _mode({"mode": None}) == _mode({"mode": 1}) == _mode({"mode": "soft"}) == "hard"
    assert _mode({"mode": "WARN"}) == "warn"
    assert _mode({"mode": ""}) == "hard"
    assert _is_disabled_flag(False) is True and _is_disabled_flag(True) is False
    assert _is_disabled_flag(0) is True and _is_disabled_flag(1) is False
    assert _is_disabled_flag("FALSE") is True and _is_disabled_flag(" no ") is True
    assert _is_disabled_flag("yes") is False
    assert _FALSEY == frozenset({"false", "0", "no"})


def test_disable_decision_oracle_strict():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 1, 1, 12, 0, 0)
    base = {"reason": "XXXX", "approved_by": "Maxim", "expires": "2026-01-10T00:00:00Z"}
    assert disable_decision_valid({"disable_decision": base}, now=now) is True
    assert disable_decision_valid(
        {"disable_decision": {"reason": "tmp", "approved_by": "Maxim", "expiry": "2026-01-10T00:00:00+00:00"}},
        now=now,
    )
    assert disable_decision_valid(
        {"disable_decision": {"reason": "tmp", "approved_by": "Maxim", "expires_at": "2026-01-10T00:00:00"}},
        now=naive,
    )
    assert disable_decision_valid(
        {"disable_decision": {"reason": "", "approved_by": "Maxim", "expires": base["expires"]}}, now=now
    ) is False
    assert disable_decision_valid(
        {"disable_decision": {"reason": "tmp", "approved_by": "", "expires": "2026-01-10T00:00:00+00:00"}},
        now=now,
    ) is False
    assert disable_decision_valid(
        {"disable_decision": {"approved_by": "Maxim", "expires": base["expires"]}}, now=now
    ) is False
    assert disable_decision_valid(
        {"disable_decision": {"reason": "tmp", "approved_by": "Maxim", "expires": "not-a-date"}},
        now=now,
    ) is False
    assert disable_decision_valid(
        {"disable_decision": {"reason": "tmp", "approved_by": "Maxim", "expires": now.isoformat()}},
        now=now,
    ) is False
    edge = {
        "disable_decision": {
            "reason": "tmp",
            "approved_by": "Maxim",
            "expires": (now + timedelta(days=MAX_DISABLE_DAYS)).isoformat(),
        }
    }
    assert disable_decision_valid(edge, now=now) is True
    assert disable_decision_valid(
        {
            "disable_decision": {
                "reason": "tmp",
                "approved_by": "Maxim",
                "expires": (now + timedelta(days=MAX_DISABLE_DAYS + 1)).isoformat(),
            }
        },
        now=now,
    ) is False


def test_write_summary_and_findings(tmp_path: Path):
    path = tmp_path / "s.json"
    hard = _write_summary(
        path, mode="hard", binary="/bin/gitleaks", config_rel=".gitleaks.toml",
        findings=[{"file": "a", "kind": "leak", "detail": "x"}], tool_rc=1, tool_note="n",
    )
    assert hard["passed"] is False and hard["schemaVersion"] == 1
    assert hard["tool"] == "gitleaks" and "generatedAt" in hard
    raw = path.read_bytes().decode()
    assert raw.startswith("{\n  ") and raw.endswith("\n")
    assert '"tool": "gitleaks"' in raw
    assert _write_summary(
        path, mode="warn", binary=None, config_rel=None,
        findings=[{"file": "a", "kind": "leak", "detail": "x"}], tool_rc=1, tool_note="n",
    )["passed"] is True
    assert _write_summary(
        path, mode="hard", binary="g", config_rel=None, findings=[], tool_rc=0, tool_note="",
    )["passed"] is True
    report = tmp_path / "r.json"
    report.write_text(json.dumps([
        {"File": "a.env", "RuleID": "generic-api-key", "Description": "d" * 300},
        "skip-me",
        {"file": "b.env", "Rule": "r2", "Secret": "sekrit"},
        {"Match": "only-match"},
        {},
    ]), encoding="utf-8")
    found = _findings_from_report(report, "note")
    assert len(found) == 4
    assert found[0]["kind"] == "generic-api-key" and len(found[0]["detail"]) == 240
    assert found[1] == {"file": "b.env", "kind": "r2", "detail": "sekrit"}
    assert found[2] == {"file": "", "kind": "leak", "detail": "only-match"}
    assert found[3] == {"file": "", "kind": "leak", "detail": "secret detected"}
    report.write_text(json.dumps([
        {"Description": None, "Secret": None, "Match": None, "File": "XXXX", "RuleID": "XXXX"},
    ]), encoding="utf-8")
    assert _findings_from_report(report, "n") == [{"file": "XXXX", "kind": "XXXX", "detail": "secret detected"}]
    report.write_text("{bad", encoding="utf-8")
    assert _findings_from_report(report, "fallback") == [{"file": "", "kind": "leak", "detail": "fallback"}]
    assert _findings_from_report(tmp_path / "missing.json", "") == [
        {"file": "", "kind": "leak", "detail": "gitleaks exit 1 (secrets detected)"}
    ]


def test_resolve_templates_build_cmd(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda name: f"/bin/{name}")
    assert _resolve_gitleaks({}) == "/bin/gitleaks"
    assert _resolve_gitleaks({"binary": "custom"}) == "/bin/custom"
    custom = tmp_path / "gl"
    custom.write_text("x", encoding="utf-8")
    assert _resolve_gitleaks({"binary": str(custom)}) == str(custom)
    empty = tmp_path / "templates" / "quality"
    empty.mkdir(parents=True)
    expected = Path(sg.__file__).resolve().parents[2] / "templates" / "quality"
    assert _quality_templates_dir(tmp_path) == expected
    (empty / "ci.yml").write_text("x\n", encoding="utf-8")
    assert _quality_templates_dir(tmp_path) == empty
    cmd = _build_cmd("gitleaks", tmp_path, config_path=None, report_path=tmp_path / "out.json")
    assert "--redact" in cmd and cmd[cmd.index("--report-format") + 1] == "json"


def test_section_warn_tool_main(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "secrets": {"enabled": False, "mode": "warn", "binary": "/x"},
        "modules": [],
    }) + "\n", encoding="utf-8")
    sec = secrets_section(tmp_path)
    assert sec["enabled"] is False and sec["mode"] == "warn" and sec["binary"] == "/x"
    assert sec["tool"] == "gitleaks" and run_secrets_gate(tmp_path) == 0
    summary = json.loads((tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(encoding="utf-8"))
    assert summary["findings"][0]["kind"] == "disabled_without_decision" and summary["passed"] is True

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
    calls: list[tuple[Path | None, str]] = []

    def _spy(root=None, *, context=DEFAULT_CONTEXT):
        calls.append((root, context))
        return 0

    monkeypatch.setattr(sg, "run_secrets_gate", _spy)
    monkeypatch.setattr(sg, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["prog", "--context", "fromsys"])
    assert main(None) == 0 and calls[-1] == (tmp_path, "fromsys")
    assert main(["--context", "fromarg"]) == 0 and calls[-1] == (tmp_path, "fromarg")
    assert main([]) == 0 and calls[-1] == (tmp_path, DEFAULT_CONTEXT)


def test_persist_custom_context_fields(tmp_path: Path, monkeypatch):
    from agentized.quality import load_quality, quality_path, save_quality

    ctx = "myctx"
    (tmp_path / ctx).mkdir()
    (tmp_path / ctx / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "gates": {"pre_push": ["module_tests"], "ci": ["module_tests"]},
        "secrets": {"enabled": False, "mode": "warn"},
        "modules": [],
    }) + "\n", encoding="utf-8")
    qp_args: list[str] = []
    lq_args: list[str] = []
    sq_args: list[str] = []
    real_qp, real_lq, real_sq = quality_path, load_quality, save_quality
    monkeypatch.setattr(sg, "quality_path", lambda root, c=DEFAULT_CONTEXT: qp_args.append(c) or real_qp(root, c))
    monkeypatch.setattr(
        "agentized.secrets_gate.load_quality",
        lambda root, c=DEFAULT_CONTEXT: lq_args.append(c) or real_lq(root, c),
    )
    monkeypatch.setattr(
        "agentized.quality.save_quality",
        lambda root, data, c=DEFAULT_CONTEXT: sq_args.append(c) or real_sq(root, data, c),
    )
    info = persist_secrets_policy(tmp_path, ctx)
    assert info == {"upgraded_modes": ["secrets", "secrets_enabled"], "created": False}
    assert qp_args == lq_args == sq_args == [ctx]
    disk = json.loads((tmp_path / ctx / "quality.json").read_text(encoding="utf-8"))
    assert disk["secrets"]["mode"] == "hard"
    assert disk["secrets"]["enabled"] is True
    assert set(disk["secrets"]) >= {"mode", "enabled"}


def test_persist_inject_when_absent(tmp_path: Path):
    from agentized.quality import load_quality

    ctx = "ctx2"
    (tmp_path / ctx).mkdir()
    (tmp_path / ctx / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "gates": {"pre_push": ["module_tests"], "ci": ["module_tests"]},
        "modules": [],
    }) + "\n", encoding="utf-8")
    info = persist_secrets_policy(tmp_path, ctx)
    assert info == {"upgraded_modes": ["secrets"], "created": False}
    cfg = load_quality(tmp_path, ctx)
    assert isinstance(cfg["secrets"], dict) and cfg["secrets"]["mode"] == "hard"
    assert cfg["gates"]["ci"][0] == "secrets" and cfg["gates"]["pre_push"][0] == "secrets"


def test_run_gate_context_summary_and_stdout(tmp_path: Path, monkeypatch, capsys):
    ctx = "rungate"
    (tmp_path / ctx).mkdir()
    (tmp_path / ".gitleaks.toml").write_text("title='t'\n", encoding="utf-8")
    (tmp_path / ctx / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "secrets": {
            "enabled": False,
            "mode": "warn",
            "report_dir": "custom-secrets",
            "config": ".gitleaks.toml",
        },
        "modules": [],
    }) + "\n", encoding="utf-8")
    sec_args: list[str] = []
    real_sec = secrets_section
    monkeypatch.setattr(
        sg, "secrets_section",
        lambda root, context=DEFAULT_CONTEXT: sec_args.append(context) or real_sec(root, context),
    )
    assert run_secrets_gate(tmp_path, context=ctx) == 0
    assert sec_args == [ctx]
    lines = capsys.readouterr().out.splitlines()
    assert "[secrets] warn mode — not failing the gate" in lines
    assert any(l.startswith("  (repo): disabled_without_decision: ") for l in lines)
    assert any(l.startswith("[secrets] 1 finding(s) (mode=warn)") for l in lines)
    summary = json.loads((tmp_path / "custom-secrets" / "secrets-summary.json").read_text(encoding="utf-8"))
    assert summary["config"] == ".gitleaks.toml"
    assert summary["findings"][0]["file"] == ""
    assert summary["findings"][0]["kind"] == "disabled_without_decision"
    assert summary["findings"][0]["detail"].startswith("secrets.enabled=false")
    assert "(reason + approved_by + unexpired expires ≤14d, human-only)." in summary["findings"][0]["detail"]

    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    (tmp_path / ctx / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "secrets": {
            "enabled": False,
            "mode": "hard",
            "disable_decision": {"reason": "tmp", "approved_by": "Maxim", "expires": future},
        },
        "modules": [],
    }) + "\n", encoding="utf-8")
    assert run_secrets_gate(tmp_path, context=ctx) == 0
    assert capsys.readouterr().out.splitlines() == ["[secrets] disabled by recorded decision — skip"]

    # custom config path must win over default (kills `and DEFAULT` mutant)
    custom_cfg = tmp_path / "custom.toml"
    custom_cfg.write_text("title='c'\n", encoding="utf-8")
    (tmp_path / ctx / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "secrets": {"mode": "hard", "config": "custom.toml"},
        "modules": [],
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: None)
    assert run_secrets_gate(tmp_path, context=ctx) == 1
    miss = json.loads((tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(encoding="utf-8"))
    assert miss["config"] == "custom.toml"
    assert miss["findings"][0]["kind"] == "missing_binary"
    assert miss["findings"][0]["file"] == ""
    assert "gitleaks binary not found on PATH" in miss["findings"][0]["detail"]

    (tmp_path / ctx / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80},
        "secrets": {"enabled": True, "mode": "hard", "config": ".gitleaks.toml"},
        "modules": [],
    }) + "\n", encoding="utf-8")
    run_kwargs: list[dict] = []

    class _Proc:
        returncode = 2
        stdout = "STDOUT"
        stderr = "STDERR"

    def _run(cmd, **kwargs):
        run_kwargs.append(kwargs)
        return _Proc()

    monkeypatch.setattr("agentized.secrets_gate.shutil.which", lambda *_: "gitleaks")
    monkeypatch.setattr("agentized.secrets_gate.subprocess.run", _run)
    assert run_secrets_gate(tmp_path, context=ctx) == 1
    assert run_kwargs[0]["capture_output"] is True and run_kwargs[0]["text"] is True
    assert run_kwargs[0]["cwd"] == str(tmp_path)
    note = json.loads((tmp_path / "reports" / "secrets" / "secrets-summary.json").read_text(encoding="utf-8"))
    assert note["toolNote"] == "STDOUTSTDERR"
    assert note["findings"][0]["kind"] == "tool_error"
    assert note["findings"][0]["file"] == ""


def test_apply_pin_context_manifest(tmp_path: Path, monkeypatch):
    ctx = "pinctx"
    (tmp_path / ctx).mkdir()
    (tmp_path / ctx / "quality.json").write_text(json.dumps({
        "coverage": {"lines": 80, "branches": 80}, "modules": [],
    }) + "\n", encoding="utf-8")
    tpl = tmp_path / "templates" / "quality" / "gitleaks.toml.example"
    tpl.parent.mkdir(parents=True)
    tpl.write_text("title='t'\n", encoding="utf-8")
    persist_calls: list[str] = []
    pin_calls: list[tuple[str, object]] = []
    real_persist, real_pin = persist_secrets_policy, pin_gitleaks_config
    monkeypatch.setattr(
        sg, "persist_secrets_policy",
        lambda root, c=DEFAULT_CONTEXT: persist_calls.append(c) or real_persist(root, c),
    )
    monkeypatch.setattr(
        sg, "pin_gitleaks_config",
        lambda root, c=DEFAULT_CONTEXT, *, manifest=None: pin_calls.append((c, manifest))
        or real_pin(root, c, manifest=manifest),
    )
    marker = {"marker": True}
    out = apply_secrets_connect(tmp_path, ctx, manifest=marker)
    assert persist_calls == [ctx] and pin_calls == [(ctx, marker)]
    assert isinstance(out["gitleaks_config"], str)

    from agentized import managed as managed_mod

    copy_calls: list[object] = []
    load_calls: list[str] = []
    real_copy, real_load = managed_mod.managed_copy_file, managed_mod.load_managed
    monkeypatch.setattr(sg, "persist_secrets_policy", real_persist)
    monkeypatch.setattr(sg, "pin_gitleaks_config", real_pin)
    monkeypatch.setattr(
        "agentized.managed.managed_copy_file",
        lambda root, c, src, dst, *, manifest: copy_calls.append(c)
        or real_copy(root, c, src, dst, manifest=manifest),
    )
    monkeypatch.setattr(
        "agentized.managed.load_managed",
        lambda root, c=DEFAULT_CONTEXT: load_calls.append(c) or real_load(root, c),
    )
    status = pin_gitleaks_config(tmp_path, ctx, manifest={"files": {}})
    assert status in {"created", "updated", "unchanged"}
    assert copy_calls == [ctx] and load_calls == []
