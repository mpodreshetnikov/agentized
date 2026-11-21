"""AGE-68 A3: mutation oracles for ``install_cursor``.

Tests-only; no runtime change. Target survivors on
``agentized.connect.x_install_cursor``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from agentized import connect as connect_mod
from agentized.connect import install_cursor
from agentized.managed import load_managed

EXPECTED_HOOKS: dict[str, Any] = {
    "version": 1,
    "hooks": {
        "sessionStart": [{"command": ".cursor/hooks/session_start.py"}],
        "preToolUse": [
            {
                "command": ".cursor/hooks/process_guard.py",
                "matcher": "Write|Edit",
            },
            {
                "command": ".cursor/hooks/lease_warn.py",
                "matcher": "Write|Edit|Shell|Bash",
            },
        ],
        "beforeShellExecution": [{"command": ".cursor/hooks/ensure_agent_hooks.py"}],
        "afterFileEdit": [{"command": ".cursor/hooks/lease_warn.py"}],
    },
}

HINT = (
    "cp -R packages/agentized-cursor ~/.cursor/plugins/local/agentized "
    "или cursor-agent --plugin-dir packages/agentized-cursor"
)


def _seed_context_skills(root: Path, rel: str = "context") -> Path:
    skills = root / rel / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    hooks = root / rel / "hooks" / "scripts"
    hooks.mkdir(parents=True)
    (hooks / "session_start.py").write_text("print('ss')\n", encoding="utf-8")
    (hooks / "process_guard.py").write_text("print('pg')\n", encoding="utf-8")
    (hooks / "lease_warn.py").write_text("print('lw')\n", encoding="utf-8")
    (hooks / "ensure_agent_hooks.py").write_text("print('eah')\n", encoding="utf-8")
    return skills


def test_hooks_json_exact_structure_and_utf8_indent(tmp_path: Path):
    """Kill hooks.json key/path/matcher/version string + write_text encoding/indent mutants."""
    _seed_context_skills(tmp_path)
    seen_enc: list[str | None] = []
    seen_indent: list[Any] = []
    real_w = Path.write_text
    real_dumps = json.dumps

    def wrap_w(self: Path, data: str, encoding: str | None = None, **kwargs):
        if self.name == "hooks.json":
            seen_enc.append(encoding)
        return real_w(self, data, encoding=encoding, **kwargs)

    def wrap_dumps(obj, **kwargs):
        if isinstance(obj, dict) and "hooks" in obj:
            seen_indent.append(kwargs.get("indent", "MISSING"))
        return real_dumps(obj, **kwargs)

    with (
        mock.patch.object(Path, "write_text", wrap_w),
        mock.patch.object(connect_mod.json, "dumps", wrap_dumps),
    ):
        result = install_cursor(tmp_path, "context")

    hooks_path = tmp_path / ".cursor" / "hooks.json"
    raw = hooks_path.read_text(encoding="utf-8")
    assert raw == json.dumps(EXPECTED_HOOKS, indent=2) + "\n"
    assert json.loads(raw) == EXPECTED_HOOKS
    assert seen_enc and all(enc == "utf-8" for enc in seen_enc)
    assert seen_indent and all(i == 2 for i in seen_indent)
    assert result["hooks_json"] == str(hooks_path)


def test_return_keys_and_skills_managed_lists(tmp_path: Path):
    """Kill return-key XX/CASE mutants + skills_result.get key/default mutants."""
    _seed_context_skills(tmp_path)
    result = install_cursor(tmp_path, "context")
    assert set(result) == {
        "skills_copied",
        "skills_managed",
        "skipped_user",
        "hooks_json",
        "plugin_path",
        "local_plugin_hint",
    }
    assert isinstance(result["skills_copied"], list)
    assert result["skills_copied"]  # created/updated paths nonempty
    assert isinstance(result["skills_managed"], dict)
    assert result["skipped_user"] == []
    assert result["plugin_path"] is None
    assert result["local_plugin_hint"] == HINT
    # skills_copied aggregates created+updated+unchanged+bootstrapped
    sm = result["skills_managed"]
    rebuilt = (
        list(sm.get("created", []))
        + list(sm.get("updated", []))
        + list(sm.get("unchanged", []))
        + list(sm.get("bootstrapped", []))
    )
    assert result["skills_copied"] == rebuilt


class _RecordGet(dict):
    """Dict that records ``.get`` key/default pairs for oracle asserts."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gets: list[tuple[Any, Any]] = []

    def get(self, key, default=None):
        self.gets.append((key, default))
        return super().get(key, default)


def test_skills_result_get_keys_and_empty_list_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill skills_result.get key XX/CASE/None + default None/omit mutants."""
    _seed_context_skills(tmp_path)
    fake = _RecordGet(
        created=["c"],
        updated=["u"],
        unchanged=["n"],
        bootstrapped=["b"],
        skipped_user=["s"],
    )

    def wrap(*args, **kwargs):
        return fake

    monkeypatch.setattr(connect_mod, "_managed_copy_tree", wrap)
    # still need pin hooks etc. — install_cursor will call wrap for managed copy only
    result = install_cursor(tmp_path, "context")
    assert result["skills_copied"] == ["c", "u", "n", "b"]
    assert result["skipped_user"] == ["s"]
    assert result["skills_managed"] is fake
    # Exact get calls for the four aggregate keys + skipped_user
    keys = [k for k, _d in fake.gets]
    assert keys.count("created") >= 1
    assert keys.count("updated") >= 1
    assert keys.count("unchanged") >= 1
    assert keys.count("bootstrapped") >= 1
    assert keys.count("skipped_user") >= 1
    for k, d in fake.gets:
        if k in {"created", "updated", "unchanged", "bootstrapped", "skipped_user"}:
            assert d == []
            assert k == k.lower() and "XX" not in str(k)
    assert "CREATED" not in keys
    assert "UPDATED" not in keys
    assert "UNCHANGED" not in keys
    assert "BOOTSTRAPPED" not in keys
    assert "SKIPPED_USER" not in keys
    assert None not in keys
    assert "XXcreatedXX" not in keys
    assert "XXupdatedXX" not in keys
    assert "XXunchangedXX" not in keys
    assert "XXbootstrappedXX" not in keys
    assert "XXskipped_userXX" not in keys


def test_force_default_false_passed_to_managed_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Kill ``force: bool = False`` → True default."""
    _seed_context_skills(tmp_path)
    seen: list[bool | None] = []
    real = connect_mod._managed_copy_tree

    def wrap(root, context_rel, src, dst, *, force=False, manifest=None):
        seen.append(force)
        return real(root, context_rel, src, dst, force=force, manifest=manifest)

    monkeypatch.setattr(connect_mod, "_managed_copy_tree", wrap)
    install_cursor(tmp_path, "context")  # omit force=
    assert seen == [False]
    install_cursor(tmp_path, "context", force=True)
    assert seen[-1] is True


def test_managed_copy_argv_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill _managed_copy_tree arg None/omit mutants for root/context_rel/force/manifest."""
    _seed_context_skills(tmp_path)
    calls: list[tuple] = []
    real = connect_mod._managed_copy_tree

    def wrap(root, context_rel, src, dst, *, force=False, manifest=None):
        calls.append((root, context_rel, src, dst, force, manifest))
        return real(root, context_rel, src, dst, force=force, manifest=manifest)

    monkeypatch.setattr(connect_mod, "_managed_copy_tree", wrap)
    install_cursor(tmp_path, "context", force=False)
    assert len(calls) == 1
    root, rel, src, dst, force, man = calls[0]
    assert root == tmp_path
    assert rel == "context"
    assert src == tmp_path / "context" / "skills"
    assert dst == tmp_path / ".cursor" / "skills"
    assert force is False
    assert man is not None


def test_load_managed_when_manifest_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill load_managed(root, context_rel) None/arity mutants when manifest omitted."""
    _seed_context_skills(tmp_path)
    seen: list[tuple] = []
    real = connect_mod.load_managed

    def wrap(root, context_rel):
        seen.append((root, context_rel))
        return real(root, context_rel)

    monkeypatch.setattr(connect_mod, "load_managed", wrap)
    install_cursor(tmp_path, "context")
    assert seen == [(tmp_path, "context")]


def test_save_managed_when_manifest_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill save_managed argv mutants + inverted ``if manifest is None``."""
    _seed_context_skills(tmp_path)
    seen: list[tuple] = []
    real = connect_mod.save_managed

    def wrap(root, context_rel, man):
        seen.append((root, context_rel, man))
        return real(root, context_rel, man)

    monkeypatch.setattr(connect_mod, "save_managed", wrap)
    install_cursor(tmp_path, "context")
    assert len(seen) == 1
    root, rel, man = seen[0]
    assert root == tmp_path
    assert rel == "context"
    assert isinstance(man, dict)
    # provided manifest → no save
    seen.clear()
    man2 = load_managed(tmp_path, "context")
    install_cursor(tmp_path, "context", manifest=man2)
    assert seen == []


def test_refresh_plugin_name_and_append(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill _refresh_local_plugin name XX/CASE + append(None) + plugin_path False mutants."""
    _seed_context_skills(tmp_path)
    # local packages so refresh can return a path
    plugin = tmp_path / "packages" / "agentized-cursor"
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    plugin.mkdir(parents=True)
    (plugin / "skills").mkdir()
    (plugin / "scripts").mkdir()

    seen: list[tuple] = []
    real = connect_mod._refresh_local_plugin

    def wrap(root, name, skills_src):
        seen.append((root, name, skills_src))
        return real(root, name, skills_src)

    monkeypatch.setattr(connect_mod, "_refresh_local_plugin", wrap)
    result = install_cursor(tmp_path, "context")
    assert seen == [(tmp_path, "agentized-cursor", tmp_path / "context" / "skills")]
    assert result["plugin_path"] == str(plugin)
    assert result["local_plugin_hint"] == HINT


def test_refresh_none_keeps_plugin_path_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill local_note.append / plugin_path ternary when refresh returns None."""
    _seed_context_skills(tmp_path)
    monkeypatch.setattr(connect_mod, "_refresh_local_plugin", lambda *a, **k: None)
    result = install_cursor(tmp_path, "context")
    assert result["plugin_path"] is None


def test_pin_hook_scripts_dest_is_cursor_hooks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill hooks_dir path mutants via _pin_hook_scripts dest spy."""
    _seed_context_skills(tmp_path)
    seen: list[Path] = []
    real = connect_mod._pin_hook_scripts

    def wrap(root, context_rel, dest):
        seen.append(dest)
        return real(root, context_rel, dest)

    monkeypatch.setattr(connect_mod, "_pin_hook_scripts", wrap)
    install_cursor(tmp_path, "context")
    assert seen == [tmp_path / ".cursor" / "hooks"]
    assert (tmp_path / ".cursor" / "hooks" / "session_start.py").is_file()


def test_hooks_dir_mkdir_parents_exist_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill hooks_dir.mkdir(parents=True, exist_ok=True) kwargs."""
    _seed_context_skills(tmp_path)
    seen: list[dict] = []
    real = Path.mkdir

    def wrap(self: Path, *args, **kwargs):
        if self == tmp_path / ".cursor" / "hooks" or self.name == "hooks":
            seen.append(dict(kwargs))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", wrap)
    install_cursor(tmp_path, "context")
    assert any(s.get("parents") is True and s.get("exist_ok") is True for s in seen)


def test_skills_copied_not_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill ``written = (... )`` → None."""
    _seed_context_skills(tmp_path)
    result = install_cursor(tmp_path, "context")
    assert result["skills_copied"] is not None
    assert isinstance(result["skills_copied"], list)


def test_hooks_json_path_str_not_none(tmp_path: Path):
    """Kill ``str(hooks_path)`` → ``str(None)``."""
    _seed_context_skills(tmp_path)
    result = install_cursor(tmp_path, "context")
    hooks = tmp_path / ".cursor" / "hooks.json"
    assert result["hooks_json"] == str(hooks)
    assert "None" not in result["hooks_json"]


def test_pretooluse_matcher_literals(tmp_path: Path):
    """Kill preToolUse matcher Write|Edit and Write|Edit|Shell|Bash case/XX mutants."""
    _seed_context_skills(tmp_path)
    install_cursor(tmp_path, "context")
    data = json.loads((tmp_path / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    pre = data["hooks"]["preToolUse"]
    assert pre[0]["matcher"] == "Write|Edit"
    assert pre[1]["matcher"] == "Write|Edit|Shell|Bash"
    assert pre[0]["command"] == ".cursor/hooks/process_guard.py"
    assert pre[1]["command"] == ".cursor/hooks/lease_warn.py"


def test_hook_event_key_literals(tmp_path: Path):
    """Kill sessionStart/beforeShellExecution/afterFileEdit key case/XX mutants."""
    _seed_context_skills(tmp_path)
    install_cursor(tmp_path, "context")
    data = json.loads((tmp_path / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    hooks = data["hooks"]
    assert list(hooks.keys()) == [
        "sessionStart",
        "preToolUse",
        "beforeShellExecution",
        "afterFileEdit",
    ]
    assert hooks["sessionStart"][0]["command"] == ".cursor/hooks/session_start.py"
    assert hooks["beforeShellExecution"][0]["command"] == (".cursor/hooks/ensure_agent_hooks.py")
    assert hooks["afterFileEdit"][0]["command"] == ".cursor/hooks/lease_warn.py"
    assert data["version"] == 1
    assert set(data) == {"version", "hooks"}
