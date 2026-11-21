"""JS/TS architecture runners (AGE-34)."""
from __future__ import annotations

from pathlib import Path

from agentized import architecture_gate as arch
from agentized import architecture_js as ajs


def test_dependency_cruiser_and_eslint(tmp_path: Path, monkeypatch):
    (tmp_path / ".dependency-cruiser.cjs").write_text("module.exports={}\n", encoding="utf-8")

    class R:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(ajs.shutil, "which", lambda n: "/usr/bin/npx")
    monkeypatch.setattr(ajs.subprocess, "run", lambda *a, **k: R())
    assert ajs.run_dependency_cruiser(
        tmp_path, {"js_config": ".dependency-cruiser.cjs", "js_source": "src"}
    ) == (0, "ok")
    assert arch._run_dependency_cruiser(
        tmp_path, {"js_config": ".dependency-cruiser.cjs", "js_source": "src"}
    ) == (0, "ok")
    assert ajs.run_eslint_boundaries(tmp_path, {})[0] == 0
    seen: dict = {}
    monkeypatch.setattr(
        ajs.subprocess,
        "run",
        lambda cmd, **k: seen.update(cmd=cmd) or type("R", (), {"returncode": 0, "stdout": "", "stderr": "clean"})(),
    )
    rc, out = ajs.run_eslint_boundaries(tmp_path, {"eslint_config": "eslint.config.js"})
    assert (rc, out) == (0, "clean")
    assert seen["cmd"] == ["/usr/bin/npx", "--yes", "eslint", ".", "--config", "eslint.config.js"]
    monkeypatch.setattr(ajs.shutil, "which", lambda n: None)
    assert ajs.run_dependency_cruiser(tmp_path, {"js_config": ".dependency-cruiser.cjs"})[0] == 1
    assert ajs.run_eslint_boundaries(tmp_path, {})[0] == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ajs.run_dependency_cruiser(empty, {"js_config": ".dependency-cruiser.cjs"}) == (
        1,
        "missing dependency-cruiser config: .dependency-cruiser.cjs",
    )
