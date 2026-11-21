from __future__ import annotations

import json
from pathlib import Path

from agentized import mutation as mut
from agentized import mutation_stryker as ms

# fmt: off


def _report(tmp_path: Path, payload: dict, name: str = "mutation.json") -> None:
    d = tmp_path / "reports" / "mutation"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(payload))


def _muts(*statuses: str) -> list[dict]:
    return [{"status": s} for s in statuses]


def _gate(tmp_path, **kw):
    d = {"changed": ["src/a.ts"], "mut": {}, "base": "unique-base-xyz", "min_score": 100.0,
         "languages": ["typescript"], "write_summary": mut._write_summary}
    d.update(kw)
    return ms.run_stryker_gate(tmp_path, **d)


def _write_on_run(tmp_path: Path, payload: dict):
    class R0:
        returncode = 0
    return lambda cmd, **kw: (_report(tmp_path, payload), R0())[1]


def test_clear_covers_read_and_gate(tmp_path: Path, monkeypatch):
    _report(tmp_path, {"files": {"a.ts": {"mutants": _muts("Killed")}}})
    _report(tmp_path, {"files": {}}, name="mutation-result.json")
    ms.clear_stryker_reports(tmp_path)
    assert not (tmp_path / "reports/mutation/mutation.json").is_file()
    assert not (tmp_path / "reports/mutation/mutation-result.json").is_file()
    ms.clear_stryker_reports(tmp_path)
    assert ms.report_covers_changed(["src/a.ts"], ["src/a.ts"])
    assert ms.report_covers_changed(["src/a.ts"], [r"src\a.ts"])
    assert ms.report_covers_changed([r"src\a.ts"], ["src/a.ts"])
    assert ms.report_covers_changed(["src/a.ts"], ["proj/src/a.ts"])
    assert ms.report_covers_changed(["proj/src/a.ts"], ["src/a.ts"])
    assert ms.report_covers_changed(["src/a.ts"], [])
    assert not ms.report_covers_changed(["src/b.ts"], ["src/a.ts"])
    assert not ms.report_covers_changed([], ["src/a.ts"])
    assert ms.report_covers_changed(["a.ts"], ["src/a.ts"])
    assert not ms.report_covers_changed(["src/a.ts"], ["src/a.ts/extra"])
    statuses = ["Killed", "Killed", "Survived", "Survived", "NoCoverage", "NoCoverage", "Timeout", "Timeout", "Other"]
    _report(tmp_path, {"files": {"src/a.ts": {"mutants": _muts(*statuses)}, "src/b.ts": {"mutants": _muts("Killed")}}})
    assert ms.read_stryker_covered(tmp_path) == {
        "mutationScoreCovered": 71.43, "mutationScore": 55.56, "killed": 3, "survived": 2,
        "no_tests": 2, "timeout": 2, "totalMutants": 9, "files": ["src/a.ts", "src/b.ts"],
        "source": "reports/mutation/mutation.json"}
    assert ms.read_stryker_covered(tmp_path / "missing") is None
    _report(tmp_path, {"files": {"c.ts": {"mutants": _muts("Killed", "Survived", "NoCoverage")}}})
    got = ms.read_stryker_covered(tmp_path)
    assert (got["mutationScore"], got["mutationScoreCovered"]) == (33.33, 50.0)
    _report(tmp_path, {"files": {}})
    assert ms.read_stryker_covered(tmp_path)["mutationScoreCovered"] is None
    _report(tmp_path, {"files": {"a.ts": {"mutants": _muts("Killed")}}}, name="mutation-result.json")
    (tmp_path / "reports/mutation/mutation.json").unlink()
    got = ms.read_stryker_covered(tmp_path)
    assert got is not None and (got["mutationScoreCovered"], got["mutationScore"]) == (100.0, 100.0)
    assert ms.find_stryker_wrapper(tmp_path / "empty") is None
    assert _gate(tmp_path, base="origin/main", min_score=100) == 1
    body = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert body["passed"] is False and body["reasons"] == ["no_stryker_runner"]
    assert (body["schemaVersion"], body["mode"], body["gate"], body["tool"]) == (1, "incremental", "hard", "stryker")
    assert "passed" in body and body["base"] == "origin/main"
    assert body["changedFiles"] == ["src/a.ts"] and body["languages"] == ["typescript"]
    assert body["minScoreCovered"] == 100
    preferred = tmp_path / "scripts" / "quality" / "run-mutation-js.cjs"
    preferred.parent.mkdir(parents=True)
    preferred.write_text("x\n")
    (tmp_path / "run-mutation-js.cjs").write_text("y\n")
    assert ms.find_stryker_wrapper(tmp_path) == preferred
    preferred.unlink()
    (tmp_path / "run-mutation-js.cjs").write_text("//\n")
    for k in ("MUTATION_BASE", "STRYKER_BASE", "MUTATION_MIN_SCORE_COVERED"):
        monkeypatch.delenv(k, raising=False)
    class R0:
        returncode = 0
    calls: dict = {}
    monkeypatch.setattr(
        ms.subprocess, "run",
        lambda cmd, **kw: calls.update(cmd=cmd, cwd=kw.get("cwd"), env=kw.get("env") or {}, check=kw.get("check")) or R0())
    _report(tmp_path, {"files": {"src/a.ts": {"mutants": _muts("Killed")}}})
    assert _gate(tmp_path, mut={"x": 1}) == 1
    no_rep = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert no_rep["passed"] is False and no_rep["reasons"] == ["no_stryker_report"]
    assert "PASSED" not in no_rep and "XXpassedXX" not in no_rep
    assert not (tmp_path / "reports/mutation/mutation.json").is_file()
    monkeypatch.setattr(
        ms.subprocess, "run",
        lambda cmd, **kw: (
            calls.update(cmd=cmd, cwd=kw.get("cwd"), env=kw.get("env") or {}, check=kw.get("check"))
            or _write_on_run(tmp_path, {"files": {"src/a.ts": {"mutants": _muts("Killed")}}})(cmd, **kw)))
    assert _gate(tmp_path, mut={"x": 1}) == 0
    ok = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert ok["passed"] is True and ok["reasons"] == [] and ok["stats"]["survived"] == 0
    assert (ok["schemaVersion"], ok["mode"], ok["gate"], ok["tool"]) == (1, "incremental", "hard", "stryker")
    assert ok["changedFiles"] == ["src/a.ts"] and ok["languages"] == ["typescript"]
    assert ok["minScoreCovered"] == 100.0
    monkeypatch.setattr(
        ms.subprocess, "run",
        _write_on_run(tmp_path, {"files": {"src/a.ts": {"mutants": _muts("Killed", "Survived")}}}))
    assert _gate(tmp_path) == 1
    bad = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert bad["reasons"] == ["score_covered=50.0<100.0", "survived=1"] and bad["stats"]["survived"] == 1
    assert calls["cmd"] == ["node", str(tmp_path / "run-mutation-js.cjs")]
    assert calls["cwd"] == tmp_path and calls["check"] is False
    assert calls["env"]["MUTATION_BASE"] == calls["env"]["STRYKER_BASE"] == "unique-base-xyz"
    assert calls["env"]["MUTATION_MIN_SCORE_COVERED"] == "100.0"
    monkeypatch.setattr(
        ms.subprocess, "run",
        _write_on_run(tmp_path, {"files": {"src/other.ts": {"mutants": _muts("Killed")}}}))
    assert _gate(tmp_path, changed=["src/a.ts"]) == 1
    miss = json.loads((tmp_path / "reports/mutation/mutation-summary.json").read_text())
    assert "report_missing_changed" in miss["reasons"]
    class R7:
        returncode = 7
    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: R7())
    assert _gate(tmp_path, base="b", min_score=80, languages=["javascript"]) == 7
# fmt: on
