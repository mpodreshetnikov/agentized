"""AGE-23: hooks_install apply + refuse (full-cover mutation)."""

from __future__ import annotations
import json
import os
from pathlib import Path
import pytest
from agentized.hooks_install import (
    JSON_INDENT,
    JSON_TEXT_ENCODING,
    HooksJsonError,
    _atomic_write_bytes,
    _json_payload,
    apply_harness_hook_merge,
    apply_marketplace_merge,
    desired_claude_hooks,
    desired_codex_document,
    desired_cursor_hooks,
    harness_hook_path,
    hooks_owned_path,
    load_hooks_owned,
    read_json_object,
    refuse_plan,
    save_hooks_owned,
    summarize_hooks_refused,
    write_json,
)

FOREIGN_CURSOR = {
    "version": 1,
    "hooks": {
        "sessionStart": [{"command": "echo foreign-start"}],
        "customEvent": [{"command": "foreign/custom.py"}],
    },
}


def _skeleton(root: Path) -> None:
    (root / "context" / ".agentized").mkdir(parents=True)
    for d in (".cursor", ".claude", ".codex"):
        (root / d).mkdir(parents=True, exist_ok=True)


def test_json_io_constants_owned_desired(tmp_path: Path, monkeypatch):
    import agentized.hooks_install as hi

    assert JSON_TEXT_ENCODING == "utf-8"
    assert JSON_INDENT == 2
    assert hi.ENSURE_ASCII is False
    assert _json_payload({"a": 1}) == b'{\n  "a": 1\n}\n'
    monkeypatch.setattr(hi, "ENSURE_ASCII", True)
    with pytest.raises(RuntimeError, match="^ENSURE_ASCII must be False$"):
        _json_payload({"a": 1})
    monkeypatch.setattr(hi, "ENSURE_ASCII", False)

    cyr = _json_payload({"msg": "Привет"})
    assert b"\\u" not in cyr
    assert "Привет".encode("utf-8") in cyr
    path = tmp_path / "deep" / "x.json"
    path.parent.mkdir(parents=True)
    assert write_json(path, {"msg": "Привет", "n": 1}) is True
    assert read_json_object(path) == {"msg": "Привет", "n": 1}
    assert write_json(path, {"msg": "Привет", "n": 1}) is False
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(HooksJsonError) as ei:
        read_json_object(path)
    assert ei.value.path == path and "broken JSON" in ei.value.reason
    path.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(HooksJsonError) as ei2:
        read_json_object(path)
    assert ei2.value.path == path and "list" in ei2.value.reason
    assert "top-level must be object" in ei2.value.reason
    assert read_json_object(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"{\xff")
    with pytest.raises(HooksJsonError) as ei3:
        read_json_object(bad)
    assert ei3.value.path == bad and "utf-8" in ei3.value.reason.lower()

    def boom(*_a, **_k):
        raise OSError("nope")

    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(HooksJsonError) as ei4:
        read_json_object(path)
    assert ei4.value.path == path and "unreadable" in ei4.value.reason
    monkeypatch.undo()
    replaces: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        replaces.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    target = tmp_path / "atomic.json"
    _atomic_write_bytes(target, b'{"ok":1}\n')
    assert target.read_bytes() == b'{"ok":1}\n'
    assert replaces and replaces[0][0].name.endswith(".tmp") and replaces[0][1] == target
    monkeypatch.undo()
    owned = hooks_owned_path(tmp_path, "context")
    owned.parent.mkdir(parents=True)
    owned.write_text("{bad", encoding="utf-8")
    with pytest.raises(HooksJsonError) as ei5:
        load_hooks_owned(tmp_path, "context")
    assert ei5.value.path == owned and "broken JSON" in ei5.value.reason
    owned.write_bytes(b'{"cursor": ["\xff"]}')
    with pytest.raises(HooksJsonError) as ei_utf:
        load_hooks_owned(tmp_path, "context")
    assert ei_utf.value.path == owned and "utf-8" in ei_utf.value.reason.lower()
    owned.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(HooksJsonError) as ei6:
        load_hooks_owned(tmp_path, "context")
    assert ei6.value.path == owned and "list" in ei6.value.reason
    owned.write_text('{"cursor": "nope"}', encoding="utf-8")
    with pytest.raises(HooksJsonError) as bad_owned:
        load_hooks_owned(tmp_path, "context")
    assert bad_owned.value.path == owned
    assert bad_owned.value.reason == "values must be list[str] (bad key 'cursor')"
    owned.write_text('{"cursor": [1]}', encoding="utf-8")
    with pytest.raises(HooksJsonError) as bad_owned2:
        load_hooks_owned(tmp_path, "context")
    assert bad_owned2.value.path == owned
    owned.write_text("{}", encoding="utf-8")

    def boom2(*_a, **_k):
        raise OSError("owned-boom")

    monkeypatch.setattr(Path, "read_bytes", boom2)
    with pytest.raises(HooksJsonError) as ei7:
        load_hooks_owned(tmp_path, "context")
    assert ei7.value.path == owned and "owned-boom" in ei7.value.reason
    monkeypatch.undo()
    assert load_hooks_owned(tmp_path, "missing") == {}
    owned_rel = hooks_owned_path(tmp_path, "ctx")
    assert owned_rel.parts[-2:] == (".agentized", "hooks_owned.json")
    out = save_hooks_owned(tmp_path, {"cursor": ["a", "b"], "claude": []}, "ctx")
    assert out == owned_rel
    assert load_hooks_owned(tmp_path, "ctx") == {"cursor": ["a", "b"]}
    import agentized.hooks_install as hi

    monkeypatch.setattr(hi, "_load_desired_bundle", lambda root=None: {"cursor_hooks": {"a": []}})
    with pytest.raises(KeyError, match="claude_hooks"):
        hi.desired_claude_hooks()
    monkeypatch.setattr(
        hi, "_load_desired_bundle", lambda root=None: {"claude_hooks": 1, "cursor_hooks": {}}
    )
    with pytest.raises(ValueError, match="must be an object"):
        hi.desired_claude_hooks()
    monkeypatch.undo()
    assert desired_cursor_hooks() and desired_claude_hooks() and desired_codex_document()
    real_is = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: False if self.name == "harness_desired.json" else real_is(self),
    )
    with pytest.raises(HooksJsonError) as miss:
        hi._desired_bundle_path()
    assert "missing" in miss.value.reason
    monkeypatch.undo()
    bad_bundle = tmp_path / "harness_desired.json"
    bad_bundle.write_text("[1]\n", encoding="utf-8")
    monkeypatch.setattr(hi, "_desired_bundle_path", lambda root=None: bad_bundle)
    with pytest.raises(ValueError, match="^harness_desired.json must be an object$"):
        hi._load_desired_bundle()
    monkeypatch.undo()
    exc = HooksJsonError(Path("p.json"), "broken JSON (x)")
    assert str(exc) == "invalid harness JSON at p.json: broken JSON (x)"
    assert refuse_plan(Path("p.json"), "cursor", exc) == {
        "path": "p.json",
        "harness": "cursor",
        "action": "refuse",
        "changed": False,
        "wrote": False,
        "error": str(exc),
        "reason": "broken JSON (x)",
    }
    plain = ValueError("plain-err")
    assert refuse_plan(Path("p.json"), "claude", plain)["reason"] == "plain-err"
    ok, refused = summarize_hooks_refused(
        {
            "cursor": {
                "hooks_merge": {
                    "action": "refuse",
                    "path": ".cursor/hooks.json",
                    "reason": "broken JSON",
                    "error": "err",
                }
            },
            "claude": {"hooks_merge": {"action": "merge", "wrote": True}},
            "skip": "not-dict",
        }
    )
    assert ok is False
    assert refused == [
        {
            "harness": "cursor",
            "path": ".cursor/hooks.json",
            "reason": "broken JSON",
            "error": "err",
        }
    ]
    assert summarize_hooks_refused(
        {"cursor": {"hooks_merge": {"action": "create", "wrote": True}}}
    ) == (True, [])
    assert summarize_hooks_refused({}) == (True, [])
    ok_m, refused_m = summarize_hooks_refused(
        {
            "codex": {
                "marketplace_merge": {
                    "action": "refuse",
                    "path": "m.json",
                    "reason": "shape",
                    "error": "e",
                }
            }
        }
    )
    assert ok_m is False
    assert refused_m == [{"harness": "codex", "path": "m.json", "reason": "shape", "error": "e"}]


def test_apply_merge_shape_refuse_create_skip_owned_dry(tmp_path: Path, monkeypatch):
    import agentized.hooks_install as hi

    _skeleton(tmp_path)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".cursor" / "hooks.json"
    path.write_text(json.dumps(FOREIGN_CURSOR, indent=2) + "\n", encoding="utf-8")
    before = path.read_bytes()
    dry = apply_harness_hook_merge(tmp_path, "cursor", context_rel="context", dry_run=True)
    assert dry["action"] == "merge" and dry["wrote"] is False and dry["dry_run"] is True
    assert path.read_bytes() == before
    assert not hooks_owned_path(tmp_path, "context").exists()
    plan = apply_harness_hook_merge(tmp_path, "cursor", context_rel="context")
    assert plan["action"] == "merge" and plan["wrote"] is True
    assert plan["path"] == str(path)
    assert plan["harness"] == "cursor"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert any(e.get("command") == "echo foreign-start" for e in data["hooks"]["sessionStart"])
    assert "customEvent" in data["hooks"]
    assert all("agentized" not in e for e in data["hooks"]["sessionStart"] if isinstance(e, dict))
    assert load_hooks_owned(tmp_path, "context").get("cursor")
    path.write_text('{"hooks":[{"command":"./mine.sh"}]}', encoding="utf-8")
    shape_bytes = path.read_bytes()
    shape = apply_harness_hook_merge(tmp_path, "cursor", context_rel="context")
    assert shape["action"] == "refuse" and shape["wrote"] is False
    assert shape["harness"] == "cursor" and shape["path"] == str(path)
    assert path.read_bytes() == shape_bytes
    path.write_text("{broken", encoding="utf-8")
    before_b = path.read_bytes()
    refused = apply_harness_hook_merge(tmp_path, "cursor", context_rel="context")
    assert refused["action"] == "refuse" and refused["wrote"] is False
    assert refused["harness"] == "cursor" and refused["path"] == str(path)
    assert path.read_bytes() == before_b
    owned = hooks_owned_path(tmp_path, "context")
    owned.write_text("{bad", encoding="utf-8")
    cpath = harness_hook_path(tmp_path, "cursor")
    if cpath.exists():
        cpath.unlink()
    owned_refuse = apply_harness_hook_merge(tmp_path, "cursor", context_rel="context")
    assert owned_refuse["action"] == "refuse" and owned_refuse["path"] == str(owned)
    assert owned_refuse["harness"] == "cursor"
    assert not cpath.exists()
    owned.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError) as uh:
        apply_harness_hook_merge(tmp_path, "nope", context_rel="context")
    assert str(uh.value) == "unknown harness: nope"
    created = apply_harness_hook_merge(tmp_path, "codex", context_rel="context")
    assert created["action"] == "create" and created["wrote"] is True
    assert created["harness"] == "codex"
    assert created["path"] == str(harness_hook_path(tmp_path, "codex"))
    again = apply_harness_hook_merge(tmp_path, "codex", context_rel="context")
    assert again["action"] == "skip" and again["wrote"] is False
    assert again["harness"] == "codex"
    stale = "echo was-ours-custom"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "sessionStart": [
                        {"command": stale},
                        {"command": "echo foreign-keep"},
                    ]
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    save_hooks_owned(tmp_path, {"cursor": [stale]}, "context")
    apply_harness_hook_merge(tmp_path, "cursor", context_rel="context")
    cmds = [
        e.get("command")
        for e in json.loads(path.read_text(encoding="utf-8"))["hooks"]["sessionStart"]
    ]
    assert stale not in cmds and "echo foreign-keep" in cmds
    cmd = ".cursor/hooks/session_start.py"
    hi._record_owned(
        tmp_path,
        "cursor",
        {
            "hooks": {
                "sessionStart": [
                    {"command": cmd},
                    {"command": cmd},
                    {"command": "echo foreign"},
                ]
            }
        },
        context_rel="dedupe",
    )
    assert load_hooks_owned(tmp_path, "dedupe")["cursor"] == [cmd]
    market = tmp_path / ".agents" / "plugins" / "marketplace.json"
    market.parent.mkdir(parents=True)
    market.write_text(
        json.dumps({"name": "keep", "plugins": [{"name": "foreign"}]}, indent=2) + "\n",
        encoding="utf-8",
    )
    m_before = market.read_bytes()
    m_dry = apply_marketplace_merge(tmp_path, dry_run=True)
    assert m_dry["wrote"] is False and m_dry["dry_run"] is True
    assert market.read_bytes() == m_before
    AGENTIZED_PLUG = {
        "name": "agentized",
        "source": {"source": "local", "path": "./packages/agentized-codex"},
        "category": "Productivity",
    }
    m_plan = apply_marketplace_merge(tmp_path)
    assert m_plan["wrote"] and m_plan["kind"] == "marketplace" and m_plan["harness"] == "codex"
    assert m_plan["path"] == str(market)
    body = json.loads(market.read_text(encoding="utf-8"))
    assert body["name"] == "keep" and body["plugins"][0]["name"] == "foreign"
    assert body["plugins"][1] == AGENTIZED_PLUG
    market.write_text('{"plugins":{}}', encoding="utf-8")
    shape_m = market.read_bytes()
    refused_m = apply_marketplace_merge(tmp_path)
    assert refused_m["action"] == "refuse" and market.read_bytes() == shape_m
    assert refused_m["harness"] == "codex" and refused_m["path"] == str(market)
    assert refused_m["error"] not in ("", "None") and "list" in refused_m["reason"]
    mk: list[dict] = []
    real_mkdir = Path.mkdir
    monkeypatch.setattr(
        Path, "mkdir", lambda self, *a, **k: mk.append(k) or real_mkdir(self, *a, **k)
    )
    apply_harness_hook_merge(tmp_path / "deep-root", "cursor", context_rel="context")
    assert any(c.get("parents") is True for c in mk)


def test_marketplace_and_desired_root_and_abs_path(tmp_path: Path, monkeypatch):
    import agentized.hooks_install as hi
    from agentized.hooks_boundary import is_agentized_command as iac
    from agentized.hooks_merge import merge_cursor_hooks

    _skeleton(tmp_path)
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "packages/shared/hooks"
    local.mkdir(parents=True)
    local_cursor = {"sessionStart": [{"command": "LOCAL_ONLY_CURSOR"}]}
    local.joinpath("harness_desired.json").write_text(
        json.dumps(
            {
                "cursor_hooks": local_cursor,
                "claude_hooks": {"Notification": []},
                "codex": {"hooks": {"SessionStart": []}},
            }
        ),
        encoding="utf-8",
    )
    assert hi.desired_cursor_hooks(tmp_path) == local_cursor
    assert hi.desired_claude_hooks(tmp_path) == {"Notification": []}
    assert hi.desired_codex_document(tmp_path) == {"hooks": {"SessionStart": []}}
    assert hi._require_desired_section("cursor_hooks", tmp_path) == local_cursor
    assert hi._load_desired_bundle(tmp_path)["claude_hooks"] == {"Notification": []}
    table = hi._merge_table(tmp_path)
    assert table["cursor"][0]() == local_cursor
    assert table["claude"][0]() == {"Notification": []}
    assert table["codex"][0]() == {"hooks": {"SessionStart": []}}
    cur = apply_harness_hook_merge(tmp_path, "cursor", context_rel="context")
    assert cur["wrote"] and "LOCAL_ONLY_CURSOR" in (tmp_path / ".cursor/hooks.json").read_text()
    plan = apply_marketplace_merge(tmp_path)
    assert plan["action"] == "create" and plan["wrote"] and plan["harness"] == "codex"
    created = json.loads(
        (tmp_path / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
    )
    assert created == {
        "name": "agentized-local",
        "plugins": [
            {
                "name": "agentized",
                "source": {"source": "local", "path": "./packages/agentized-codex"},
                "category": "Productivity",
            }
        ],
    }
    assert apply_marketplace_merge(tmp_path)["action"] == "skip"

    # Exact known form + absolute whole-command aliases (no compound / substring).
    assert iac(".cursor/hooks/session_start.py", "cursor") is True
    abs_cur = "/home/u/repo/.cursor/hooks/session_start.py"
    assert iac(abs_cur, "cursor") is True
    assert iac('python3 "/opt/proj/.claude/hooks/process_guard.py"', "claude") is True
    assert iac("python3 /opt/proj/.claude/hooks/lease_warn.py", "claude") is True
    assert iac('python3 "/opt/proj/.codex/hooks/ensure_agent_hooks.py"', "codex") is True
    assert iac("vendor/.cursor/hooks/session_start.py", "cursor") is False
    assert iac('x ".cursor/hooks/session_start.py"', "cursor") is False
    assert iac("echo /home/u/repo/.cursor/hooks/session_start.py", "cursor") is False
    assert iac(f"{abs_cur}; ./mine.sh", "cursor") is False
    assert iac("nope", "unknown-harness") is False

    # Abs path recognized → merge replaces it (no duplicate of desired relative form).
    desired = {"sessionStart": [{"command": ".cursor/hooks/session_start.py"}]}
    existing = {
        "version": 1,
        "hooks": {
            "sessionStart": [
                {"command": "echo foreign"},
                {"command": abs_cur},
            ]
        },
    }
    out = merge_cursor_hooks(existing, desired)
    assert out["hooks"]["sessionStart"] == [
        {"command": "echo foreign"},
        {"command": ".cursor/hooks/session_start.py"},
    ]

    miss_root = tmp_path / "empty-desired"
    miss_root.mkdir()
    real_is = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: False if self.name == "harness_desired.json" else real_is(self),
    )
    with pytest.raises(HooksJsonError) as miss:
        hi._desired_bundle_path(miss_root)
    assert miss.value.reason == "harness_desired.json missing (local and installed)"
    assert miss.value.path == miss_root / "packages/shared/hooks/harness_desired.json"
