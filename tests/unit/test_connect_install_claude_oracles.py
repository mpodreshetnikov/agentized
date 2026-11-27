"""AGE-68 A4: mutation oracles for ``install_claude``.

Tests-only; no runtime change. Target survivors on
``agentized.connect.x_install_claude``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from agentized import connect as connect_mod
from agentized.connect import install_claude
from agentized.managed import load_managed

EXPECTED_SETTINGS: dict[str, Any] = {
    "hooks": {
        "SessionStart": [
            {
                "matcher": "startup|resume|clear|compact|fork",
                "hooks": [
                    {
                        "type": "command",
                        "command": ('python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/session_start.py"'),
                    }
                ],
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Edit|Write",
                "hooks": [
                    {
                        "type": "command",
                        "command": ('python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/process_guard.py"'),
                    }
                ],
            },
            {
                "matcher": "Edit|Write|Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": ('python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/lease_warn.py"'),
                    }
                ],
            },
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/ensure_agent_hooks.py"'
                        ),
                    }
                ],
            },
        ],
    }
}

HINT = "claude --plugin-dir packages/agentized-claude"


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


def test_settings_json_exact_structure_and_utf8_indent(tmp_path: Path):
    """Kill settings.json key/matcher/command/type + write_text encoding mutants."""
    _seed_context_skills(tmp_path)
    seen_enc: list[str | None] = []
    real_w = Path.write_text

    def wrap_w(self: Path, data: str, encoding: str | None = None, **kwargs):
        if self.name == "settings.json":
            seen_enc.append(encoding)
        return real_w(self, data, encoding=encoding, **kwargs)

    with mock.patch.object(Path, "write_text", wrap_w):
        result = install_claude(tmp_path, "context")

    settings_path = tmp_path / ".claude" / "settings.json"
    raw = settings_path.read_text(encoding="utf-8")
    assert raw == json.dumps(EXPECTED_SETTINGS, indent=2) + "\n"
    assert seen_enc == ["utf-8"]
    assert result["settings"] == str(settings_path)
    assert result["plugin_hint"] == HINT


def test_return_keys_and_skills_managed_lists(tmp_path: Path):
    """Kill return-key XX/CASE mutants + skills_result.get key/default mutants."""
    _seed_context_skills(tmp_path)
    result = install_claude(tmp_path, "context")
    expected_copied = [str(tmp_path / ".claude" / "skills" / "demo" / "SKILL.md")]
    assert set(result) == {
        "skills_copied",
        "skills_managed",
        "skipped_user",
        "settings",
        "plugin_hint",
    }
    assert result["skills_copied"] == expected_copied
    assert result["skills_managed"] == {
        "created": expected_copied,
        "updated": [],
        "unchanged": [],
        "skipped_user": [],
        "bootstrapped": [],
    }
    assert result["skipped_user"] == []


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
    """Kill skills_result.get key/default mutants via recorded get calls."""
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
    result = install_claude(tmp_path, "context")
    assert result["skills_copied"] == ["c", "u", "n", "b"]
    assert result["skipped_user"] == ["s"]
    assert result["skills_managed"] is fake
    assert fake.gets == [
        ("created", []),
        ("updated", []),
        ("unchanged", []),
        ("bootstrapped", []),
        ("skipped_user", []),
    ]


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
    install_claude(tmp_path, "context")  # omit force=
    assert seen == [False]
    install_claude(tmp_path, "context", force=True)
    assert seen == [False, True]


def test_managed_copy_argv_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill _managed_copy_tree arg None/omit mutants for root/context_rel/force/manifest."""
    _seed_context_skills(tmp_path)
    calls: list[tuple] = []
    loaded: list[Any] = []
    real = connect_mod._managed_copy_tree
    real_load = connect_mod.load_managed

    def wrap_load(root, context_rel):
        man = real_load(root, context_rel)
        loaded.append(man)
        return man

    def wrap(root, context_rel, src, dst, *, force=False, manifest=None):
        calls.append((root, context_rel, src, dst, force, manifest))
        return real(root, context_rel, src, dst, force=force, manifest=manifest)

    monkeypatch.setattr(connect_mod, "load_managed", wrap_load)
    monkeypatch.setattr(connect_mod, "_managed_copy_tree", wrap)
    install_claude(tmp_path, "context", force=False)
    assert len(calls) == 1
    root, rel, src, dst, force, man = calls[0]
    assert root == tmp_path
    assert rel == "context"
    assert src == tmp_path / "context" / "skills"
    assert dst == tmp_path / ".claude" / "skills"
    assert force is False
    assert loaded == [man]


def test_load_managed_when_manifest_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill load_managed(root, context_rel) None/arity mutants when manifest omitted."""
    _seed_context_skills(tmp_path)
    seen: list[tuple] = []
    real = connect_mod.load_managed

    def wrap(root, context_rel):
        seen.append((root, context_rel))
        return real(root, context_rel)

    monkeypatch.setattr(connect_mod, "load_managed", wrap)
    install_claude(tmp_path, "context")
    assert seen == [(tmp_path, "context")]


def test_provided_manifest_used_without_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill ``manifest if … and False`` / ``or True`` — use provided man, skip load."""
    _seed_context_skills(tmp_path)
    provided: dict[str, Any] = {"__oracle_mark__": "claude-a4"}
    loads: list[tuple] = []
    copy_mans: list[Any] = []
    real_load = connect_mod.load_managed
    real_copy = connect_mod._managed_copy_tree

    def wrap_load(root, context_rel):
        loads.append((root, context_rel))
        return real_load(root, context_rel)

    def wrap_copy(root, context_rel, src, dst, *, force=False, manifest=None):
        copy_mans.append(manifest)
        return real_copy(root, context_rel, src, dst, force=force, manifest=manifest)

    monkeypatch.setattr(connect_mod, "load_managed", wrap_load)
    monkeypatch.setattr(connect_mod, "_managed_copy_tree", wrap_copy)
    install_claude(tmp_path, "context", manifest=provided)
    assert loads == []
    assert copy_mans == [provided]


def test_save_managed_when_manifest_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill save_managed argv mutants + inverted ``if manifest is None``."""
    _seed_context_skills(tmp_path)
    seen: list[tuple] = []
    real = connect_mod.save_managed

    def wrap(root, context_rel, man):
        seen.append((root, context_rel, man))
        return real(root, context_rel, man)

    monkeypatch.setattr(connect_mod, "save_managed", wrap)
    install_claude(tmp_path, "context")
    assert len(seen) == 1
    root, rel, man = seen[0]
    assert root == tmp_path
    assert rel == "context"
    assert man == load_managed(tmp_path, "context")
    seen.clear()
    man2 = load_managed(tmp_path, "context")
    install_claude(tmp_path, "context", manifest=man2)
    assert seen == []


def test_refresh_plugin_name_agentized_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill _refresh_local_plugin name XX/CASE for agentized-claude."""
    _seed_context_skills(tmp_path)
    seen: list[tuple] = []
    real = connect_mod._refresh_local_plugin

    def wrap(root, name, skills_src):
        seen.append((root, name, skills_src))
        return real(root, name, skills_src)

    monkeypatch.setattr(connect_mod, "_refresh_local_plugin", wrap)
    install_claude(tmp_path, "context")
    assert seen == [(tmp_path, "agentized-claude", tmp_path / "context" / "skills")]


def test_pin_hook_scripts_dest_is_claude_hooks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill hooks_dir path mutants via _pin_hook_scripts dest spy."""
    _seed_context_skills(tmp_path)
    seen: list[Path] = []
    real = connect_mod._pin_hook_scripts

    def wrap(root, context_rel, dest):
        seen.append(dest)
        return real(root, context_rel, dest)

    monkeypatch.setattr(connect_mod, "_pin_hook_scripts", wrap)
    install_claude(tmp_path, "context")
    assert seen == [tmp_path / ".claude" / "hooks"]
    assert (tmp_path / ".claude" / "hooks" / "session_start.py").is_file()


def test_hooks_dir_mkdir_parents_exist_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill hooks_dir.mkdir(parents=True, exist_ok=True) kwargs."""
    _seed_context_skills(tmp_path)
    seen: list[dict] = []
    real = Path.mkdir
    hooks_dir = tmp_path / ".claude" / "hooks"

    def wrap(self: Path, *args, **kwargs):
        caller = sys._getframe(1).f_code.co_filename
        if self == hooks_dir and caller == connect_mod.__file__:
            seen.append(dict(kwargs))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", wrap)
    install_claude(tmp_path, "context")
    assert seen == [
        {"parents": True, "exist_ok": True},
        {"parents": True, "exist_ok": True},
    ]


def test_settings_get_hooks_key_and_preserve_other_fields(tmp_path: Path):
    """Kill settings.get('hooks') key mutants; preserve sibling settings keys."""
    _seed_context_skills(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"hooks": {"Other": []}, "permissions": {"allow": ["Bash"]}}, indent=2) + "\n",
        encoding="utf-8",
    )
    result = install_claude(tmp_path, "context")
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["permissions"] == {"allow": ["Bash"]}
    assert data["hooks"]["Other"] == []  # sibling hook keys preserved
    assert data["hooks"]["SessionStart"] == EXPECTED_SETTINGS["hooks"]["SessionStart"]
    assert data["hooks"]["PreToolUse"] == EXPECTED_SETTINGS["hooks"]["PreToolUse"]
    assert result["settings"] == str(settings_path)


def test_settings_path_read_encoding_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill settings_path.read_text(encoding=...) None/omit mutants on existing file."""
    _seed_context_skills(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text('{"keep": true}\n', encoding="utf-8")
    seen: list[str | None] = []
    real = Path.read_text

    def wrap(self: Path, *args, encoding: str | None = None, **kwargs):
        if self.name == "settings.json":
            seen.append(encoding)
        return real(self, *args, encoding=encoding, **kwargs)

    monkeypatch.setattr(Path, "read_text", wrap)
    install_claude(tmp_path, "context")
    assert seen == ["utf-8"]
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["keep"] is True
