"""JS/TS architecture runners (AGE-34)."""
from __future__ import annotations

from pathlib import Path

from agentized import architecture_gate as arch
from agentized import architecture_js as ajs


def test_run_dependency_cruiser_and_eslint_helpers(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".dependency-cruiser.cjs"
    cfg.write_text("module.exports={}\n", encoding="utf-8")

    class R:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(ajs.shutil, "which", lambda n: "/usr/bin/npx")
    monkeypatch.setattr(ajs.subprocess, "run", lambda *a, **k: R())
    rc, out = ajs.run_dependency_cruiser(
        tmp_path, {"js_config": ".dependency-cruiser.cjs", "js_source": "src"}
    )
    assert (rc, out) == (0, "ok")
    # Alias on architecture_gate stays wired.
    assert arch._run_dependency_cruiser(
        tmp_path, {"js_config": ".dependency-cruiser.cjs", "js_source": "src"}
    ) == (0, "ok")

    rc2, out2 = ajs.run_eslint_boundaries(tmp_path, {})
    assert rc2 == 0 and out2 == "ok"

    monkeypatch.setattr(ajs.shutil, "which", lambda n: None)
    rc3, note = ajs.run_dependency_cruiser(tmp_path, {"js_config": ".dependency-cruiser.cjs"})
    assert rc3 == 1 and note == "npx not found — install Node to run dependency-cruiser"
    rc4, note4 = ajs.run_eslint_boundaries(tmp_path, {})
    assert rc4 == 1 and note4 == "npx not found — install Node to run eslint-boundaries"

    missing = tmp_path / "empty"
    missing.mkdir()
    rc5, note5 = ajs.run_dependency_cruiser(missing, {"js_config": ".dependency-cruiser.cjs"})
    assert rc5 == 1 and note5 == "missing dependency-cruiser config: .dependency-cruiser.cjs"


def test_eslint_with_config_flag(tmp_path: Path, monkeypatch):
    class R:
        returncode = 0
        stdout = ""
        stderr = "clean"

    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return R()

    monkeypatch.setattr(ajs.shutil, "which", lambda n: "/bin/npx")
    monkeypatch.setattr(ajs.subprocess, "run", fake_run)
    rc, out = ajs.run_eslint_boundaries(tmp_path, {"eslint_config": "eslint.config.js"})
    assert rc == 0
    assert out == "clean"
    assert seen["cmd"] == ["/bin/npx", "--yes", "eslint", ".", "--config", "eslint.config.js"]
