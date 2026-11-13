from __future__ import annotations

from pathlib import Path

from agentized.process_control import (
    claim_check,
    default_process_config,
    load_process_config,
    main as process_main,
    path_needs_claim,
    size_check,
)


def _task(root: Path, task_id: str, *, status: str, claim: str) -> None:
    tasks = root / "context" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / f"{task_id}.md").write_text(
        f"# {task_id} — t\n\nстатус: {status}\nтеги:\nродитель:\nclaim: {claim}\n",
        encoding="utf-8",
    )


def test_path_globs_and_excludes():
    cfg = default_process_config()
    assert path_needs_claim("runtime/agentized/x.py", cfg) is True
    assert path_needs_claim("context/tasks/AGE-1.md", cfg) is False
    assert path_needs_claim("README.md", cfg) is False


def test_claim_ok_and_refuse(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text(
        '{"claim_required": true, "claim_mode_agent": "refuse", "claim_mode_local": "warn"}\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_AGENT", raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    # local warn without claim
    r = claim_check(tmp_path, ["runtime/x.py"], env={})
    assert r["ok"] is True
    assert r["mode"] == "warn"
    # agent refuse
    r2 = claim_check(tmp_path, ["runtime/x.py"], env={"CURSOR_AGENT": "1"})
    assert r2["ok"] is False
    assert r2["mode"] == "refuse"
    _task(tmp_path, "T-261113-abc", status="in-progress", claim="alice")
    r3 = claim_check(tmp_path, ["runtime/x.py"], env={"CURSOR_AGENT": "1"})
    assert r3["ok"] is True
    assert "T-261113-abc" in r3["message"]


def test_load_defaults_when_missing(tmp_path: Path):
    cfg = load_process_config(tmp_path)
    assert cfg["reviewable_lines"] == 1500
    assert cfg["warn_at_pct"] == 75


def test_size_check_levels(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 100, "warn_at_pct": 50}\n',
        encoding="utf-8",
    )

    def fake_diff(root, base_ref):  # noqa: ARG001
        return 60

    monkeypatch.setattr("agentized.process_control._diff_insertions", fake_diff)
    result = size_check(tmp_path)
    assert result["level"] == "warn"
    assert result["ok"] is True

    monkeypatch.setattr("agentized.process_control._diff_insertions", lambda *_: 120)
    over = size_check(tmp_path)
    assert over["level"] == "over"
    assert over["ok"] is False


def test_claim_disabled_and_skip(tmp_path: Path):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text(
        '{"claim_required": false}\n', encoding="utf-8"
    )
    assert claim_check(tmp_path, ["runtime/x.py"])["mode"] == "disabled"
    (tmp_path / "context" / "process-control.json").write_text(
        '{"claim_required": true}\n', encoding="utf-8"
    )
    assert claim_check(tmp_path, ["context/tasks/x.md"])["mode"] == "skip"


def test_empty_globs_need_claim():
    cfg = default_process_config()
    cfg["edit_path_globs"] = []
    assert path_needs_claim("anything.py", cfg) is True


def test_load_bad_json(tmp_path: Path):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text("{nope", encoding="utf-8")
    cfg = load_process_config(tmp_path)
    assert cfg["reviewable_lines"] == 1500


def test_diff_insertions_and_cli(tmp_path: Path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "f.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "c"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agentized.process_control.find_repo_root", lambda: tmp_path)
    (tmp_path / "context").mkdir(exist_ok=True)
    assert process_main(["size", "--context", "context"]) in {0, 1}
    assert process_main(["claim", "--context", "context", "--paths", "runtime/x.py"]) in {0, 1}
    assert process_main([]) == 2


def test_active_claims_open_fallback(tmp_path: Path):
    from agentized.process_control import active_claims

    _task(tmp_path, "T-261113-zzz", status="open", claim="bob")
    claims = active_claims(tmp_path)
    assert any("T-261113-zzz" in c for c in claims)
