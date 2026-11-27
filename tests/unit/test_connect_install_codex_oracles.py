"""AGE-68 A5: mutation oracles for ``install_codex``.

Tests-only; no runtime change. Target survivors on
``agentized.connect.x_install_codex``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from agentized import connect as connect_mod
from agentized.connect import install_codex
from agentized.managed import load_managed

HOOK_CMD = 'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/{}.py"'

EXPECTED_HOOKS_JSON: dict[str, Any] = {
    "description": "Agentized project hooks (claim guard, warn-only leases, NAV reminder).",
    "hooks": {
        "SessionStart": [
            {
                "matcher": "startup|resume|clear|compact|fork",
                "hooks": [
                    {
                        "type": "command",
                        "command": HOOK_CMD.format("session_start"),
                        "statusMessage": "Agentized NAV check",
                        "additionalContextLimit": 5000,
                    }
                ],
            }
        ],
        "PreToolUse": [
            {
                "matcher": "apply_patch|Edit|Write",
                "hooks": [
                    {
                        "type": "command",
                        "command": HOOK_CMD.format("process_guard"),
                        "statusMessage": "Agentized process guard",
                        "additionalContextLimit": 5000,
                    }
                ],
            },
            {
                "matcher": "Bash|apply_patch|Edit|Write",
                "hooks": [
                    {
                        "type": "command",
                        "command": HOOK_CMD.format("lease_warn"),
                        "statusMessage": "Agentized lease warn",
                        "additionalContextLimit": 5000,
                    }
                ],
            },
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": HOOK_CMD.format("ensure_agent_hooks"),
                        "statusMessage": "Agentized git-hooks self-heal",
                        "additionalContextLimit": 2000,
                    }
                ],
            },
        ],
    },
}

EXPECTED_MARKETPLACE: dict[str, Any] = {
    "name": "agentized-local",
    "plugins": [
        {
            "name": "agentized",
            "source": {"source": "local", "path": "./packages/agentized-codex"},
            "category": "Productivity",
        }
    ],
}

PLUGIN_HINT = (
    "codex plugin marketplace add . && "
    "codex plugin install agentized@agentized-local  "
    "(или пользуйтесь project .codex/hooks.json + .agents/skills после connect)"
)
GAP = (
    "У Codex нет стабильного --plugin-dir; hooks плагина могут требовать trust. "
    "Connect пишет официальные project hooks в .codex/hooks.json."
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


def test_hooks_json_exact_text_and_marketplace_exact_text(tmp_path: Path):
    """Kill hooks.json / marketplace.json key, value, indent, newline, encoding mutants."""
    _seed_context_skills(tmp_path)
    seen_enc: list[tuple[str, str | None]] = []
    real_w = Path.write_text

    def wrap_w(self: Path, data: str, encoding: str | None = None, **kwargs):
        if self.name in ("hooks.json", "marketplace.json"):
            seen_enc.append((self.name, encoding))
        return real_w(self, data, encoding=encoding, **kwargs)

    with mock.patch.object(Path, "write_text", wrap_w):
        install_codex(tmp_path, "context")

    hooks_raw = (tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8")
    market_raw = (tmp_path / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    assert hooks_raw == json.dumps(EXPECTED_HOOKS_JSON, indent=2) + "\n"
    assert market_raw == json.dumps(EXPECTED_MARKETPLACE, indent=2) + "\n"
    assert seen_enc == [("hooks.json", "utf-8"), ("marketplace.json", "utf-8")]


def test_return_value_exact(tmp_path: Path):
    """Kill return-key XX/CASE mutants and the str(...) wrappers of the path values."""
    _seed_context_skills(tmp_path)
    result = install_codex(tmp_path, "context")
    expected_copied = [str(tmp_path / ".agents" / "skills" / "demo" / "SKILL.md")]
    assert result == {
        "skills_copied": expected_copied,
        "skills_managed": {
            "created": expected_copied,
            "updated": [],
            "unchanged": [],
            "skipped_user": [],
            "bootstrapped": [],
        },
        "skipped_user": [],
        "hooks_json": str(tmp_path / ".codex" / "hooks.json"),
        "marketplace": str(tmp_path / ".agents" / "plugins" / "marketplace.json"),
        "plugin_hint": PLUGIN_HINT,
        "gap": GAP,
    }
    assert list(result) == [
        "skills_copied",
        "skills_managed",
        "skipped_user",
        "hooks_json",
        "marketplace",
        "plugin_hint",
        "gap",
    ]


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
    result = install_codex(tmp_path, "context")
    assert result["skills_copied"] == ["c", "u", "n", "b"]
    assert result["skipped_user"] == ["s"]
    assert result["skills_managed"] == dict(fake)
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
    install_codex(tmp_path, "context")
    assert seen == [False]
    install_codex(tmp_path, "context", force=True)
    assert seen == [False, True]


def test_managed_copy_argv_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill _managed_copy_tree arg None/omit mutants for root/context_rel/src/dst/force/manifest."""
    _seed_context_skills(tmp_path)
    calls: list[tuple] = []
    loaded: list[Any] = []
    real = connect_mod._managed_copy_tree
    real_load = connect_mod.load_managed

    def wrap_load(root, context_rel):
        man = real_load(root, context_rel)
        loaded.append(man)
        return man

    def wrap(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(connect_mod, "load_managed", wrap_load)
    monkeypatch.setattr(connect_mod, "_managed_copy_tree", wrap)
    install_codex(tmp_path, "context", force=False)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (
        tmp_path,
        "context",
        tmp_path / "context" / "skills",
        tmp_path / ".agents" / "skills",
    )
    assert kwargs == {"force": False, "manifest": loaded[0]}
    assert len(loaded) == 1


def test_provided_manifest_used_without_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill ``manifest if … and False`` / ``or True`` / inverted — use provided man, skip load."""
    _seed_context_skills(tmp_path)
    provided: dict[str, Any] = {"__oracle_mark__": "codex-a5"}
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
    install_codex(tmp_path, "context", manifest=provided)
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
    install_codex(tmp_path, "context")
    assert len(seen) == 1
    root, rel, man = seen[0]
    assert root == tmp_path
    assert rel == "context"
    assert man == load_managed(tmp_path, "context")
    seen.clear()
    man2 = load_managed(tmp_path, "context")
    install_codex(tmp_path, "context", manifest=man2)
    assert seen == []


def test_refresh_plugin_name_agentized_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill _refresh_local_plugin name XX/CASE for agentized-codex."""
    _seed_context_skills(tmp_path)
    seen: list[tuple] = []
    real = connect_mod._refresh_local_plugin

    def wrap(root, name, skills_src):
        seen.append((root, name, skills_src))
        return real(root, name, skills_src)

    monkeypatch.setattr(connect_mod, "_refresh_local_plugin", wrap)
    install_codex(tmp_path, "context")
    assert seen == [(tmp_path, "agentized-codex", tmp_path / "context" / "skills")]


def test_connect_mkdir_calls_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill mkdir(parents=…, exist_ok=…) kwarg mutants: exact production call sequence."""
    _seed_context_skills(tmp_path)
    seen: list[tuple[Path, dict]] = []
    real = Path.mkdir

    def wrap(self: Path, *args, **kwargs):
        if sys._getframe(1).f_code.co_filename == connect_mod.__file__:
            seen.append((self, dict(kwargs)))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", wrap)
    install_codex(tmp_path, "context")
    both = {"parents": True, "exist_ok": True}
    assert seen == [
        (tmp_path / ".codex" / "hooks", both),
        (tmp_path / ".codex" / "hooks", both),
        (tmp_path / ".codex", both),
        (tmp_path / ".agents" / "plugins", both),
    ]
