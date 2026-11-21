from __future__ import annotations

from pathlib import Path

from agentized.paths import DEFAULT_CONTEXT
from agentized.process_control import (
    DOC,
    PROCESS_FILENAME,
    _diff_insertions,
    _match,
    active_claims,
    claim_check,
    default_process_config,
    is_agent_session,
    load_process_config,
    path_needs_claim,
    process_path,
    size_check,
)
from agentized.process_control import (
    main as process_main,
)
from agentized.process_size import DOC as SIZE_DOC
from agentized.process_size import diff_insertions as size_diff_insertions


def _task(root: Path, task_id: str, *, status: str, claim: str) -> None:
    tasks = root / "context" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / f"{task_id}.md").write_text(
        f"# {task_id} — t\n\nстатус: {status}\nтеги:\nродитель:\nclaim: {claim}\n",
        encoding="utf-8",
    )


def test_path_globs_and_excludes(tmp_path: Path):
    cfg = default_process_config()
    watched = [
        path_needs_claim("runtime/agentized/x.py", cfg),
        path_needs_claim("context/tasks/AGE-1.md", cfg),
        path_needs_claim("README.md", cfg),
        path_needs_claim(".github/workflows/ci.yml", cfg, root=tmp_path),
    ]
    # True, False, False, True — equality to a concrete tuple (not bool-only oracles).
    assert watched == [True, False, False, True]
    # absolute path under workspace → relative match
    abs_runtime = tmp_path / "runtime" / "x.py"
    abs_runtime.parent.mkdir(parents=True)
    abs_runtime.write_text("x\n", encoding="utf-8")
    assert path_needs_claim(str(abs_runtime), cfg, root=tmp_path) is True


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
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 100, "warn_at_pct": 50}\n',
        encoding="utf-8",
    )

    def fake_diff(root, base_ref):
        return 60

    monkeypatch.setattr("agentized.process_control.diff_insertions", fake_diff)
    result = size_check(tmp_path)
    assert result["level"] == "warn"
    assert result["ok"] is True
    assert result["insertions"] == 60
    assert result["limit"] == 100
    assert result["warn_at"] == 50
    assert result["base"] == "origin/main"
    assert result["message"] == (
        "process-control: PR size 60 insertions vs origin/main "
        "(warn ≥50 = 50.0% of 100; over >100). See docs/process-control.md."
    )
    assert "over >100" in result["message"]
    assert "over ≥100" not in result["message"]
    assert DOC == SIZE_DOC == "docs/process-control.md"

    monkeypatch.setattr("agentized.process_control.diff_insertions", lambda *_: 120)
    over = size_check(tmp_path)
    assert over["level"] == "over"
    assert over["ok"] is False
    assert over["insertions"] == 120
    assert over["message"] == (
        "process-control: PR size 120 insertions vs origin/main "
        "(warn ≥50 = 50.0% of 100; over >100). See docs/process-control.md."
    )
    assert "over >100" in over["message"]
    assert "over ≥100" not in over["message"]

    # Inclusive limit: at exact limit → warn; +1 → over.
    monkeypatch.setattr("agentized.process_control.diff_insertions", lambda *_: 100)
    at_limit = size_check(tmp_path, base_ref="upstream/main")
    assert at_limit["level"] == "warn"
    assert at_limit["ok"] is True
    assert at_limit["base"] == "upstream/main"
    assert at_limit["message"] == (
        "process-control: PR size 100 insertions vs upstream/main "
        "(warn ≥50 = 50.0% of 100; over >100). See docs/process-control.md."
    )
    monkeypatch.setattr("agentized.process_control.diff_insertions", lambda *_: 101)
    over_by_one = size_check(tmp_path, base_ref="upstream/main")
    assert over_by_one["level"] == "over"
    assert over_by_one["ok"] is False
    assert over_by_one["insertions"] == 101
    assert over_by_one["message"] == (
        "process-control: PR size 101 insertions vs upstream/main "
        "(warn ≥50 = 50.0% of 100; over >100). See docs/process-control.md."
    )


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
    # Empty globs → every path needs a claim (concrete map, not int()/bool() cast).
    assert {
        "anything.py": path_needs_claim("anything.py", cfg),
        "README.md": path_needs_claim("README.md", cfg),
        "x": path_needs_claim("x", cfg),
    } == {"anything.py": True, "README.md": True, "x": True}


def test_load_bad_json_raises(tmp_path: Path):
    import pytest

    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_process_config(tmp_path)


def test_size_cli_bad_json_nonzero(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agentized.process_control.find_repo_root", lambda: tmp_path)
    (tmp_path / "context").mkdir(exist_ok=True)
    (tmp_path / "context" / "process-control.json").write_text("{bad", encoding="utf-8")
    assert process_main(["size", "--context", "context"]) == 1


def test_size_cli_git_error_nonzero(tmp_path: Path, monkeypatch):
    from agentized import process_size as ps

    class FakeProc:
        returncode = 128
        stdout = ""
        stderr = "fatal: bad"

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: FakeProc())
    monkeypatch.setattr("agentized.process_control.find_repo_root", lambda: tmp_path)
    (tmp_path / "context").mkdir(exist_ok=True)
    assert process_main(["size", "--context", "context"]) == 1


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


def test_active_claims_keeps_claim_when_parent_empty(tmp_path: Path):
    """Empty `родитель:` must not eat `claim:` — active_claims still lists the owner."""
    from agentized.process_control import active_claims

    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / "T-261116-emp.md").write_text(
        "# T-261116-emp — t\n\nстатус: in-progress\nтеги: AGE-43\nродитель:\nclaim: worker-x\n",
        encoding="utf-8",
    )
    claims = active_claims(tmp_path)
    assert claims == ["T-261116-emp (worker-x, in-progress)"]


def test_normalize_and_extract_paths(tmp_path: Path):
    from agentized.hook_common import context_rel, extract_paths, normalize_repo_path

    assert extract_paths({"file_path": "./.github/workflows/ci.yml"}) == [
        ".github/workflows/ci.yml"
    ]
    # Must not turn ".github/..." into "github/..." (old lstrip("./") bug).
    assert extract_paths({"file_path": ".github/workflows/ci.yml"}) == [".github/workflows/ci.yml"]
    # Strip only "./" prefixes; keep absolute paths intact for normalize_repo_path.
    assert extract_paths({"file_path": "././runtime/x.py"}) == ["runtime/x.py"]
    abs_keep = str(tmp_path / "runtime" / "kept.py")
    assert extract_paths({"file_path": abs_keep}) == [abs_keep.replace("\\", "/")]
    # tool_input edits/files dicts must keep real paths (not None).
    assert extract_paths(
        {"tool_input": {"edits": [{"path": "runtime/a.py"}, {"file_path": "runtime/b.py"}]}}
    ) == ["runtime/a.py", "runtime/b.py"]
    # Dedup after ./ strip.
    assert extract_paths({"file_path": "./x.py", "path": "x.py"}) == ["x.py"]

    abs_p = tmp_path / "runtime" / "x.py"
    abs_p.parent.mkdir(parents=True)
    abs_p.write_text("x\n", encoding="utf-8")
    assert normalize_repo_path(str(abs_p), tmp_path) == "runtime/x.py"
    assert normalize_repo_path("./.github/a.yml", tmp_path) == ".github/a.yml"
    assert normalize_repo_path("././docs/QUALITY.md", tmp_path) == "docs/QUALITY.md"
    assert normalize_repo_path("", tmp_path) == ""
    # Absolute path string that starts with resolved root prefix (non-Path.is_absolute branch).
    root_s = str(tmp_path.resolve()).replace("\\", "/")
    assert normalize_repo_path(f"{root_s}/runtime/x.py", tmp_path) == "runtime/x.py"
    # Outside the workspace → absolute form (no bogus strip of leading "/").
    outside = Path("/tmp/agentized-outside-claim-test.py")
    out_norm = normalize_repo_path(str(outside), tmp_path)
    assert out_norm.startswith("/")
    assert "agentized-outside-claim-test.py" in out_norm
    # Backslash separators normalize to "/".
    assert normalize_repo_path(r"runtime\agentized\x.py", tmp_path) == "runtime/agentized/x.py"
    # context_rel reads connect state key "context".
    state_dir = tmp_path / ".agentized"
    state_dir.mkdir(parents=True)
    (state_dir / "connect.json").write_text('{"context":"custom"}\n', encoding="utf-8")
    assert context_rel(tmp_path) == "custom"

    # claim_check with custom context + absolute path
    custom = tmp_path / "custom"
    (custom / "tasks").mkdir(parents=True)
    (custom / "process-control.json").write_text(
        '{"claim_required": true, "claim_mode_agent": "refuse"}\n', encoding="utf-8"
    )
    (custom / "tasks" / "T-261113-xyz.md").write_text(
        "# T-261113-xyz — t\n\nстатус: in-progress\nтеги:\nродитель:\nclaim: alice\n",
        encoding="utf-8",
    )
    r = claim_check(
        tmp_path,
        [str(abs_p)],
        context_rel="custom",
        env={"CURSOR_AGENT": "1"},
    )
    assert r["ok"] is True
    assert "T-261113-xyz" in r["message"]
    # Absolute path outside workspace must not skip claim when another path needs it.
    r2 = claim_check(
        tmp_path,
        [str(outside), str(abs_p)],
        context_rel="custom",
        env={"CURSOR_AGENT": "1"},
    )
    assert r2["ok"] is True


def test_default_process_config_exact_contract():
    cfg = default_process_config()
    assert cfg["version"] == 1
    assert cfg["reviewable_lines"] == 1500
    assert cfg["warn_at_pct"] == 75
    assert cfg["claim_required"] is True
    assert cfg["claim_mode_agent"] == "refuse"
    assert cfg["claim_mode_local"] == "warn"
    assert cfg["edit_path_globs"] == [
        "runtime/**",
        "scripts/**",
        "packages/**",
        "templates/**",
        "tests/**",
        ".githooks/**",
        ".github/**",
        "bin/**",
    ]
    assert cfg["edit_path_excludes"] == [
        "context/tasks/**",
        "context/leases/**",
        "context/digests/**",
        "**/__pycache__/**",
        ".artifacts/**",
    ]
    # Fresh copy each call (mutants that return shared mutable singleton).
    cfg2 = default_process_config()
    cfg["reviewable_lines"] = 1
    assert cfg2["reviewable_lines"] == 1500
    assert PROCESS_FILENAME == "process-control.json"
    assert DEFAULT_CONTEXT == "context"


def test_process_path_and_load_uses_context(tmp_path: Path):
    assert process_path(tmp_path) == tmp_path / "context" / "process-control.json"
    assert process_path(tmp_path, "ctx2") == tmp_path / "ctx2" / "process-control.json"
    (tmp_path / "ctx2").mkdir()
    (tmp_path / "ctx2" / "process-control.json").write_text(
        '{"reviewable_lines": 42}\n', encoding="utf-8"
    )
    cfg = load_process_config(tmp_path, "ctx2")
    assert cfg["reviewable_lines"] == 42
    assert cfg["warn_at_pct"] == 75


def test_is_agent_session_sources(monkeypatch):
    monkeypatch.delenv("CURSOR_AGENT", raising=False)
    monkeypatch.delenv("CURSOR_CODE_REMOTE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.delenv("CODEX_CI", raising=False)
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.delenv("AI_AGENT", raising=False)
    monkeypatch.delenv("AGENT", raising=False)
    assert {
        "empty": is_agent_session({}),
        "cursor": is_agent_session({"CURSOR_AGENT": "1"}),
        "claude": is_agent_session({"CLAUDE_CODE_REMOTE": "true"}),
        "codex": is_agent_session({"CODEX_CI": "1"}),
        "opencode": is_agent_session({"OPENCODE": "1"}),
    } == {
        "empty": False,
        "cursor": True,
        "claude": True,
        "codex": True,
        "opencode": True,
    }
    # env=None reads os.environ
    monkeypatch.setenv("CURSOR_AGENT", "1")
    assert [is_agent_session(None)] == [True]
    monkeypatch.delenv("CURSOR_AGENT", raising=False)
    assert [is_agent_session(None)] == [False]


def test_match_backslash_and_patterns():
    assert {
        "bs": _match(r"runtime\x.py", ["runtime/**"]),
        "docs": _match("docs/a.md", ["runtime/**"]),
        "empty": _match("a.py", []),
        "glob": _match("a.py", ["*.py", "b"]),
    } == {"bs": True, "docs": False, "empty": False, "glob": True}


def test_path_needs_claim_strip_dot_slash_and_excludes():
    cfg = default_process_config()
    assert {
        "dot_runtime": path_needs_claim("./runtime/x.py", cfg),
        "dot_scripts": path_needs_claim("././scripts/y.sh", cfg),
        "leases": path_needs_claim("context/leases/x.md", cfg),
        "digests": path_needs_claim("context/digests/d.md", cfg),
        "pycache": path_needs_claim("pkg/__pycache__/z.py", cfg),
        "artifacts": path_needs_claim(".artifacts/out.txt", cfg),
        "tests": path_needs_claim("tests/unit/t.py", cfg),
        "bin": path_needs_claim("bin/agentized", cfg),
        "templates": path_needs_claim("templates/x", cfg),
        "packages": path_needs_claim("packages/x", cfg),
        "githooks": path_needs_claim(".githooks/pre-push", cfg),
    } == {
        "dot_runtime": True,
        "dot_scripts": True,
        "leases": False,
        "digests": False,
        "pycache": False,
        "artifacts": False,
        "tests": True,
        "bin": True,
        "templates": True,
        "packages": True,
        "githooks": True,
    }
    # exclude wins over glob
    cfg2 = default_process_config()
    cfg2["edit_path_excludes"] = ["runtime/**"]
    assert [path_needs_claim("runtime/x.py", cfg2)] == [False]


def test_active_claims_filters_and_preference(tmp_path: Path):
    assert active_claims(tmp_path) == []
    (tmp_path / "context" / "tasks").mkdir(parents=True)
    assert active_claims(tmp_path) == []
    _task(tmp_path, "T-261121-done1", status="done", claim="z")
    _task(tmp_path, "T-261121-usco", status="in-progress", claim="_empty")
    _task(tmp_path, "T-261121-blnk", status="in-progress", claim="   ")
    _task(tmp_path, "T-261121-open", status="open", claim="bob")
    _task(tmp_path, "T-261121-blok", status="blocked", claim="cara")
    _task(tmp_path, "T-261121-prog", status="in-progress", claim="alice")
    # Preferred: only in-progress with real claim.
    assert active_claims(tmp_path) == ["T-261121-prog (alice, in-progress)"]
    # Without in-progress preferred, open/blocked with claims appear.
    (tmp_path / "context" / "tasks" / "T-261121-prog.md").unlink()
    assert set(active_claims(tmp_path)) == {
        "T-261121-open (bob, open)",
        "T-261121-blok (cara, blocked)",
    }


def test_claim_check_message_modes(tmp_path: Path):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "process-control.json").write_text(
        '{"claim_required": true, "claim_mode_agent": "refuse", "claim_mode_local": "warn"}\n',
        encoding="utf-8",
    )
    local = claim_check(tmp_path, ["runtime/x.py"], env={})
    assert local == {
        "ok": True,
        "mode": "warn",
        "message": (
            "WARN. process-control: no in-progress task claim before code edits. "
            "Claim first: `./bin/agentized claim <TASK_ID> --owner <you>`. "
            f"See {DOC}."
        ),
        "paths": ["runtime/x.py"],
    }
    refused = claim_check(tmp_path, ["runtime/x.py"], env={"CURSOR_AGENT": "1"})
    assert refused["ok"] is False
    assert refused["mode"] == "refuse"
    assert refused["message"].startswith("REFUSED. process-control: no in-progress task claim")
    assert refused["message"].endswith(f"See {DOC}.")
    assert refused["paths"] == ["runtime/x.py"]
    # Missing mode keys → warn default for local / refuse path still agent via cfg default.
    (tmp_path / "context" / "process-control.json").write_text(
        '{"claim_required": true}\n', encoding="utf-8"
    )
    _task(tmp_path, "T-261121-ok01", status="in-progress", claim="owner-1")
    ok = claim_check(tmp_path, ["runtime/x.py"], env={"CURSOR_AGENT": "1"})
    assert ok["ok"] is True
    assert ok["mode"] == "ok"
    assert ok["claims"] == ["T-261121-ok01 (owner-1, in-progress)"]
    assert ok["message"] == "process-control: claim OK — T-261121-ok01 (owner-1, in-progress)"
    (tmp_path / "context" / "process-control.json").write_text(
        '{"claim_required": false}\n', encoding="utf-8"
    )
    disabled = claim_check(tmp_path, ["runtime/x.py"], env={"CURSOR_AGENT": "1"})
    assert disabled == {"ok": True, "mode": "disabled", "message": ""}
    (tmp_path / "context" / "process-control.json").write_text(
        '{"claim_required": true}\n', encoding="utf-8"
    )
    skip = claim_check(tmp_path, ["README.md"], env={"CURSOR_AGENT": "1"})
    assert skip == {"ok": True, "mode": "skip", "message": ""}


def test_size_check_defaults_process_base_and_errors(tmp_path: Path, monkeypatch):
    (tmp_path / "context").mkdir()
    # Missing keys → defaults 1500 / 75
    (tmp_path / "context" / "process-control.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("agentized.process_control.diff_insertions", lambda *_: 10)
    monkeypatch.delenv("PROCESS_BASE", raising=False)
    ok = size_check(tmp_path)
    assert ok["limit"] == 1500
    assert ok["warn_at"] == 1125  # int(1500 * 75 / 100)
    assert ok["level"] == "ok"
    assert ok["ok"] is True
    assert ok["message"] == (
        "process-control: PR size 10 insertions vs origin/main "
        "(warn ≥1125 = 75.0% of 1500; over >1500). See docs/process-control.md."
    )
    monkeypatch.setenv("PROCESS_BASE", "origin/develop")
    via_env = size_check(tmp_path)
    assert via_env["base"] == "origin/develop"
    assert "vs origin/develop" in via_env["message"]
    assert "over >1500" in via_env["message"]

    # AGE-40: reviewable_lines/warn_at_pct 0 fail closed (no silent coerce via `or`).
    (tmp_path / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 0, "warn_at_pct": 0}\n', encoding="utf-8"
    )
    bad_zero = size_check(tmp_path)
    assert bad_zero["ok"] is False
    assert bad_zero["level"] == "error"
    assert "reviewable_lines" in bad_zero["message"]

    # Restore valid config so boom-git exercises diff_insertions, not field validation.
    (tmp_path / "context" / "process-control.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "agentized.process_control.diff_insertions",
        lambda *_: (_ for _ in ()).throw(RuntimeError("boom-git")),
    )
    err = size_check(tmp_path)
    assert err == {
        "ok": False,
        "level": "error",
        "insertions": 0,
        "limit": 0,
        "warn_at": 0,
        "base": "origin/develop",
        "message": "boom-git",
    }
    monkeypatch.setattr(
        "agentized.process_control.load_process_config",
        lambda *_: (_ for _ in ()).throw(ValueError("bad-json")),
    )
    err2 = size_check(tmp_path, base_ref="main")
    assert err2["ok"] is False
    assert err2["level"] == "error"
    assert err2["base"] == "main"
    assert err2["message"] == "bad-json"
    assert err2["insertions"] == 0
    assert err2["limit"] == 0
    assert err2["warn_at"] == 0


def test_main_size_claim_usage_streams(tmp_path: Path, monkeypatch, capsys):
    for key in (
        "CURSOR_AGENT",
        "CURSOR_CODE_REMOTE",
        "CLAUDE_CODE_REMOTE",
        "CODEX_CI",
        "CODEX_THREAD_ID",
        "CODEX_SESSION_ID",
        "CODEX_SANDBOX",
        "OPENCODE",
        "AI_AGENT",
        "AGENT",
        "PI_CODING_AGENT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("agentized.process_control.find_repo_root", lambda: tmp_path)
    (tmp_path / "context").mkdir(exist_ok=True)
    (tmp_path / "context" / "process-control.json").write_text(
        '{"reviewable_lines": 50, "warn_at_pct": 50, "claim_required": true, '
        '"claim_mode_agent": "refuse", "claim_mode_local": "warn"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("agentized.process_control.diff_insertions", lambda *_: 10)
    assert process_main(["size", "--context", "context"]) == 0
    out = capsys.readouterr()
    assert "over >50" in out.out
    assert out.err == ""

    monkeypatch.setattr("agentized.process_control.diff_insertions", lambda *_: 60)
    assert process_main(["size"]) == 1
    out = capsys.readouterr()
    assert "over >50" in out.err
    assert out.out == ""

    assert process_main(["claim", "--context", "context"]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("WARN. process-control:")
    assert (
        process_main(["claim", "--context", "context", "--paths", "runtime/a.py", "runtime/b.py"])
        == 0
    )
    out = capsys.readouterr()
    assert "WARN." in out.out

    _task(tmp_path, "T-261121-cli1", status="in-progress", claim="cli-owner")
    monkeypatch.setenv("CURSOR_AGENT", "1")
    assert process_main(["claim", "--paths", "runtime/a.py"]) == 0
    out = capsys.readouterr()
    assert "claim OK — T-261121-cli1 (cli-owner, in-progress)" in out.out

    (tmp_path / "context" / "tasks" / "T-261121-cli1.md").unlink()
    assert process_main(["claim", "--paths", "runtime/a.py"]) == 1
    out = capsys.readouterr()
    assert out.err.startswith("REFUSED.")
    assert out.out == ""

    assert process_main([]) == 2
    out = capsys.readouterr()
    assert out.err == "usage: process_control.py size|claim [--context CTX] [--paths ...]\n"
    assert out.out == ""
    assert process_main(["nope"]) == 2
    # Alias stays wired to process_size.diff_insertions.
    assert _diff_insertions is size_diff_insertions
    assert callable(_diff_insertions)


def test_path_needs_claim_backslash_without_root():
    """Kill replace('\\\\','/') mutants on the no-root branch.

    `.\\` must become `./` before the ``./`` strip; otherwise `_match`'s own
    replace leaves a leading ``./`` and ``runtime/**`` fails to match.
    """
    cfg = default_process_config()
    assert {
        "runtime_bs": path_needs_claim(r"runtime\agentized\x.py", cfg),
        "docs_bs": path_needs_claim(r"docs\readme.md", cfg),
        "dot_runtime": path_needs_claim(r".\runtime\agentized\x.py", cfg),
        "dot_docs": path_needs_claim(r".\docs\readme.md", cfg),
    } == {
        "runtime_bs": True,
        "docs_bs": False,
        "dot_runtime": True,
        "dot_docs": False,
    }


def test_active_claims_strips_preferred_and_skips_underscore_prefix(tmp_path: Path):
    _task(tmp_path, "T-261121-pad1", status="in-progress", claim="  alice  ")
    _task(tmp_path, "T-261121-hid1", status="in-progress", claim="_hidden")
    assert active_claims(tmp_path) == ["T-261121-pad1 (alice, in-progress)"]


def test_claim_check_default_required_and_join_and_mode_key(tmp_path: Path, monkeypatch):
    # claim_required missing → default True (enabled); False default would disable.
    monkeypatch.setattr(
        "agentized.process_control.load_process_config",
        lambda root, context_rel="context": {},
    )
    enabled = claim_check(tmp_path, ["runtime/x.py"], env={})
    assert enabled["mode"] == "warn"
    assert enabled["ok"] is True

    # Local refuse via claim_mode_local key (wrong key → warn).
    monkeypatch.setattr(
        "agentized.process_control.load_process_config",
        lambda root, context_rel="context": {
            "claim_required": True,
            "claim_mode_local": "refuse",
        },
    )
    local_refuse = claim_check(tmp_path, ["runtime/x.py"], env={})
    assert local_refuse["mode"] == "refuse"
    assert local_refuse["ok"] is False

    # Missing mode → default warn string exposed as mode.
    monkeypatch.setattr(
        "agentized.process_control.load_process_config",
        lambda root, context_rel="context": {"claim_required": True},
    )
    missing_mode = claim_check(tmp_path, ["runtime/x.py"], env={})
    assert missing_mode["mode"] == "warn"

    # Non-refuse custom mode still reports mode "warn" (not the raw config token).
    monkeypatch.setattr(
        "agentized.process_control.load_process_config",
        lambda root, context_rel="context": {
            "claim_required": True,
            "claim_mode_local": "soft",
        },
    )
    soft = claim_check(tmp_path, ["runtime/x.py"], env={})
    assert soft["ok"] is True
    assert soft["mode"] == "warn"
    assert soft["message"].startswith("WARN.")

    # Explicit null / empty mode → warn (not refuse); missing key same.
    monkeypatch.setattr(
        "agentized.process_control.load_process_config",
        lambda root, context_rel="context": {
            "claim_required": True,
            "claim_mode_local": None,
        },
    )
    null_mode = claim_check(tmp_path, ["runtime/x.py"], env={})
    assert null_mode["ok"] is True
    assert null_mode["mode"] == "warn"
    monkeypatch.setattr(
        "agentized.process_control.load_process_config",
        lambda root, context_rel="context": {
            "claim_required": True,
            "claim_mode_local": "",
        },
    )
    empty_mode = claim_check(tmp_path, ["runtime/x.py"], env={})
    assert empty_mode["ok"] is True
    assert empty_mode["mode"] == "warn"

    # Multi-claim join uses ", " not another separator.
    monkeypatch.setattr(
        "agentized.process_control.load_process_config",
        lambda root, context_rel="context": {
            "claim_required": True,
            "edit_path_globs": ["runtime/**"],
            "edit_path_excludes": [],
        },
    )
    _task(tmp_path, "T-261121-j01", status="in-progress", claim="a")
    _task(tmp_path, "T-261121-j02", status="in-progress", claim="b")
    joined = claim_check(tmp_path, ["runtime/x.py"], env={"CURSOR_AGENT": "1"})
    assert joined["mode"] == "ok"
    assert joined["message"] == (
        "process-control: claim OK — T-261121-j01 (a, in-progress), T-261121-j02 (b, in-progress)"
    )
    assert ", " in joined["message"]
    assert "XX, XX" not in joined["message"]


def test_claim_and_size_pass_context_rel(tmp_path: Path, monkeypatch):
    calls: list[tuple] = []

    def fake_load(root, context_rel="context"):
        calls.append(("load", context_rel))
        return {
            "claim_required": True,
            "claim_mode_agent": "refuse",
            "claim_mode_local": "warn",
            "edit_path_globs": ["runtime/**"],
            "edit_path_excludes": [],
            "reviewable_lines": 10,
            "warn_at_pct": 50,
        }

    monkeypatch.setattr("agentized.process_control.load_process_config", fake_load)
    monkeypatch.setattr("agentized.process_control.diff_insertions", lambda *_: 1)
    claim_check(tmp_path, ["runtime/x.py"], context_rel="otherctx", env={})
    size_check(tmp_path, context_rel="sizectx")
    assert calls == [("load", "otherctx"), ("load", "sizectx")]


def test_main_argv_none_context_paths_and_newlines(tmp_path: Path, monkeypatch, capsys):
    for key in (
        "CURSOR_AGENT",
        "CURSOR_CODE_REMOTE",
        "CLAUDE_CODE_REMOTE",
        "CODEX_CI",
        "OPENCODE",
        "AI_AGENT",
        "AGENT",
        "PROCESS_BASE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("agentized.process_control.find_repo_root", lambda: tmp_path)
    (tmp_path / "ctxa").mkdir()
    (tmp_path / "ctxa" / "process-control.json").write_text(
        '{"reviewable_lines": 5, "warn_at_pct": 50, "claim_required": true, '
        '"claim_mode_local": "warn", "claim_mode_agent": "refuse"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("agentized.process_control.diff_insertions", lambda *_: 1)

    # argv is None → sys.argv[1:]
    monkeypatch.setattr(
        "agentized.process_control.sys.argv",
        ["process_control.py", "size", "--context", "ctxa"],
    )
    assert process_main(None) == 0
    out = capsys.readouterr()
    assert out.out.endswith("\n")
    assert out.out == (
        "process-control: PR size 1 insertions vs origin/main "
        "(warn ≥2 = 50.0% of 5; over >5). See docs/process-control.md.\n"
    )
    assert "XX\nXX" not in out.out

    # --context must be honored (wrong flag → default context missing → defaults).
    (tmp_path / "context").mkdir(exist_ok=True)
    assert process_main(["size", "--context", "ctxa"]) == 0
    out = capsys.readouterr()
    assert "over >5" in out.out

    seen: list[tuple] = []

    def capture_claim(root, paths, *, context_rel="context", env=None):
        seen.append((list(paths), context_rel))
        return {"ok": True, "mode": "warn", "message": "WARN. captured", "paths": paths}

    monkeypatch.setattr("agentized.process_control.claim_check", capture_claim)
    assert process_main(["claim", "--context", "ctxa"]) == 0
    out = capsys.readouterr()
    assert out.out == "WARN. captured\n"
    assert seen[-1] == (["runtime/agentized/x.py"], "ctxa")

    assert (
        process_main(["claim", "--context", "ctxa", "--paths", "runtime/a.py", "runtime/b.py"]) == 0
    )
    out = capsys.readouterr()
    assert out.out == "WARN. captured\n"
    assert seen[-1] == (["runtime/a.py", "runtime/b.py"], "ctxa")
    # Empty --paths list after flag still passes empty list (not default).
    assert process_main(["claim", "--paths"]) == 0
    assert seen[-1][0] == []
