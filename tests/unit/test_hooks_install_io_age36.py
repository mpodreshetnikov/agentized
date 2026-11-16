"""AGE-36: hooks_install_io JSON refuse paths."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agentized.connect import connect, uninstall_hooks
from agentized.connect_plan import refuse_exit_code
from agentized.hooks_install import (
    HooksJsonError,
    plan_harness_hooks,
    read_json_object,
    refuse_plan,
    uninstall_harness_hooks,
)
from agentized.hooks_install_io import JSON_TEXT_ENCODING


def _skeleton(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    ctx = root / "context"
    for p in (
        ctx / "tasks",
        ctx / "leases",
        ctx / "hooks" / "scripts",
        ctx / "skills",
        root / "packages" / "shared" / "skills" / "navigate",
        root / "packages" / "shared" / "hooks" / "scripts",
        root / "templates" / "quality",
    ):
        p.mkdir(parents=True, exist_ok=True)
    (ctx / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (root / "packages" / "shared" / "skills" / "navigate" / "SKILL.md").write_text(
        "---\nname: navigate\n---\n", encoding="utf-8"
    )
    (root / "packages" / "shared" / "hooks" / "scripts" / "session_start.py").write_text(
        "print('ok')\n", encoding="utf-8"
    )
    (root / "templates" / "quality" / "pre-push").write_text(
        "#!/bin/sh\n# AGENTIZED:QUALITY\necho hi\n", encoding="utf-8"
    )
    (root / "templates" / "quality" / "ci.yml").write_text(
        "# AGENTIZED:QUALITY\nname: CI\n", encoding="utf-8"
    )


def test_read_json_object_refuse_cases(tmp_path: Path):
    assert JSON_TEXT_ENCODING == "utf-8"

    missing = tmp_path / "nope.json"
    assert read_json_object(missing) == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    with pytest.raises(HooksJsonError) as exc:
        read_json_object(broken)
    assert exc.value.reason[:13] == "broken JSON ("
    assert exc.value.path == broken

    arr = tmp_path / "arr.json"
    arr.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(HooksJsonError) as exc2:
        read_json_object(arr)
    assert exc2.value.reason == "top-level must be object, got list"
    assert exc2.value.path == arr

    num = tmp_path / "num.json"
    num.write_text("1\n", encoding="utf-8")
    with pytest.raises(HooksJsonError) as exc_num:
        read_json_object(num)
    assert exc_num.value.reason == "top-level must be object, got int"
    assert exc_num.value.path == num

    ok = tmp_path / "ok.json"
    ok.write_text('{"a": 1}\n', encoding="utf-8")
    assert read_json_object(ok) == {"a": 1}

    bad_utf = tmp_path / "bin.json"
    bad_utf.write_bytes(b"\xff\xfe")
    with pytest.raises(HooksJsonError) as exc3:
        read_json_object(bad_utf)
    assert exc3.value.reason.startswith(f"not {JSON_TEXT_ENCODING} (")
    assert exc3.value.reason[:9] == "not utf-8"
    assert exc3.value.path == bad_utf


def test_read_json_object_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "blocked.json"
    path.write_text("{}\n", encoding="utf-8")

    def boom(_self: Path) -> bytes:
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(HooksJsonError) as exc:
        read_json_object(path)
    assert exc.value.path == path
    assert exc.value.reason.startswith("unreadable (")
    assert "denied" in exc.value.reason
    assert str(exc.value) == f"invalid harness JSON at {path}: {exc.value.reason}"


def test_plan_and_uninstall_refuse_broken_cursor(tmp_path: Path):
    _skeleton(tmp_path)
    target = tmp_path / ".cursor" / "hooks.json"
    target.parent.mkdir(parents=True)
    target.write_text("{broken", encoding="utf-8")
    before = target.read_bytes()

    plans = plan_harness_hooks(tmp_path, ["cursor"], context_rel="context")
    assert len(plans) == 1
    assert plans[0]["action"] == "refuse"
    assert plans[0]["harness"] == "cursor"
    assert plans[0]["path"] == str(target)
    assert plans[0]["changed"] is False
    assert target.read_bytes() == before

    results = uninstall_harness_hooks(tmp_path, ["cursor"], context_rel="context")
    assert results[0]["action"] == "refuse"
    assert results[0]["harness"] == "cursor"
    assert results[0]["path"] == str(target)
    assert results[0]["wrote"] is False
    assert target.read_bytes() == before


def test_plan_continues_after_refuse(tmp_path: Path):
    cursor = tmp_path / ".cursor" / "hooks.json"
    cursor.parent.mkdir(parents=True)
    cursor.write_text("{broken", encoding="utf-8")
    plans = plan_harness_hooks(tmp_path, ["cursor", "claude"], context_rel="context")
    assert [p["harness"] for p in plans] == ["cursor", "claude"]
    assert [p["action"] for p in plans] == ["refuse", "create"]
    assert plans[0]["path"] == str(cursor)
    assert plans[1]["path"] == str(tmp_path / ".claude" / "settings.json")


def test_uninstall_continues_past_missing_and_refuse(tmp_path: Path):
    # cursor missing → skip; claude broken → refuse; codex valid → skip
    claude = tmp_path / ".claude" / "settings.json"
    claude.parent.mkdir(parents=True)
    claude.write_text("{", encoding="utf-8")
    codex = tmp_path / ".codex" / "hooks.json"
    codex.parent.mkdir(parents=True)
    codex.write_text("{}\n", encoding="utf-8")
    results = uninstall_harness_hooks(
        tmp_path, ["cursor", "claude", "codex"], context_rel="context"
    )
    assert [r["harness"] for r in results] == ["claude", "codex"]
    assert [r["action"] for r in results] == ["refuse", "skip"]
    assert results[0]["path"] == str(claude)
    assert results[0]["harness"] == "claude"
    assert results[1]["path"] == str(codex)


def test_connect_dry_run_refuse_flag(tmp_path: Path):
    _skeleton(tmp_path)
    target = tmp_path / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text("null", encoding="utf-8")
    before = target.read_bytes()
    dry = connect(tmp_path, context_rel="context", harnesses=["claude"], dry_run=True)
    assert dry["refused"] is True
    assert any(p["action"] == "refuse" for p in dry["hook_plans"])
    assert target.read_bytes() == before


def test_uninstall_hooks_refused_wrapper(tmp_path: Path):
    _skeleton(tmp_path)
    target = tmp_path / ".codex" / "hooks.json"
    target.parent.mkdir(parents=True)
    target.write_text("{", encoding="utf-8")
    result = uninstall_hooks(tmp_path, harnesses=["codex"])
    assert result["refused"] is True
    assert result["results"][0]["action"] == "refuse"
    assert target.read_bytes() == b"{"


def test_uninstall_skip_valid_without_hooks_merge(tmp_path: Path):
    _skeleton(tmp_path)
    target = tmp_path / ".cursor" / "hooks.json"
    target.parent.mkdir(parents=True)
    payload = {"version": 1, "hooks": {"sessionStart": [{"command": "echo x"}]}}
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    before = target.read_bytes()
    results = uninstall_harness_hooks(tmp_path, ["cursor"], context_rel="context")
    assert results == [
        {
            "path": str(target),
            "harness": "cursor",
            "action": "skip",
            "changed": False,
            "wrote": False,
            "reason": "hooks_merge_unavailable",
        }
    ]
    assert target.read_bytes() == before


def test_refuse_exit_code_from_dry_run_and_uninstall(tmp_path: Path):
    _skeleton(tmp_path)
    target = tmp_path / ".cursor" / "hooks.json"
    target.parent.mkdir(parents=True)
    target.write_text("{broken", encoding="utf-8")
    dry = connect(tmp_path, context_rel="context", harnesses=["cursor"], dry_run=True)
    assert refuse_exit_code(dry) == 1
    un = uninstall_hooks(tmp_path, harnesses=["cursor"])
    assert refuse_exit_code(un) == 1
    target.write_text(json.dumps({"version": 1}, indent=2) + "\n", encoding="utf-8")
    clean = connect(tmp_path, context_rel="context", harnesses=["cursor"], dry_run=True)
    assert refuse_exit_code(clean) == 0
    assert refuse_exit_code({"refused": False}) == 0
    assert refuse_exit_code({}) == 0


def test_plan_create_when_missing(tmp_path: Path):
    plans = plan_harness_hooks(tmp_path, ["cursor"], context_rel="context")
    assert plans[0]["action"] == "create"
    assert plans[0]["changed"] is True


def test_uninstall_skips_missing(tmp_path: Path):
    assert uninstall_harness_hooks(tmp_path, ["cursor", "claude", "codex"], context_rel="context") == []


def test_plan_update_when_hooks_exist(tmp_path: Path):
    target = tmp_path / ".cursor" / "hooks.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"version": 1}, indent=2) + "\n", encoding="utf-8")
    plans = plan_harness_hooks(tmp_path, ["cursor"], context_rel="context")
    assert plans[0]["action"] == "update"
    assert plans[0]["path"] == str(target)


def test_refuse_plan_exact_shape(tmp_path: Path):
    path = tmp_path / ".cursor" / "hooks.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(HooksJsonError) as exc:
        read_json_object(path)
    plan = refuse_plan(path, "cursor", exc.value)
    assert plan == {
        "path": str(path),
        "harness": "cursor",
        "action": "refuse",
        "changed": False,
        "wrote": False,
        "error": str(exc.value),
        "reason": exc.value.reason,
    }
    assert f"invalid harness JSON at {path}: {exc.value.reason}" == plan["error"]


def test_plan_harness_paths_exact(tmp_path: Path):
    plans = plan_harness_hooks(tmp_path, ["cursor", "codex"], context_rel="context")
    assert [p["path"] for p in plans] == [
        str(tmp_path / ".cursor" / "hooks.json"),
        str(tmp_path / ".codex" / "hooks.json"),
    ]
    assert [p["action"] for p in plans] == ["create", "create"]
    assert [p["harness"] for p in plans] == ["cursor", "codex"]
    assert [p["changed"] for p in plans] == [True, True]


def test_context_rel_required(tmp_path: Path):
    with pytest.raises(ValueError, match="^context_rel required$"):
        plan_harness_hooks(tmp_path, ["cursor"], context_rel="")
    with pytest.raises(ValueError, match="^context_rel required$"):
        uninstall_harness_hooks(tmp_path, ["cursor"], context_rel="")


def test_uninstall_all_three_harnesses(tmp_path: Path):
    for rel in (".cursor/hooks.json", ".claude/settings.json", ".codex/hooks.json"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    results = uninstall_harness_hooks(
        tmp_path, ["cursor", "claude", "codex"], context_rel="context"
    )
    assert [r["harness"] for r in results] == ["cursor", "claude", "codex"]
    assert [r["action"] for r in results] == ["skip", "skip", "skip"]


def test_hooks_json_error_keeps_path(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_bytes(b"\xff")
    with pytest.raises(HooksJsonError) as exc:
        read_json_object(path)
    assert exc.value.path == path
    assert str(exc.value) == f"invalid harness JSON at {path}: {exc.value.reason}"
