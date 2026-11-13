from __future__ import annotations

import json
from pathlib import Path

from agentized import coverage_check as cc
from agentized.quality import default_quality_config, save_quality


def test_coverage_check_skip_tests_fails_without_artifacts(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    save_quality(tmp_path, default_quality_config())
    monkeypatch.chdir(tmp_path)
    rc = cc.run_coverage_check(tmp_path, skip_tests=True)
    assert rc == 1


def test_coverage_check_pass_with_artifacts(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    cfg = default_quality_config()
    cfg["coverage"] = {"lines": 80, "branches": 80}
    cfg["modules"] = [
        {
            "id": "runtime",
            "source": ["runtime/agentized"],
            "test_command": "",
            "coverage_json": "coverage/runtime/coverage.json",
            "thresholds": {},
        }
    ]
    save_quality(tmp_path, cfg)
    cov = tmp_path / "coverage" / "runtime"
    cov.mkdir(parents=True)
    (cov / "coverage.json").write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 9,
                    "num_statements": 10,
                    "covered_branches": 8,
                    "num_branches": 10,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    rc = cc.run_coverage_check(tmp_path, skip_tests=True)
    assert rc == 0


def test_check_module_threshold_fail():
    cfg = {"coverage": {"lines": 90, "branches": 90}}
    module = {"id": "m", "thresholds": {}}
    summary = {
        "totals": {
            "lines_pct": 50.0,
            "branches_pct": 50.0,
            "lines_hit": 1,
            "lines_found": 2,
            "branches_hit": 1,
            "branches_found": 2,
        },
        "artifact_ok": True,
        "missing_artifacts": [],
    }
    assert cc._check_module(cfg, module, summary) == 1
