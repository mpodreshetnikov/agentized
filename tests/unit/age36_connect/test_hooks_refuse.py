"""AGE-36: dry-run / uninstall refuse → non-zero; broken JSON left unchanged."""
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
    missing = tmp_path / "nope.json"
    assert read_json_object(missing) == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    with pytest.raises(HooksJsonError) as exc:
        read_json_object(broken)
    assert exc.value.reason[:12] == "broken JSON ("

    arr = tmp_path / "arr.json"
    arr.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(HooksJsonError) as exc2:
        read_json_object(arr)
    assert exc2.value.reason == "top-level must be object, got list"

    ok = tmp_path / "ok.json"
    ok.write_text('{"a": 1}\n', encoding="utf-8")
    assert read_json_object(ok) == {"a": 1}

    bad_utf = tmp_path / "bin.json"
    bad_utf.write_bytes(b"\xff\xfe")
    with pytest.raises(HooksJsonError) as exc3:
        read_json_object(bad_utf)
    assert exc3.value.reason.startswith("not utf-8")


def test_plan_and_uninstall_refuse_broken_cursor(tmp_path: Path):
    _skeleton(tmp_path)
    target = tmp_path / ".cursor" / "hooks.json"
    target.parent.mkdir(parents=True)
    target.write_text("{broken", encoding="utf-8")
    before = target.read_bytes()

    plans = plan_harness_hooks(tmp_path, ["cursor"], context_rel="context")
    assert len(plans) == 1
    assert plans[0]["action"] == "refuse"
    assert plans[0]["changed"] is False
    assert target.read_bytes() == before

    results = uninstall_harness_hooks(tmp_path, ["cursor"], context_rel="context")
    assert results[0]["action"] == "refuse"
    assert results[0]["wrote"] is False
    assert target.read_bytes() == before


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
    with pytest.raises(ValueError):
        plan_harness_hooks(tmp_path, ["cursor"], context_rel="")
    with pytest.raises(ValueError):
        uninstall_harness_hooks(tmp_path, ["cursor"], context_rel="")
