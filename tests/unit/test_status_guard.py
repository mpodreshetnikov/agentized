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

_UNB = (
    "cannot build candidate text for task file "
    "(empty/whitespace write or unknown tool shape)"
)
_EDIT = "cannot apply Edit onto task file (old_string mismatch or missing file)"


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists() and (parent / "packages").is_dir():
            return parent
    return here.parents[2]


REPO = _repo_root()
SHARED_GUARD = REPO / "packages/shared/hooks/scripts/status_guard.py"
SHARED_PG = REPO / "packages/shared/hooks/scripts/process_guard.py"
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
    """Mirror agentized.status_gates API (#25)."""

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
        extract_status=extract_status, validate_task_text=validate_task_text
    )


def _mk_task(tmp_path: Path, name: str, body: str = OPEN) -> Path:
    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    path = tasks / name
    path.write_text(body, encoding="utf-8")
    return path


def _eval(tmp_path: Path, tool: dict, *, gates=None, gates_loader=None, extract=extract_paths):
    return sg.evaluate_status_guard(
        {"hook_event_name": "PreToolUse", "tool_input": tool},
        root=tmp_path,
        context_rel="context",
        extract_paths=extract,
        gates=gates if gates is not None else (_fake_gates() if gates_loader is None else None),
        gates_loader=gates_loader,
    )


def _isolated_hook(tmp_path: Path, src: Path) -> Path:
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    boot = src.parent / "_bootstrap.py"
    (hook_dir / "_bootstrap.py").write_text(boot.read_text(encoding="utf-8"), encoding="utf-8")
    return hook_dir / src.name


def _iso_env(tmp_path: Path) -> dict:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "PYTHONPATH": "",
        "AGENTIZED_ROOT": "",
    }


def test_shared_source_only_no_harness_copies():
    assert SHARED_GUARD.is_file()
    copies = [
        REPO / p
        for p in (
            ".cursor/hooks/status_guard.py",
            ".claude/hooks/status_guard.py",
            ".codex/hooks/status_guard.py",
            "context/hooks/scripts/status_guard.py",
            "packages/agentized-cursor/scripts/status_guard.py",
            "packages/agentized-claude/scripts/status_guard.py",
            "packages/agentized-codex/scripts/status_guard.py",
        )
    ]
    assert [p for p in copies if p.is_file()] == []


def test_parse_and_decide_stdin(tmp_path: Path):
    assert sg.parse_hook_stdin("") == ({}, None)
    assert sg.parse_hook_stdin('{"a":1}') == ({"a": 1}, None)
    p, e = sg.parse_hook_stdin("{bad")
    assert p is None and e == "[status-guard] REFUSED: broken stdin (invalid JSON)"
    p, e = sg.parse_hook_stdin("[1]")
    assert p is None and e == "[status-guard] REFUSED: unknown payload (JSON must be an object)"
    assert sg.decide_from_stdin(
        "{bad", root=tmp_path, context_rel="context", extract_paths=extract_paths
    ) == _deny("PreToolUse", "[status-guard] REFUSED: broken stdin (invalid JSON)")
    assert sg.decide_from_stdin(
        '"x"', root=tmp_path, context_rel="context", extract_paths=extract_paths
    ) == _deny("PreToolUse", "[status-guard] REFUSED: unknown payload (JSON must be an object)")
    assert (
        sg.decide_from_stdin(
            json.dumps({"tool_input": {"file_path": "runtime/x.py", "content": "x"}}),
            root=tmp_path,
            context_rel="context",
            extract_paths=extract_paths,
        )
        == ALLOW_PRE
    )


def test_is_task_path_and_helpers():
    yes = [
        "context/tasks/T-261116-aaa.md",
        "./context/tasks/T-261116-aaa.md",
        "tasks/T-x.md",
        "context\\tasks\\T-261116-aaa.md",
        "/abs/proj/context/tasks/T-261116-aaa.md",
        "context//tasks/T-261116-aaa.md",
    ]
    no = [
        "runtime/agentized/x.py",
        "context/tasks/README.md",
        "T-261116-aaa.md",
        "",
        "tasks/T.md",
        "tasks/T-.md",
        "tasks/T-x.txt",
    ]
    assert [p for p in yes if sg.is_task_path(p)] == yes
    assert [p for p in no if sg.is_task_path(p)] == []
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


def test_apply_edits_coverage():
    base = "hello world world"
    assert sg.apply_edits(base, {"old_string": "world", "new_string": "there"}) == "hello there world"
    assert sg.apply_edits(base, {"old_string": "missing", "new_string": "x"}) is None
    assert sg.apply_edits(base, {"old_string": "world", "new_string": 1}) is None
    assert sg.apply_edits(base, {"old_string": 1, "new_string": "there"}) is None
    base2 = "aa bb cc"
    assert (
        sg.apply_edits(
            base2,
            {
                "edits": [
                    {"old_string": "aa", "new_string": "AA"},
                    "skip",
                    {"old_string": 1, "new_string": 2},
                    {"old_string": "cc", "new_string": 99},
                    {"old": "cc", "content": "CC"},
                    {"old_string": "bb", "new_string": "BB"},
                ]
            },
        )
        == "AA BB cc"
    )
    assert sg.apply_edits(base2, {"edits": []}) is None
    assert sg.apply_edits(base2, {"edits": [{"old_string": "nope", "new_string": "x"}]}) is None
    assert sg.apply_edits(base2, {}) is None
    assert sg.apply_edits(base2, {"edits": "x"}) is None
    assert sg.apply_edits(base2, {"edits": [{"old_string": "aa"}]}) is None
    assert sg.apply_edits(base2, {"edits": [{"old_string": "aa", "new_string": "AA"}]}) == "AA bb cc"
    assert sg.apply_edits("xx xx", {"edits": [{"old_string": "xx", "new_string": "YY"}]}) == "YY xx"
    assert (
        sg.apply_edits(
            base2,
            {"edits": [{"old_string": "aa", "new_string": "AA"}, {"old_string": "missing", "new_string": "x"}]},
        )
        is None
    )


def test_evaluate_core_paths(tmp_path: Path):
    assert (
        _eval(tmp_path, {"file_path": "runtime/x.py", "content": "x"}, gates_loader=lambda: (_ for _ in ()).throw(RuntimeError("x")))
        == ALLOW_PRE
    )
    msg = "[status-guard] REFUSED: context_rel must be a non-empty string"
    payload = {"hook_event_name": "PreToolUse", "tool_input": {"file_path": "runtime/x.py", "content": "x"}}
    assert sg.evaluate_status_guard(payload, root=tmp_path, context_rel="", extract_paths=extract_paths) == _deny(
        "PreToolUse", msg
    )
    assert sg.evaluate_status_guard(
        payload, root=tmp_path, context_rel=None, extract_paths=extract_paths  # type: ignore[arg-type]
    ) == _deny("PreToolUse", msg)

    _mk_task(tmp_path, "T-261116-imp.md")
    out = _eval(
        tmp_path,
        {"file_path": "context/tasks/T-261116-imp.md", "content": OPEN},
        gates_loader=lambda: (_ for _ in ()).throw(ImportError("no gates")),
    )
    assert out == _deny("PreToolUse", "[status-guard] REFUSED: status_gates unavailable: no gates")

    tool = {"file_path": "context/tasks/T-261116-api.md", "content": OPEN}
    _mk_task(tmp_path, "T-261116-api.md")
    api = "[status-guard] REFUSED: status_gates missing validate API"
    assert _eval(tmp_path, tool, gates=types.SimpleNamespace()) == _deny("PreToolUse", api)
    assert _eval(
        tmp_path, tool, gates=types.SimpleNamespace(extract_status=lambda t: "open")
    ) == _deny("PreToolUse", api)


def test_evaluate_transitions_and_writes(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-bad.md")
    bad = "# T\n\nстатус: done\n\nЦенность: test\n"
    calls: list = []
    out = _eval(
        tmp_path,
        {"file_path": "context/tasks/T-261116-bad.md", "content": bad},
        gates=_fake_gates(record=calls),
    )
    assert out == _deny(
        "PreToolUse",
        "[status-guard] REFUSED: T-261116-bad.md: illegal transition open → done",
    )
    assert calls[0]["old_status"] == "open" and calls[0]["require_value"] is True

    _mk_task(tmp_path, "T-261116-ok.md")
    good = "# T\n\nстатус: blocked\n\nЦенность: test\n"
    assert _eval(tmp_path, {"file_path": "context/tasks/T-261116-ok.md", "content": good}) == ALLOW_PRE

    _mk_task(tmp_path, "T-261116-ed.md")
    assert _eval(
        tmp_path,
        {
            "file_path": "context/tasks/T-261116-ed.md",
            "old_string": "NO MATCH",
            "new_string": good,
        },
    ) == _deny("PreToolUse", f"[status-guard] REFUSED: T-261116-ed.md: {_EDIT}")

    _mk_task(tmp_path, "T-261116-pr.md", OPEN + "\n## Цель\n\nx\n")
    assert (
        _eval(
            tmp_path,
            {
                "file_path": "context/tasks/T-261116-pr.md",
                "old_string": "## Цель\n\nx\n",
                "new_string": "## Цель\n\nx\n\n## Progress\n\n- note\n",
            },
        )
        == ALLOW_PRE
    )


def test_evaluate_aliases_and_empty_and_apply_patch(tmp_path: Path):
    _mk_task(tmp_path, "T-261116-in.md")
    tool = {"file_path": "context/tasks/T-261116-in.md", "content": OPEN}
    assert (
        sg.evaluate_status_guard(
            {"hookEventName": "PreToolUse", "input": tool},
            root=tmp_path,
            context_rel="context",
            extract_paths=extract_paths,
            gates=_fake_gates(),
        )
        == ALLOW_PRE
    )
    assert (
        sg.evaluate_status_guard(
            {"hook_event_name": "PreToolUse", "toolInput": tool},
            root=tmp_path,
            context_rel="context",
            extract_paths=extract_paths,
            gates=_fake_gates(),
        )
        == ALLOW_PRE
    )
    bad = "# T\n\nстатус: done\n\nЦенность: test\n"
    out = sg.evaluate_status_guard(
        {"hookEventName": "PreToolUse", "input": {"file_path": "context/tasks/T-261116-in.md", "content": bad}},
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
        gates=_fake_gates(),
    )
    assert out["permission"] == "deny" and "illegal transition" in out["agent_message"]

    _mk_task(tmp_path, "T-261116-empty.md")
    for tool in (
        {"file_path": "context/tasks/T-261116-empty.md", "content": ""},
        {"file_path": "context/tasks/T-261116-empty.md", "content": "   \n"},
        {"file_path": "context/tasks/T-261116-empty.md"},
    ):
        assert _eval(tmp_path, tool) == _deny(
            "PreToolUse", f"[status-guard] REFUSED: T-261116-empty.md: {_UNB}"
        )

    _mk_task(tmp_path, "T-261116-ap.md")
    cmd = "apply_patch <<'EOF'\n*** Update File: context/tasks/T-261116-ap.md\n@@\n-x\n+y\nEOF"
    out = _eval(tmp_path, {"command": cmd})
    assert out["permission"] == "deny" and _UNB in out["agent_message"]


def test_hook_scripts_and_connect(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
):
    # Isolated trees MUST NOT be under a path that contains runtime/ (bootstrap walks parents).
    iso_root = tmp_path_factory.mktemp("age38-iso")
    iso = _isolated_hook(iso_root / "sg", SHARED_GUARD)
    proc = subprocess.run(
        [sys.executable, str(iso)],
        input='{"tool_input":{"file_path":"x.py"}}',
        text=True,
        capture_output=True,
        cwd=iso_root / "sg",
        env=_iso_env(iso_root / "sg"),
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["permission"] == "deny" and "import failure" in out["agent_message"]

    iso_pg = _isolated_hook(iso_root / "pg", SHARED_PG)
    proc = subprocess.run(
        [sys.executable, str(iso_pg)],
        input=json.dumps({"tool_input": {"file_path": "runtime/x.py", "content": "x"}}),
        text=True,
        capture_output=True,
        cwd=iso_root / "pg",
        env=_iso_env(iso_root / "pg"),
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["permission"] == "deny" and "import failure" in out["agent_message"]

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

    from agentized.connect import connect

    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (ctx / "tasks").mkdir()
    (ctx / "leases").mkdir()
    monkeypatch.chdir(tmp_path)
    connect(tmp_path, context_rel="ctx", harnesses=["cursor", "claude", "codex"], coverage_pct=80)
    assert (ctx / "hooks/scripts/status_guard.py").is_file()
    assert (tmp_path / ".cursor/hooks/status_guard.py").is_file()
    pg = (tmp_path / ".cursor/hooks/process_guard.py").read_text(encoding="utf-8")
    assert "decide_from_stdin" in pg and "import failure" in pg

    src = SHARED_PG.read_bytes()
    for rel in (
        ".cursor/hooks/process_guard.py",
        ".claude/hooks/process_guard.py",
        ".codex/hooks/process_guard.py",
        "context/hooks/scripts/process_guard.py",
    ):
        assert (REPO / rel).read_bytes() == src


def test_load_status_gates_import_error(monkeypatch: pytest.MonkeyPatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "agentized.status_gates" or (
            name == "agentized" and a and a[2] and "status_gates" in a[2]
        ):
            raise ImportError("missing")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(ImportError):
        sg.load_status_gates()


def test_load_status_gates_success(monkeypatch: pytest.MonkeyPatch):
    fake_mod = types.ModuleType("agentized.status_gates")
    fake_mod.extract_status = lambda text: "open"  # type: ignore[attr-defined]
    fake_mod.validate_task_text = lambda *a, **k: _GateResult(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agentized.status_gates", fake_mod)
    import agentized as pkg

    monkeypatch.setattr(pkg, "status_gates", fake_mod, raising=False)
    loaded = sg.load_status_gates()
    assert loaded.extract_status("статус: open\n") == "open"


def test_candidate_utf8_and_path_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import locale

    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "ascii")
    body = "# T\n\nстатус: open\n\nЦенность: тест-юникод\n"
    path = _mk_task(tmp_path, "T-261116-utf.md", body)
    cand, old = sg.candidate_and_old(
        path,
        root=str(tmp_path),
        rel="context/tasks/T-261116-utf.md",
        tool_input={"old_string": "тест-юникод", "new_string": "тест-ok"},
        event="PreToolUse",
    )
    assert old == body and cand is not None and "тест-ok" in cand
    cand2, old2 = sg.candidate_and_old(
        path, root=tmp_path, rel="x", tool_input={"content": "new"}, event="PreToolUse"
    )
    assert cand2 == "new" and old2 == body
    cand3, _ = sg.candidate_and_old(
        path, root=tmp_path, rel="x", tool_input={"content": "  "}, event="PreToolUse"
    )
    assert cand3 is None
    missing = tmp_path / "context/tasks/T-missing.md"
    assert sg.candidate_and_old(
        missing, root=tmp_path, rel="x", tool_input={}, event="PreToolUse"
    ) == (None, None)


def test_evaluate_edge_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    other = Path("/tmp") / f"age38-{tmp_path.name}" / "tasks"
    other.mkdir(parents=True, exist_ok=True)
    task = other / "T-261116-out.md"
    task.write_text(OPEN, encoding="utf-8")
    try:
        assert (
            _eval(tmp_path, {"file_path": str(task), "content": OPEN}) == ALLOW_PRE
        )
    finally:
        task.unlink(missing_ok=True)
        other.rmdir()
        other.parent.rmdir()

    _mk_task(tmp_path, "T-261116-ws.md", "keep\n")
    assert _eval(
        tmp_path,
        {
            "file_path": "context/tasks/T-261116-ws.md",
            "edits": [{"old_string": "keep\n", "new_string": "   \n"}],
        },
    ) == _deny("PreToolUse", f"[status-guard] REFUSED: T-261116-ws.md: {_EDIT}")

    _mk_task(tmp_path, "T-261116-ld.md")
    body = "# T\n\nстатус: blocked\n\nЦенность: test\n"
    loaded = {"n": 0}

    def loader():
        loaded["n"] += 1
        return _fake_gates()

    assert (
        _eval(
            tmp_path,
            {"file_path": "context/tasks/T-261116-ld.md", "content": body},
            gates_loader=loader,
        )
        == ALLOW_PRE
        and loaded["n"] == 1
    )

    class Weird:
        ok = False

    assert _eval(
        tmp_path,
        {"file_path": "context/tasks/T-261116-ld.md", "content": OPEN},
        gates=types.SimpleNamespace(
            extract_status=lambda t: "open", validate_task_text=lambda *_a, **_k: Weird()
        ),
    ) == _deny("PreToolUse", "[status-guard] REFUSED: T-261116-ld.md: invalid task")

    class NoOk:
        message = "nope"

    assert _eval(
        tmp_path,
        {"file_path": "context/tasks/T-261116-ld.md", "content": OPEN},
        gates=types.SimpleNamespace(
            extract_status=lambda t: "open", validate_task_text=lambda *_a, **_k: NoOk()
        ),
    ) == _deny("PreToolUse", "[status-guard] REFUSED: T-261116-ld.md: nope")

    calls: list[int] = []
    monkeypatch.setattr(sg, "load_status_gates", lambda: calls.append(1) or _fake_gates())
    assert (
        sg.evaluate_status_guard(
            {
                "hook_event_name": "PreToolUse",
                "tool_input": {"file_path": "context/tasks/T-261116-ld.md", "content": body},
            },
            root=tmp_path,
            context_rel="context",
            extract_paths=extract_paths,
            gates=None,
            gates_loader=None,
        )
        == ALLOW_PRE
        and calls == [1]
    )

    assert (
        sg.decide_from_stdin(
            json.dumps(
                {
                    "tool_input": {"file_path": "context/tasks/T-261116-ld.md", "content": body},
                }
            ),
            root=tmp_path,
            context_rel="context",
            extract_paths=extract_paths,
            gates_loader=loader,
        )
        == ALLOW_PRE
    )


def test_multi_task_and_new_file_and_catchall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _mk_task(tmp_path, "T-261116-a.md")
    _mk_task(tmp_path, "T-261116-b.md")
    bad = "# T\n\nстатус: done\n\nЦенность: test\n"

    def multi(payload: dict) -> list[str]:
        del payload
        return ["context/tasks/T-261116-a.md", "context/tasks/T-261116-b.md"]

    out = _eval(
        tmp_path,
        {"file_path": "context/tasks/T-261116-a.md", "content": bad},
        extract=multi,
    )
    assert "T-261116-a.md: illegal" in out["agent_message"]
    assert "T-261116-b.md: illegal" in out["agent_message"]
    out2 = _eval(
        tmp_path,
        {"file_path": "context/tasks/T-261116-a.md", "old_string": "NOPE", "new_string": bad},
        extract=multi,
    )
    assert "cannot apply Edit" in out2["agent_message"] and "; " in out2["agent_message"]

    (tmp_path / "context/tasks").mkdir(parents=True, exist_ok=True)
    extracts: list = []

    def extract_status(text):
        extracts.append(text)
        return None

    def validate_task_text(text, *, old_status=None, require_value, check_transition):
        assert require_value is True and check_transition is False and old_status is None
        return _GateResult(True)

    assert (
        _eval(
            tmp_path,
            {"file_path": "context/tasks/T-261116-new.md", "content": OPEN},
            gates=types.SimpleNamespace(
                extract_status=extract_status, validate_task_text=validate_task_text
            ),
        )
        == ALLOW_PRE
        and extracts == []
    )

    def boom(*_a, **_k):
        raise PermissionError("locked")

    monkeypatch.setattr(sg, "evaluate_status_guard", boom)
    out = sg.decide_from_stdin(
        json.dumps({"tool_input": {"file_path": "context/tasks/T-261116-a.md", "content": OPEN}}),
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
    )
    assert out["permission"] == "deny" and "evaluation error: locked" in out["agent_message"]

    def boom2(*_a, **_k):
        raise TypeError("edits is not a mapping")

    monkeypatch.setattr(sg, "evaluate_status_guard", boom2)
    out = sg.decide_from_stdin(
        json.dumps({"tool_input": {"file_path": "context/tasks/T-261116-a.md", "edits": "x"}}),
        root=tmp_path,
        context_rel="context",
        extract_paths=extract_paths,
    )
    assert out["permission"] == "deny" and "evaluation error" in out["agent_message"]
