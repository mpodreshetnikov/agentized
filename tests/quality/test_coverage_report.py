from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "quality"))
sys.path.insert(0, str(ROOT / "runtime"))

import coverage_report as cr
from agentized.quality import default_quality_config, save_quality


def test_coverage_parsers(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cr, "ROOT", tmp_path)
    lcov = tmp_path / "cov.lcov"
    lcov.write_text(
        "SF:runtime/agentized/paths.py\nLF:10\nLH:8\nBRF:4\nBRH:3\nend_of_record\n"
        "SF:runtime/agentized/paths.py\nLF:10\nLH:9\nBRF:4\nBRH:2\nend_of_record\n",
        encoding="utf-8",
    )
    assert cr.parse_lcov(lcov)["totals"]["lines_hit"] == 9
    p = tmp_path / "coverage.json"
    p.write_text(
        json.dumps({"totals": {"covered_lines": 8, "num_statements": 10, "covered_branches": 3, "num_branches": 4}}),
        encoding="utf-8",
    )
    assert cr.parse_coverage_json(p)["lines_pct"] == 80.0
    (tmp_path / "context").mkdir()
    cfg = default_quality_config()
    cfg["modules"] = [{
        "id": "runtime", "source": ["runtime/agentized"],
        "coverage_lcov": "coverage/runtime/lcov.info",
        "coverage_json": "coverage/runtime/coverage.json", "thresholds": {},
    }]
    save_quality(tmp_path, cfg)
    cov = tmp_path / "coverage/runtime"; cov.mkdir(parents=True)
    (cov / "lcov.info").write_text(
        "SF:runtime/agentized/paths.py\nLF:10\nLH:9\nBRF:4\nBRH:4\nend_of_record\n",
        encoding="utf-8",
    )
    (cov / "coverage.json").write_text(
        json.dumps({"totals": {"covered_lines": 9, "num_statements": 10, "covered_branches": 4, "num_branches": 4}}),
        encoding="utf-8",
    )
    summary = cr.build_report(tmp_path)
    assert summary["combined_pass"] is True
    assert cr.write_report(tmp_path, summary)[0].exists()
