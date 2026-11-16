from __future__ import annotations

import json
from pathlib import Path

from agentized.secrets_gate import _build_cmd, _mode, run_secrets_gate


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


def test_disabled_skips(tmp_path: Path):
    _quality(tmp_path, {"enabled": False, "mode": "hard"})
    assert run_secrets_gate(tmp_path) == 0


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

    _quality(tmp_path, {"enabled": False})
    monkeypatch.setattr(sg, "find_repo_root", lambda: tmp_path)
    assert sg.main(["--context", "context"]) == 0
