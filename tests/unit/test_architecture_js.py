from __future__ import annotations

from pathlib import Path

from agentized import architecture_js as ajs


def test_runners_pin_cmd_and_errors(tmp_path: Path, monkeypatch):
    (tmp_path / ".dependency-cruiser.cjs").write_text("module.exports={}\n")
    (tmp_path / "custom.cjs").write_text("x\n")

    class R:
        returncode, stdout, stderr = 0, "ok", ""

    seen: dict = {}
    monkeypatch.setattr(ajs.shutil, "which", lambda n: "/bin/npx" if n == "npx" else None)
    monkeypatch.setattr(
        ajs.subprocess,
        "run",
        lambda cmd, **k: (
            seen.update(
                cmd=list(cmd),
                cwd=k.get("cwd"),
                capture_output=k.get("capture_output"),
                text=k.get("text"),
                check=k.get("check"),
            )
            or R()
        ),
    )
    assert ajs.run_dependency_cruiser(
        tmp_path, {"js_config": "custom.cjs", "js_source": "lib"}
    ) == (
        0,
        "ok",
    )
    assert seen["cmd"] == [
        "/bin/npx",
        "--yes",
        "dependency-cruiser",
        "--config",
        str(tmp_path / "custom.cjs"),
        "lib",
    ]
    assert seen["cwd"] == tmp_path and seen["capture_output"] is True and seen["text"] is True
    assert seen["check"] is False
    assert ajs.run_dependency_cruiser(tmp_path, {})[1] == "ok" and seen["cmd"][-1] == "src"
    assert ajs.run_dependency_cruiser(tmp_path, {"js_config": "nope.cjs"}) == (
        1,
        "missing:nope.cjs",
    )
    monkeypatch.setattr(ajs.shutil, "which", lambda n: None)
    assert ajs.run_dependency_cruiser(tmp_path, {}) == (1, "npx-missing")
    assert ajs.run_eslint_boundaries(tmp_path, {}) == (1, "npx-missing")
    monkeypatch.setattr(ajs.shutil, "which", lambda n: "/bin/npx")

    class R3:
        returncode, stdout, stderr = 3, "a", "b"

    monkeypatch.setattr(ajs.subprocess, "run", lambda cmd, **k: seen.update(cmd=list(cmd)) or R3())
    assert ajs.run_eslint_boundaries(tmp_path, {"eslint_config": "e.js"}) == (3, "ab")
    assert seen["cmd"] == ["/bin/npx", "--yes", "eslint", ".", "--config", "e.js"]
    assert ajs.run_eslint_boundaries(tmp_path, {"eslint_boundaries_command": ["eslint", "."]}) == (
        3,
        "ab",
    )
    assert seen["cmd"] == ["eslint", "."]
    seen.clear()
    monkeypatch.setattr(
        ajs.subprocess, "run", lambda cmd, **k: seen.update(cwd=k.get("cwd")) or R3()
    )
    assert ajs.run_eslint_boundaries(tmp_path, {"eslint_boundaries_command": ["e"]})[0] == 3
    assert seen["cwd"] is tmp_path

    class R0:
        returncode, stdout, stderr = 0, None, None

    monkeypatch.setattr(ajs.subprocess, "run", lambda *a, **k: R0())
    assert ajs._run(["x"], tmp_path) == (0, "")

    class Rlong:
        returncode, stdout, stderr = 0, "x" * 2500, ""

    monkeypatch.setattr(ajs.subprocess, "run", lambda *a, **k: Rlong())
    assert len(ajs._run(["x"], tmp_path)[1]) == 2000
