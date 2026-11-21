"""AGE-23: hooks_merge + hooks_boundary mutation-hard tests (no stamp/strip)."""
from __future__ import annotations

import pytest

from agentized.hooks_boundary import (
    _ALLOWED_PREFIX_SEGS,
    _DOLLAR,
    _SLASH,
    _path_prefix_allowed,
    is_agentized_command,
)
from agentized.hooks_merge import (
    CURSOR_VERSION_KEY,
    HooksShapeError,
    _collect_owned_commands,
    cursor_entry_is_ours,
    merge_claude_settings,
    merge_codex_hooks,
    merge_cursor_hooks,
    merge_marketplace_plugins,
    merge_nested_hooks,
    nested_hook_is_ours,
    plan_json_change,
)


def test_is_agentized_boundaries_and_owned():
    cases = [
        (".cursor/hooks/session_start.py", "cursor", True),
        (r".cursor\hooks\process_guard.py", "cursor", True),
        (".claude/hooks/lease_warn.py", "claude", True),
        (".codex/hooks/ensure_agent_hooks.py", "codex", True),
        ("vendor/.cursor/hooks/session_start.py", "cursor", False),
        ("x.cursor/hooks/lease_warn.py", "cursor", False),
        ("my.cursor/hooks/session_start.py", "cursor", False),
        (".cursor/hooks/session_start.py;echo", "cursor", True),
        ("", "cursor", False),
        (None, "cursor", False),
        (
            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/process_guard.py"',
            "claude",
            True,
        ),
        ('cmd ".cursor/hooks/session_start.py"', "cursor", True),
        (" .cursor/hooks/session_start.py", "cursor", True),
    ]
    assert [(c, h, is_agentized_command(c, h)) for c, h, _ in cases] == [
        (c, h, e) for c, h, e in cases
    ]
    assert _path_prefix_allowed(".cursor/hooks/x.py", 0) is True
    assert _path_prefix_allowed('x".cursor/hooks/x.py', 2) is True
    assert cursor_entry_is_ours({"command": ".cursor/hooks/session_start.py"}) is True
    assert cursor_entry_is_ours({"command": "foreign"}) is False
    assert cursor_entry_is_ours("x") is False
    assert cursor_entry_is_ours({"command": ".cursor/hooks/my_lease_warn.py"}) is False
    unmarked = {"command": ".cursor/hooks/old_renamed.py"}
    assert cursor_entry_is_ours(unmarked) is False
    assert (
        cursor_entry_is_ours(
            unmarked, previously_owned=frozenset({unmarked["command"]})
        )
        is True
    )
    assert (
        nested_hook_is_ours(
            {
                "command": (
                    'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/process_guard.py"'
                )
            },
            "claude",
        )
        is True
    )
    assert nested_hook_is_ours({"command": "echo"}, "claude") is False
    assert nested_hook_is_ours("x", "claude") is False
    assert (
        nested_hook_is_ours(
            {"command": "legacy.sh"},
            "claude",
            previously_owned=frozenset({"legacy.sh"}),
        )
        is True
    )


def test_path_prefix_edge_cases():
    iac = is_agentized_command
    assert iac('x ".cursor/hooks/session_start.py"', "cursor")
    assert iac("vendor/.cursor/hooks/session_start.py", "cursor") is False
    for cmd in (
        ".cursor/hooks/session_start.py",
        "./.cursor/hooks/session_start.py",
        "../.cursor/hooks/session_start.py",
        "/.cursor/hooks/session_start.py",
        "/./.cursor/hooks/session_start.py",
        "$HOME/.cursor/hooks/session_start.py",
        "prefix/$HOME/.cursor/hooks/session_start.py",
        "foo/./.cursor/hooks/session_start.py",
        'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/session_start.py"',
        "nox.cursor/hooks/session_start.py ok .cursor/hooks/process_guard.py",
    ):
        harness = "codex" if ".codex/" in cmd else "cursor"
        assert iac(cmd, harness), cmd
    assert iac("x/.cursor/hooks/session_start.py", "cursor") is False
    assert iac("foo/x/.cursor/hooks/session_start.py", "cursor") is False
    assert iac("pre/$a/b/.cursor/hooks/session_start.py", "cursor") is False
    assert iac("nope", "unknown-harness") is False
    assert _path_prefix_allowed(".cursor/hooks/", 0) is True
    assert _path_prefix_allowed("x/.cursor/hooks/session_start.py", 2) is False
    assert _ALLOWED_PREFIX_SEGS == frozenset({"", ".", ".."})
    assert _SLASH == "/" and _DOLLAR == "$"


def test_wrong_shape_and_merges():
    with pytest.raises(HooksShapeError) as e1:
        merge_cursor_hooks({"hooks": [{"command": "./mine.sh"}]}, {})
    assert str(e1.value) == "cursor: hooks must be an object, got list"
    with pytest.raises(HooksShapeError) as e2:
        merge_cursor_hooks({"hooks": {"sessionStart": {"command": "x"}}}, {})
    assert str(e2.value) == "cursor.sessionStart: event value must be a list, got dict"
    with pytest.raises(HooksShapeError) as e3:
        merge_nested_hooks(
            {"SessionStart": [{"hooks": {"command": "x"}}]}, {}, harness="claude"
        )
    assert str(e3.value) == "claude.SessionStart: block hooks must be a list, got dict"

    desired = {
        "sessionStart": [{"command": ".cursor/hooks/session_start.py"}],
        "preToolUse": [
            {
                "command": ".cursor/hooks/process_guard.py",
                "matcher": "Write|Edit",
            }
        ],
    }
    foreign = {
        "version": 1,
        "hooks": {
            "sessionStart": [
                {"command": "echo foreign-start"},
                {"command": ".cursor/hooks/session_start.py"},
            ],
            "preToolUse": [{"command": "foreign/tool.py", "matcher": "Write"}],
            "customEvent": [{"command": "foreign/custom.py"}],
        },
    }
    out = merge_cursor_hooks(foreign, desired)
    assert out["hooks"]["sessionStart"][0]["command"] == "echo foreign-start"
    assert out["hooks"]["sessionStart"][1]["command"] == ".cursor/hooks/session_start.py"
    assert "agentized" not in out["hooks"]["sessionStart"][1]
    assert out["hooks"]["customEvent"] == [{"command": "foreign/custom.py"}]
    assert out[CURSOR_VERSION_KEY] == 1
    assert (
        merge_cursor_hooks(
            None, {"sessionStart": [{"command": ".cursor/hooks/session_start.py"}]}
        )[CURSOR_VERSION_KEY]
        == 1
    )

    stale = "echo custom-owned"
    before = {"hooks": {"SessionStart": [{"hooks": [{"command": stale}]}]}}
    assert merge_claude_settings(
        before, {"SessionStart": []}, previously_owned=frozenset({stale})
    ) == {"hooks": {}}
    assert merge_claude_settings(before, {"SessionStart": []}, previously_owned=None) == before
    assert merge_codex_hooks(
        before, {"hooks": {}}, previously_owned=frozenset({stale})
    ) == {"hooks": {}}
    assert merge_codex_hooks(before, {"hooks": {}}, previously_owned=None) == before

    claude_desired = {
        "SessionStart": [
            {
                "matcher": "startup",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/session_start.py"'
                        ),
                    }
                ],
            }
        ]
    }
    claude_in = {
        "permissions": {"allow": ["Bash"]},
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup",
                    "hooks": [
                        {"type": "command", "command": "echo foreign-claude"},
                        {
                            "type": "command",
                            "command": (
                                'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/session_start.py"'
                            ),
                        },
                    ],
                }
            ]
        },
    }
    cout = merge_claude_settings(claude_in, claude_desired)
    assert cout["permissions"] == {"allow": ["Bash"]}
    assert cout["hooks"]["SessionStart"][0]["hooks"] == [
        {"type": "command", "command": "echo foreign-claude"}
    ]
    assert merge_claude_settings(None, {}) == {"hooks": {}}

    ours_cmd = ".codex/hooks/session_start.py"
    x_in = {
        "description": "keep-me",
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup",
                    "hooks": [
                        {"type": "command", "command": "echo foreign-codex"},
                        {"type": "command", "command": ours_cmd},
                    ],
                }
            ]
        },
    }
    desired_x = {
        "description": "agentized",
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup",
                    "hooks": [{"type": "command", "command": ours_cmd}],
                }
            ]
        },
    }
    x_out = merge_codex_hooks(x_in, desired_x)
    assert x_out["description"] == "keep-me"
    x_cmds = [
        h.get("command")
        for b in x_out["hooks"]["SessionStart"]
        if isinstance(b, dict)
        for h in b.get("hooks") or []
    ]
    assert x_cmds.count(ours_cmd) == 1 and "echo foreign-codex" in x_cmds
    assert merge_codex_hooks(None, desired_x)["description"] == "agentized"
    assert merge_codex_hooks({"hooks": {}}, "bad") == {"hooks": {}}

    empty = {"matcher": "*", "hooks": []}
    nested = merge_nested_hooks(
        {
            "SessionStart": [
                "not-a-dict",
                empty,
                {"hooks": [{"command": "echo after-empty"}]},
                {"hooks": [{"command": ".claude/hooks/session_start.py"}]},
                {"hooks": [{"command": "echo after-ours"}]},
            ],
            "PreToolUse": [{"hooks": [{"command": "echo foreign-b"}]}],
        },
        {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "command": ".claude/hooks/session_start.py",
                            "type": "command",
                        }
                    ]
                }
            ]
        },
        harness="claude",
    )
    assert nested["SessionStart"][0] == "not-a-dict"
    assert nested["SessionStart"][1] == empty
    assert nested["SessionStart"][2] == {"hooks": [{"command": "echo after-empty"}]}
    assert nested["SessionStart"][3] == {"hooks": [{"command": "echo after-ours"}]}

    market = merge_marketplace_plugins(
        {
            "name": "keep",
            "plugins": [{"name": "foreign"}, {"name": "agentized", "old": 1}],
        },
        {
            "name": "agentized-local",
            "plugins": [{"name": "agentized", "source": {"path": "./x"}}],
        },
    )
    assert market["name"] == "keep"
    assert market["plugins"][0] == {"name": "foreign"}
    assert market["plugins"][1]["source"]["path"] == "./x"
    assert (
        merge_marketplace_plugins(None, {"name": "agentized-local", "plugins": []})[
            "name"
        ]
        == "agentized-local"
    )
    assert (
        merge_marketplace_plugins(
            {"plugins": None}, {"plugins": [{"name": "agentized"}]}
        )["plugins"][0]["name"]
        == "agentized"
    )
    with pytest.raises(HooksShapeError) as em:
        merge_marketplace_plugins({"plugins": {"x": 1}}, {"plugins": []})
    assert str(em.value) == "marketplace: plugins must be a list, got dict"
    with pytest.raises(HooksShapeError) as em2:
        merge_marketplace_plugins({}, {"plugins": {"x": 1}})
    assert str(em2.value) == "marketplace: desired plugins must be a list"
    kept = merge_marketplace_plugins(
        {"plugins": [{"name": 1, "foreign": True}]},
        {"plugins": [{"name": 1}]},
    )
    assert kept["plugins"][0].get("foreign") is True


def test_plan_json_and_collect_owned():
    assert plan_json_change("p", {"a": 1}, {"a": 1}) == {
        "path": "p",
        "action": "skip",
        "changed": False,
        "before_hooks_events": [],
        "after_hooks_events": [],
    }
    assert plan_json_change("p", {}, {"hooks": {"X": []}}) == {
        "path": "p",
        "action": "create",
        "changed": True,
        "before_hooks_events": [],
        "after_hooks_events": ["X"],
    }
    merge = plan_json_change(
        "p", {"hooks": {"A": []}}, {"hooks": {"A": [], "B": []}}
    )
    assert merge["action"] == "merge" and merge["changed"] is True
    assert merge["before_hooks_events"] == ["A"]
    assert merge["after_hooks_events"] == ["A", "B"]

    assert _collect_owned_commands(
        {
            "hooks": {
                "sessionStart": [
                    {"command": ".cursor/hooks/session_start.py"},
                    {"command": "echo foreign"},
                    "skip-me",
                ],
                "bad": "not-list",
            }
        },
        harness="cursor",
    ) == [".cursor/hooks/session_start.py"]
    assert _collect_owned_commands(
        {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {"command": ".claude/hooks/session_start.py"},
                            {"command": "echo foreign"},
                        ]
                    },
                    "skip-block",
                    {"hooks": None},
                ],
                "bad": "not-list",
            }
        },
        harness="claude",
    ) == [".claude/hooks/session_start.py"]
    assert _collect_owned_commands({}, harness="cursor") == []
    assert _collect_owned_commands({"hooks": None}, harness="codex") == []
    assert _collect_owned_commands(
        {
            "hooks": {
                "a": "skip",
                "b": [{"command": ".cursor/hooks/session_start.py"}],
                "c": [{"command": ".cursor/hooks/lease_warn.py"}],
            }
        },
        harness="cursor",
    ) == [".cursor/hooks/session_start.py", ".cursor/hooks/lease_warn.py"]

    with pytest.raises(HooksShapeError) as se2:
        merge_nested_hooks("bad", {}, harness="claude")
    assert str(se2.value) == "claude: hooks must be an object, got str"

    got = merge_codex_hooks(
        {"description": "keep"},
        {
            "description": "new",
            "hooks": {
                "E": [{"hooks": [{"command": ".codex/hooks/session_start.py"}]}]
            },
        },
    )
    assert got["description"] == "keep"
    assert got["hooks"]["E"][0]["hooks"][0]["command"] == ".codex/hooks/session_start.py"
    assert "agentized" not in got["hooks"]["E"][0]["hooks"][0]

    assert _collect_owned_commands(
        {
            "hooks": {
                "a": "skip",
                "b": [{"hooks": [{"command": ".claude/hooks/session_start.py"}]}],
                "c": [{"hooks": [{"command": ".claude/hooks/lease_warn.py"}]}],
            }
        },
        harness="claude",
    ) == [".claude/hooks/session_start.py", ".claude/hooks/lease_warn.py"]

    with pytest.raises(HooksShapeError, match=r"^claude\.E:"):
        merge_nested_hooks({"E": {"x": 1}}, {}, harness="claude")
    assert _collect_owned_commands(
        {
            "hooks": {
                "E": [
                    "skip",
                    {"hooks": [{"command": ".claude/hooks/lease_warn.py"}]},
                ]
            }
        },
        harness="claude",
    ) == [".claude/hooks/lease_warn.py"]
