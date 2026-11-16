"""AGE-38: status_guard fail-closed decisions + single shared source."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from agentized.hook_common import extract_paths
from agentized import status_guard as sg


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists() and (parent / "packages").is_dir():
            return parent
    return here.parents[2]


REPO = _repo_root()
SHARED_GUARD = REPO / "packages" / "shared" / "hooks" / "scripts" / "status_guard.py"
OPEN = "# T\n\nстатус: open\n\nЦенность: test\n"
ALLOW_PRE = {
    "permission": "allow",
    "continue": True,
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
    },
}


def _deny(event: str, msg: str) -> dict:
    return {
        "permission": "deny",
        "continue": False,
        "agent_message": msg,
        "additional_context": msg,
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
        },
        "hookEventName": event,
        "systemMessage": msg,
    }


@dataclass(frozen=True)
class _GateResult:
    ok: bool
    errors: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        return "; ".join(self.errors)


def _fake_gates(*, fail_message: str | None = None, record: list | None = None):
    def extract_status(text: str | None) -> str | None:
        if not text:
            return None
        for line in text.splitlines():
            if line.lower().startswith("статус:"):
                return line.split(":", 1)[1].strip()
        return None

    def validate_task_text(
        text: str,
        *,
        old_status: str | None = None,
        require_value: bool,
        check_transition: bool,
    ) -> _GateResult:
        if record is not None:
            record.append(
                {
                    "require_value": require_value,
                    "check_transition": check_transition,
                    "old_status": old_status,
                    "text": text,
                }
            )
        if require_value is not True:
            return _GateResult(False, ("require_value must be True",))
        if fail_message:
            return _GateResult(False, (fail_message,))
        st = extract_status(text)
        if check_transition is True and old_status == "open" and st == "done":
            return _GateResult(False, ("illegal transition open → done",))
        if require_value is True and "Ценность:" not in text:
            return _GateResult(False, ("missing value",))
        return _GateResult(True)

    return types.SimpleNamespace(
        extract_status=extract_status,
        validate_task_text=validate_task_text,
    )


def _mk_task(tmp_path: Path, name: str, body: str = OPEN) -> Path:
    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    path = tasks / name
    path.write_text(body, encoding="utf-8")
    return path


def test_shared_source_only_no_harness_copies():
    assert SHARED_GUARD.is_file()
    copies = [
        REPO / ".cursor" / "hooks" / "status_guard.py",
        REPO / ".claude" / "hooks" / "status_guard.py",
        REPO / ".codex" / "hooks" / "status_guard.py",
        REPO / "context" / "hooks" / "scripts" / "status_guard.py",
        REPO / "packages" / "agentized-cursor" / "scripts" / "status_guard.py",
        REPO / "packages" / "agentized-claude" / "scripts" / "status_guard.py",
        REPO / "packages" / "agentized-codex" / "scripts" / "status_guard.py",
    ]
    present = [p for p in copies if p.is_file()]
    assert present == [], f"unexpected committed copies: {present}"


def test_parse_hook_stdin_variants():
    payload, err = sg.parse_hook_stdin("")
    assert err is None and payload == {}
    payload, err = sg.parse_hook_stdin('{"hook_event_name":"PreToolUse"}')
    assert err is None and payload == {"hook_event_name": "PreToolUse"}
    payload, err = sg.parse_hook_stdin("{not-json")
    assert payload is None
    assert err == "[status-guard] REFUSED: broken stdin (invalid JSON)"
    payload, err = sg.parse_hook_stdin("[1,2]")
    assert payload is None
    assert err == "[status-guard] REFUSED: unknown payload (JSON must be an object)"


def test_decide_from_stdin_denies_bad(tmp_path: Path):
    assert sg.decide_from_stdin(
        "{bad", root=tmp_path, context_rel="context", extract_paths=extract_paths
    ) == _deny("PreToolUse", "[status-guard] REFUSED: broken stdin (invalid JSON)")
    assert sg.decide_from_stdin(
        '"just-a-string"', root=tmp_path, context_rel="context", extract_paths=extract_paths
    ) == _deny(
        "PreToolUse",
        "[status-guard] REFUSED: unknown payload (JSON must be an object)",
    )


def test_is_task_path_variants():
    positives = [
        "context/tasks/T-261116-aaa.md",
        "./context/tasks/T-261116-aaa.md",
        "././tasks/T-261116-aaa.md",
        "context/./tasks/T-261116-aaa.md",
        "tasks/T-261116-aaa.md",
        "tasks/T-x.md",
        "context\\tasks\\T-261116-aaa.md",
        "/abs/proj/context/tasks/T-261116-aaa.md",
        "/other/workspace/tasks/T-261116-aaa.md",
        "context//tasks/T-261116-aaa.md",
        "context/./tasks/T-x.md",
    ]
    negatives = [
        "runtime/agentized/x.py",
        "context/tasks/README.md",
        "context/tasks/TEMPLATE.md",
        "docs/guide.md",
        "T-261116-aaa.md",
        "",
        ".",
        "tasks/T.md",
        "tasks/T-.md",
        "tasks/T-x.txt",
        "tasks/X-261116-aaa.md",
    ]
    assert [p for p in positives if sg.is_task_path(p)] == positives
    assert [p for p in negatives if sg.is_task_path(p)] == []


def test_is_after_edit():
    yes = ["afterFileEdit", "After_File_Edit", "PostToolUse"]
    no = ["PreToolUse", "", None]
    assert [e for e in yes if sg.is_after_edit(e)] == yes  # type: ignore[arg-type]
    assert [e for e in no if sg.is_after_edit(e)] == []  # type: ignore[arg-type]


def test_apply_edits_coverage():
    base = "hello world world"
    assert sg.apply_edits(base, {"old_string": "world", "new_string": "there"}) == "hello there world"
    assert sg.apply_edits(base, {"old_string": "missing", "new_string": "x"}) is None
    assert sg.apply_edits(base, {"old_string": "world", "new_string": 1}) is None
    assert sg.apply_edits(base, {"old_string": 1, "new_string": "there"}) is None
    base2 = "aa bb cc"
    merged = sg.apply_edits(
        base2,
        {
            "edits": [
                {"old_string": "aa", "new_string": "AA"},
                "skip-me",
                {"old_string": 1, "new_string": 2},
                {"old_string": "cc", "new_string": 99},
                {"old": "cc", "content": "CC"},
                {"old_string": "bb", "new_string": "BB"},
            ]
        },
    )
    assert merged == "AA BB cc"
    assert sg.apply_edits(base2, {"edits": []}) is None
    assert sg.apply_edits(base2, {"edits": [{"old_string": "nope", "new_string": "x"}]}) is None
    assert sg.apply_edits(base2, {}) is None
    assert sg.apply_edits(base2, {"edits": "not-a-list"}) is None
    assert sg.apply_edits(base2, {"edits": [{"old_string": "aa"}]}) is None
    assert sg.apply_edits(base2, {"edits": [{"old_string": "aa", "new_string": "AA"}]}) == "AA bb cc"
    assert sg.apply_edits("xx xx", {"edits": [{"old_string": "xx", "new_string": "YY"}]}) == "YY xx"
    assert (
        sg.apply_edits(
            base2,
            {
                "edits": [
                    {"old_string": "aa", "new_string": "AA"},
                    {"old_string": "missing", "new_string": "x"},
                ]
            },
        )
        is None
    )


def test_full_write_and_tool_input_and_responses():
    assert sg.full_write_text({"content": "  x  "}) == "  x  "
    assert sg.full_write_text({"contents": "y"}) == "y"
    assert sg.full_write_text({"body": "z"}) == "z"
    assert sg.full_write_text({"text": "t"}) == "t"
    assert sg.full_write_text({"content": "   "}) is None
    assert sg.full_write_text({}) is None
    assert sg.tool_input_from_payload({"tool_input": {"a": 1}}) == {"a": 1}
    assert sg.tool_input_from_payload({"toolInput": {"b": 2}}) == {"b": 2}
    assert sg.tool_input_from_payload({"input": {"c": 3}}) == {"c": 3}
    assert sg.tool_input_from_payload({"input": "x"}) == {}
    assert sg.tool_input_from_payload({}) == {}
    assert sg.allow_response("PreToolUse") == ALLOW_PRE
    assert sg.deny_response("PreToolUse", "nope") == _deny("PreToolUse", "nope")
    assert sg.hook_event_name({}) == "PreToolUse"
    assert sg.hook_event_name({"hookEventName": "X"}) == "X"
    assert sg.hook_event_name({"hook_event_name": "Y"}) == "Y"


def test_evaluate_allows_non_task(tmp_path: Path):
    out = sg.evaluate_status_guard(
        {"hook_event_name": "PreToolUse", "tool_input": {"file_path": "runtime/x.py", "content": "x"}},
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates_loader=lambda: (_ for _ in ()).throw(RuntimeError("should not load")),
    )
    assert out == ALLOW_PRE


def test_evaluate_denies_bad_context_rel(tmp_path: Path):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_input": {"file_path": "runtime/x.py", "content": "x"},
    }
    msg = "[status-guard] REFUSED: context_rel must be a non-empty string"
    assert sg.evaluate_status_guard(
        payload, root=tmp_path, context_rel="", extract_paths=extract_paths
    ) == _deny("PreToolUse", msg)
    assert sg.evaluate_status_guard(
        payload, root=tmp_path, context_rel=None, extract_paths=extract_paths  # type: ignore[arg-type]
    ) == _deny("PreToolUse", msg)


def test_evaluate_denies_import_failure_on_task(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-imp.md", "статус: open\nЦенность: v\n")
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {
                "file_path": "context/tasks/T-261116-imp.md",
                "content": "статус: blocked\nЦенность: v\n",
            },
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates_loader=lambda: (_ for _ in ()).throw(ImportError("no gates")),
    )
    assert out["permission"] == "deny"
    assert out["hookEventName"] == "PreToolUse"
    assert out["agent_message"] == (
        "[status-guard] REFUSED: status_gates unavailable: no gates"
    )


def test_evaluate_denies_missing_validate_api(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-api.md", "статус: open\nЦенность: v\n")
    body = "статус: open\nЦенность: v\n"
    tool = {"file_path": "context/tasks/T-261116-api.md", "content": body}
    msg = "[status-guard] REFUSED: status_gates missing validate API"
    assert (
        sg.evaluate_status_guard(
            {"hook_event_name": "PreToolUse", "tool_input": tool},
            root=tmp_path,
            context_rel="context",
            extract_paths=extract_paths,
            gates=types.SimpleNamespace(),
        )
        == _deny("PreToolUse", msg)
    )
    assert (
        sg.evaluate_status_guard(
            {"hook_event_name": "PreToolUse", "tool_input": tool},
            root=tmp_path,
            context_rel="context",
            extract_paths=extract_paths,
            gates=types.SimpleNamespace(extract_status=lambda t: "open"),
        )
        == _deny("PreToolUse", msg)
    )


def test_evaluate_blocks_illegal_transition(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-bad.md")
    bad = "# T\n\nстатус: done\n\nЦенность: test\n"
    calls: list = []
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "context/tasks/T-261116-bad.md", "content": bad},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(record=calls),
    )
    assert out == _deny(
        "PreToolUse",
        "[status-guard] REFUSED: T-261116-bad.md: illegal transition open → done",
    )
    assert calls == [
        {
            "require_value": True,
            "check_transition": True,
            "old_status": "open",
            "text": bad,
        }
    ]


def test_evaluate_allows_valid_write(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-ok.md")
    good = "# T\n\nстатус: blocked\n\nЦенность: test\n"
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "context/tasks/T-261116-ok.md", "content": good},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out == ALLOW_PRE


def test_evaluate_denies_edit_mismatch(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-ed.md")
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {
                "file_path": "context/tasks/T-261116-ed.md",
                "old_string": "NO MATCH",
                "new_string": "# T\n\nстатус: in-progress\n\nЦенность: test\n",
            },
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out == _deny(
        "PreToolUse",
        "[status-guard] REFUSED: T-261116-ed.md: cannot apply Edit onto task file "
        "(old_string mismatch or missing file)",
    )


def test_evaluate_allows_progress_edit(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-pr.md", OPEN + "\n## Цель\n\nx\n")
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {
                "file_path": "context/tasks/T-261116-pr.md",
                "old_string": "## Цель\n\nx\n",
                "new_string": "## Цель\n\nx\n\n## Progress\n\n- note\n",
            },
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out == ALLOW_PRE


def test_evaluate_input_alias_paths(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-in.md")
    tool = {"file_path": "context/tasks/T-261116-in.md", "content": OPEN}
    out = sg.evaluate_status_guard(
        {"hookEventName": "PreToolUse", "input": tool},
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out == ALLOW_PRE
    out2 = sg.evaluate_status_guard(
        {"hook_event_name": "PreToolUse", "toolInput": tool},
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out2 == ALLOW_PRE
    # Illegal transition via `input` only — kills tool_input re-inject key mutants
    # (without re-inject, extract_paths misses `input` → silent allow).
    bad = "# T\n\nстатус: done\n\nЦенность: test\n"
    out3 = sg.evaluate_status_guard(
        {
            "hookEventName": "PreToolUse",
            "input": {"file_path": "context/tasks/T-261116-in.md", "content": bad},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out3 == _deny(
        "PreToolUse",
        "[status-guard] REFUSED: T-261116-in.md: illegal transition open → done",
    )


def test_candidate_after_edit_uses_git(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    task = _mk_task(tmp_path, "T-261116-git.md")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    task.write_text("# T\n\nстатус: done\n\nЦенность: test\n", encoding="utf-8")
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "afterFileEdit",
            "tool_input": {"file_path": "context/tasks/T-261116-git.md"},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out == _deny(
        "afterFileEdit",
        "[status-guard] REFUSED: T-261116-git.md: illegal transition open → done",
    )


def test_git_blob_missing_and_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert (sg.git_blob(tmp_path, "nope.md") or "<missing>") == "<missing>"

    def boom(*_a, **_k):
        raise OSError("no git")

    monkeypatch.setattr(sg.subprocess, "run", boom)
    assert (sg.git_blob(tmp_path, "x") or "<oserror>") == "<oserror>"

    def bad_git(*_a, **_k):
        return types.SimpleNamespace(returncode=1, stdout="stale")

    monkeypatch.setattr(sg.subprocess, "run", bad_git)
    assert (sg.git_blob(tmp_path, "x") or "<nonzero>") == "<nonzero>"


def test_hook_script_denies_broken_stdin(tmp_path: Path):
    env = {**dict(os.environ), "CLAUDE_PROJECT_DIR": str(tmp_path)}
    (tmp_path / "runtime").symlink_to(REPO / "runtime")
    proc = subprocess.run(
        [sys.executable, str(SHARED_GUARD)],
        input="{bad",
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=env,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == _deny(
        "PreToolUse", "[status-guard] REFUSED: broken stdin (invalid JSON)"
    )


def test_connect_pins_status_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from agentized.connect import connect

    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (ctx / "tasks").mkdir()
    (ctx / "leases").mkdir()
    monkeypatch.chdir(tmp_path)
    connect(tmp_path, context_rel="context", harnesses=["cursor", "claude", "codex"], coverage_pct=80)
    shared = REPO / "packages" / "shared" / "hooks" / "scripts" / "status_guard.py"
    assert shared.is_file()
    assert (ctx / "hooks" / "scripts" / "status_guard.py").is_file()
    assert (tmp_path / ".cursor" / "hooks" / "status_guard.py").is_file()
    assert (tmp_path / ".claude" / "hooks" / "status_guard.py").is_file()
    assert (tmp_path / ".codex" / "hooks" / "status_guard.py").is_file()
    pg = (tmp_path / ".cursor" / "hooks" / "process_guard.py").read_text(encoding="utf-8")
    assert "decide_from_stdin" in pg and "status_guard" in pg


def test_load_status_gates_import_error(monkeypatch: pytest.MonkeyPatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "agentized.status_gates" or (
            name == "agentized" and args and args[2] and "status_gates" in args[2]
        ):
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError):
        sg.load_status_gates()


def test_load_status_gates_success(monkeypatch: pytest.MonkeyPatch):
    fake = types.ModuleType("agentized.status_gates")
    fake.extract_status = lambda text: "open"  # type: ignore[attr-defined]
    fake.validate_task_text = lambda *a, **k: _GateResult(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agentized.status_gates", fake)
    import agentized as pkg

    monkeypatch.setattr(pkg, "status_gates", fake, raising=False)
    loaded = sg.load_status_gates()
    assert loaded.extract_status("статус: open\n") == "open"
    assert loaded.validate_task_text("x").errors == ()


def test_candidate_and_old_write_and_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = _mk_task(tmp_path, "T-1.md", "old\n")
    cand, old = sg.candidate_and_old(
        path,
        root=tmp_path,
        rel="context/tasks/T-1.md",
        tool_input={"content": "new body"},
        event="PreToolUse",
    )
    assert cand == "new body" and old == "old\n"
    missing = tmp_path / "context" / "tasks" / "T-missing.md"
    cand2, old2 = sg.candidate_and_old(
        missing, root=tmp_path, rel="context/tasks/T-missing.md", tool_input={}, event="PreToolUse"
    )
    assert cand2 is None and old2 is None
    calls: list[tuple] = []

    def fake_blob(root, rel):
        calls.append((root, rel))
        return "BLOB"

    monkeypatch.setattr(sg, "git_blob", fake_blob)
    cand3, old3 = sg.candidate_and_old(
        missing, root=tmp_path, rel="context/tasks/T-missing.md", tool_input={}, event="afterFileEdit"
    )
    assert cand3 == "" and old3 == "BLOB"
    assert calls == [(tmp_path, "context/tasks/T-missing.md")]


def test_evaluate_after_edit_missing_empty_candidate(tmp_path: Path):
    (tmp_path / "context" / "tasks").mkdir(parents=True)
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "afterFileEdit",
            "tool_input": {"file_path": "context/tasks/T-261116-gone.md"},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out == {
        "permission": "allow",
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "afterFileEdit",
            "permissionDecision": "allow",
        },
    }


def test_evaluate_absolute_path_outside_root(tmp_path: Path):
    other = Path("/tmp") / f"age38-{tmp_path.name}" / "tasks"
    other.mkdir(parents=True, exist_ok=True)
    task = other / "T-261116-out.md"
    task.write_text(OPEN, encoding="utf-8")
    try:
        out = sg.evaluate_status_guard(
            {
                "hook_event_name": "PreToolUse",
                "tool_input": {"file_path": str(task), "content": OPEN},
            },
            root=tmp_path,
            context_rel="context",
            extract_paths=extract_paths,
            gates=_fake_gates(),
        )
        assert out == ALLOW_PRE
    finally:
        task.unlink(missing_ok=True)
        other.rmdir()
        other.parent.rmdir()


def test_evaluate_empty_candidate_without_edit_keys_allows(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-empty.md")
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "context/tasks/T-261116-empty.md"},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out == ALLOW_PRE


def test_decide_from_stdin_valid_object_allows_non_task(tmp_path: Path):
    out = sg.decide_from_stdin(
        json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_input": {"file_path": "runtime/x.py", "content": "x"},
            }
        ),
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
    )
    assert out == ALLOW_PRE


def test_decide_from_stdin_passes_gates(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-pass.md")
    body = "# T\n\nстатус: blocked\n\nЦенность: test\n"
    out = sg.decide_from_stdin(
        json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_input": {"file_path": "context/tasks/T-261116-pass.md", "content": body},
            }
        ),
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out == ALLOW_PRE


def test_evaluate_uses_gates_loader_when_gates_none(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-ld.md")
    body = "# T\n\nстатус: blocked\n\nЦенность: test\n"
    loaded = {"n": 0}

    def loader():
        loaded["n"] += 1
        return _fake_gates()

    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "context/tasks/T-261116-ld.md", "content": body},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=None,
        gates_loader=loader,
    )
    assert out == ALLOW_PRE and loaded["n"] == 1


def test_evaluate_validation_message_fallback(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-fb.md")

    class WeirdResult:
        ok = False

    gates = types.SimpleNamespace(
        extract_status=lambda text: "open",
        validate_task_text=lambda *_a, **_k: WeirdResult(),
    )
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "context/tasks/T-261116-fb.md", "content": OPEN},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=gates,
    )
    assert out == _deny("PreToolUse", "[status-guard] REFUSED: T-261116-fb.md: invalid task")


def test_evaluate_result_without_ok_attr_denies(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-nok.md")

    class NoOk:
        message = "nope"

    gates = types.SimpleNamespace(
        extract_status=lambda text: "open",
        validate_task_text=lambda *_a, **_k: NoOk(),
    )
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "context/tasks/T-261116-nok.md", "content": OPEN},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=gates,
    )
    assert out == _deny("PreToolUse", "[status-guard] REFUSED: T-261116-nok.md: nope")


def test_evaluate_whitespace_candidate_with_edits_denies(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-ws.md", "keep\n")
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {
                "file_path": "context/tasks/T-261116-ws.md",
                "edits": [{"old_string": "keep\n", "new_string": "   \n"}],
            },
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out == _deny(
        "PreToolUse",
        "[status-guard] REFUSED: T-261116-ws.md: cannot apply Edit onto task file "
        "(old_string mismatch or missing file)",
    )


def test_evaluate_defaults_to_load_status_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _mk_task(tmp_path, "T-261116-def.md")
    body = "# T\n\nстатус: blocked\n\nЦенность: test\n"
    calls: list[int] = []
    monkeypatch.setattr(sg, "load_status_gates", lambda: calls.append(1) or _fake_gates())
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "context/tasks/T-261116-def.md", "content": body},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=None,
        gates_loader=None,
    )
    assert out == ALLOW_PRE and calls == [1]


def test_decide_from_stdin_passes_gates_loader(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-gl.md")
    body = "# T\n\nстатус: blocked\n\nЦенность: test\n"
    loaded = {"n": 0}

    def loader():
        loaded["n"] += 1
        return _fake_gates()

    out = sg.decide_from_stdin(
        json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_input": {"file_path": "context/tasks/T-261116-gl.md", "content": body},
            }
        ),
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=None,
        gates_loader=loader,
    )
    assert out == ALLOW_PRE and loaded["n"] == 1


def test_evaluate_two_task_errors_join_and_continue(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-a.md")
    _mk_task(tmp_path, "T-261116-b.md")
    bad = "# T\n\nстатус: done\n\nЦенность: test\n"

    def extract_paths_multi(payload: dict) -> list[str]:
        del payload
        return ["context/tasks/T-261116-a.md", "context/tasks/T-261116-b.md"]

    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "context/tasks/T-261116-a.md", "content": bad},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths_multi,
        gates=_fake_gates(),
    )
    assert out == _deny(
        "PreToolUse",
        "[status-guard] REFUSED: T-261116-a.md: illegal transition open → done; "
        "T-261116-b.md: illegal transition open → done",
    )
    out2 = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {
                "file_path": "context/tasks/T-261116-a.md",
                "old_string": "NOPE",
                "new_string": bad,
            },
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths_multi,
        gates=_fake_gates(),
    )
    assert out2["permission"] == "deny"
    assert "T-261116-a.md: cannot apply Edit" in out2["agent_message"]
    assert "T-261116-b.md: cannot apply Edit" in out2["agent_message"]
    assert "; " in out2["agent_message"]


def test_evaluate_skips_extract_when_no_old_text(tmp_path: Path):
    (tmp_path / "context" / "tasks").mkdir(parents=True)
    extracts: list = []

    def extract_status(text):
        extracts.append(text)
        return "open" if text is None else None

    def validate_task_text(text, *, old_status=None, require_value, check_transition):
        assert require_value is True and check_transition is False and old_status is None
        return _GateResult(True)

    gates = types.SimpleNamespace(extract_status=extract_status, validate_task_text=validate_task_text)
    out = sg.evaluate_status_guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "context/tasks/T-261116-new.md", "content": OPEN},
        },
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=gates,
    )
    assert out == ALLOW_PRE and extracts == []


def test_evaluate_outside_root_after_edit_records_rel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    other = Path("/tmp") / f"age38-rel-{tmp_path.name}" / "tasks"
    other.mkdir(parents=True, exist_ok=True)
    task = other / "T-261116-rel.md"
    task.write_text(OPEN, encoding="utf-8")
    recorded: list[str] = []
    monkeypatch.setattr(sg, "git_blob", lambda root, rel: recorded.append(rel) or OPEN)
    try:
        out = sg.evaluate_status_guard(
            {"hook_event_name": "afterFileEdit", "tool_input": {"file_path": str(task)}},
            root=tmp_path,
            context_rel="context",
            extract_paths=extract_paths,
            gates=_fake_gates(),
        )
        assert out["permission"] == "allow" and recorded == [task.as_posix()]
    finally:
        task.unlink(missing_ok=True)
        other.rmdir()
        other.parent.rmdir()
