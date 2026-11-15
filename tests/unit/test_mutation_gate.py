from __future__ import annotations

import json
from pathlib import Path

from agentized import mutation as mut


def test_mutmut_failure_fails_gate_even_with_cached_mutants(tmp_path: Path, monkeypatch):
    """Codex P1: cached mutants must not make a failed mutmut run PASS."""
    (tmp_path / "context").mkdir()
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    # Fake prior successful mutant metadata
    meta_dir = tmp_path / "mutants" / "agentized"
    meta_dir.mkdir(parents=True)
    (meta_dir / "x.meta").write_text(
        json.dumps({"exit_code_by_key": {"a": 1}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(mut, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(mut, "load_quality", lambda *a, **k: {
        "mutation": {
            "enabled": True,
            "min_score_covered": 50,
            "break_on_no_tests": False,
            "include_globs": ["runtime/agentized/quality.py"],
        },
        "modules": [{"source": ["runtime/agentized"]}],
    })
    monkeypatch.setattr(mut, "_changed_py_files", lambda *a, **k: ["runtime/agentized/quality.py"])
    monkeypatch.setattr(mut, "_ensure_agentized_link", lambda root: False)
    monkeypatch.setattr(mut, "_write_setup", lambda root, only: None)

    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        # first call may be pytest; second mutmut
        class R:
            returncode = 1 if "mutmut" in cmd else 0

        return R()

    monkeypatch.setattr(mut.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "setup.cfg").write_text("[mutmut]\n", encoding="utf-8")

    rc = mut.run_mutation(tmp_path)
    assert rc == 1
    summary = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert summary["passed"] is False
    assert any("mutmut_exit=" in r for r in summary["reasons"])
