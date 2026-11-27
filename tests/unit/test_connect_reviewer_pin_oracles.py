"""AGE-68 A-PR (b2): mutation oracles for reviewer pinning in ``connect``.

Tests-only; no runtime change. Targets survivors in
``harness_reviewer_opts``, ``_reviewer_body``, ``_render_reviewer_agent``,
``_render_reviewer_toml`` and ``pin_reviewer_agents``. Every oracle is the
exact full value.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from agentized import connect as connect_mod
from agentized.connect import (
    DEFAULT_HARNESS_REVIEWERS,
    harness_reviewer_opts,
    pin_reviewer_agents,
)
from agentized.managed import load_managed, save_managed

EXTRA = (
    "\n## Caveman / ultracave — **exception**\n\n"
    "You are the **reviewer**. Do **not** use caveman/ultracave compression. Always write\n"
    "**expanded, unambiguous** findings and accept/reject rationale so a human can act\n"
    "without decoding shorthand.\n"
)

CURSOR_DESC = (
    "Independent strong read-only reviewer for Agentized. Use only after gates pass and a "
    "full fix pack or substantial/sensitive change since the last reviewed watermark — "
    "never on tiny format edits. Reports severity findings; never edits, commits, merges, "
    "or approves."
)

DEFAULT_MODEL = "grok-4.7[reasoning_effort=medium]"
SRC_MD = "---\nname: reviewer\nmodel: ignore\nreadonly: true\n---\n\nBody here.\n"
BODY = "Body here.\n" + EXTRA


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _src(tmp_path: Path, text: str, name: str = "src.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _cursor_md(model: str, body: str = BODY) -> str:
    return (
        f"---\nname: reviewer\ndescription: {CURSOR_DESC}\nmodel: {model}\n"
        f"readonly: true\n---\n\n{body}"
    )


def _claude_md(model: str, effort: str, body: str = BODY) -> str:
    return (
        "---\nname: reviewer\n"
        "description: Independent strong read-only reviewer for Agentized.\n"
        f"model: {model}\neffort: {effort}\n"
        f"disallowedTools: Write, Edit, NotebookEdit\n---\n\n{body}"
    )


def _toml(model: str, effort: str, instr: str) -> str:
    return (
        'name = "reviewer"\n'
        'description = "Independent strong read-only reviewer for Agentized. '
        'Reports severity findings; never edits, commits, merges, or approves."\n'
        f'model = "{model}"\n'
        f'model_reasoning_effort = "{effort}"\n'
        'developer_instructions = """\n'
        f"{instr}\n"
        "\n"
        "Hard read-only: never edit files, never commit, never merge, never approve PRs.\n"
        '"""\n'
    )


# ---------------------------------------------------------------- harness_reviewer_opts


@pytest.mark.parametrize(
    ("cfg", "harness", "expected"),
    [
        ({}, "cursor", {"model": DEFAULT_MODEL, "effort": "medium"}),
        ({}, "claude", {"model": "claude-fable-5-2", "effort": "medium"}),
        ({}, "codex", {"model": "gpt-6-astra", "effort": "medium"}),
        ({}, "unknown", {"model": DEFAULT_MODEL, "effort": "medium"}),
        (
            {"model": "legacy-m", "effort": "legacy-e"},
            "unknown",
            {"model": "legacy-m", "effort": "legacy-e"},
        ),
        (
            {"model": "legacy-m"},
            "claude",
            {"model": "legacy-m", "effort": "medium"},
        ),
        (
            {"effort": "legacy-e"},
            "claude",
            {"model": "claude-fable-5-2", "effort": "legacy-e"},
        ),
        (
            {"model": "", "effort": ""},
            "codex",
            {"model": "gpt-6-astra", "effort": "medium"},
        ),
        (
            {"harnesses": {"cursor": {"model": "m1", "effort": "e1"}}, "model": "legacy"},
            "cursor",
            {"model": "m1", "effort": "e1"},
        ),
        (
            {"harnesses": {"cursor": {"model": "m1"}}},
            "cursor",
            {"model": "m1", "effort": "medium"},
        ),
        (
            {"harnesses": {"cursor": {"effort": "e1"}}},
            "cursor",
            {"model": DEFAULT_MODEL, "effort": "e1"},
        ),
        (
            {"harnesses": {"claude": {"model": "m1", "effort": ""}}},
            "claude",
            {"model": "m1", "effort": "medium"},
        ),
        (
            {"harnesses": {"claude": {"model": "", "effort": "e1"}}},
            "claude",
            {"model": "claude-fable-5-2", "effort": "e1"},
        ),
        (
            {"harnesses": {"claude": {"model": 5, "effort": 7}}},
            "claude",
            {"model": "5", "effort": "7"},
        ),
        (
            {"harnesses": {"cursor": {}}, "model": "legacy", "effort": "legacy-e"},
            "cursor",
            {"model": DEFAULT_MODEL, "effort": "medium"},
        ),
        (
            {"harnesses": {"cursor": {"model": "", "effort": ""}}, "model": "legacy"},
            "cursor",
            {"model": DEFAULT_MODEL, "effort": "medium"},
        ),
        (
            {"harnesses": {"cursor": "text"}, "model": "legacy"},
            "cursor",
            {"model": DEFAULT_MODEL, "effort": "medium"},
        ),
        (
            {"harnesses": {"cursor": None}, "model": "legacy"},
            "cursor",
            {"model": DEFAULT_MODEL, "effort": "medium"},
        ),
        (
            {"harnesses": {"codex": {"model": "m1"}}, "model": "legacy", "effort": "legacy-e"},
            "claude",
            {"model": "legacy", "effort": "legacy-e"},
        ),
        (
            {"harnesses": ["cursor"], "model": "legacy", "effort": "legacy-e"},
            "cursor",
            {"model": "legacy", "effort": "legacy-e"},
        ),
        (
            {"harnesses": None, "model": "legacy"},
            "codex",
            {"model": "legacy", "effort": "medium"},
        ),
        (
            {"harnesses": "bogus", "effort": "legacy-e"},
            "codex",
            {"model": "gpt-6-astra", "effort": "legacy-e"},
        ),
        (
            {"harnesses": {"cursor": {"model": "m1"}}, "model": "legacy"},
            "unknown",
            {"model": "legacy", "effort": "medium"},
        ),
    ],
)
def test_harness_reviewer_opts_exact(cfg: dict, harness: str, expected: dict[str, str]):
    assert harness_reviewer_opts(cfg, harness) == expected


def test_harness_reviewer_opts_never_mutates_defaults():
    before = json.loads(json.dumps(DEFAULT_HARNESS_REVIEWERS))
    out = harness_reviewer_opts({"harnesses": {"cursor": {"model": "m", "effort": "e"}}}, "cursor")
    out["model"] = "changed"
    assert DEFAULT_HARNESS_REVIEWERS == before
    assert harness_reviewer_opts({}, "cursor") == {"model": DEFAULT_MODEL, "effort": "medium"}


# ---------------------------------------------------------------- _reviewer_body


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("---\nname: r\n---\n\nBody here.\n", "Body here.\n" + EXTRA),
        ("---\nname: r\n---\nBody here.\n", "Body here.\n" + EXTRA),
        ("---\nname: r\n---\n\n\n\nBody here.\n", "Body here.\n" + EXTRA),
        ("  ---  \nname: r\n\t---\t\nBody here.\n", "Body here.\n" + EXTRA),
        ("---\n---\nBody here.\n", "Body here.\n" + EXTRA),
        ("---\nfirst: 1\n---\nBody\n---\nrest\n", "Body\n---\nrest\n" + EXTRA),
        ("---\nname: r\nBody here.\n", "---\nname: r\nBody here.\n" + EXTRA),
        ("Body here.\n", "Body here.\n" + EXTRA),
        ("Body here.\n\n\n", "Body here.\n" + EXTRA),
        ("\n\nBody here.\n", "\n\nBody here.\n" + EXTRA),
        ("", "\n" + EXTRA),
        ("# Caveman / ultracave note\nBody\n", "# Caveman / ultracave note\nBody\n"),
        (
            "---\nname: r\n---\n\nCaveman / ultracave inside\n",
            "Caveman / ultracave inside",
        ),
        (
            "---\nname: r\n---\n\nBody\n\n\nCaveman / ultracave\n\n",
            "Body\n\n\nCaveman / ultracave\n",
        ),
        ("Caveman / ultracave \n\n\n", "Caveman / ultracave \n\n\n"),
        ("Intro Caveman / ultracave outro", "Intro Caveman / ultracave outro"),
        ("caveman / ultracave lower\n", "caveman / ultracave lower\n" + EXTRA),
        ("Caveman  / ultracave\n", "Caveman  / ultracave\n" + EXTRA),
        ("Тело — ревью\n", "Тело — ревью\n" + EXTRA),
        ("---\n---\n  Xindented\n", "  Xindented\n" + EXTRA),
        ("---\n---\n\n\nXbody\n", "Xbody\n" + EXTRA),
        ("---\n---\n\t\n Xtab\n", "\t\n Xtab\n" + EXTRA),
    ],
)
def test_reviewer_body_exact(tmp_path: Path, text: str, expected: str):
    assert connect_mod._reviewer_body(_src(tmp_path, text)) == expected


def test_reviewer_body_reads_utf8_regardless_of_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    src = _src(tmp_path, "---\nname: r\n---\n\nТело — ревью\n")
    real_read_text = Path.read_text

    def ascii_locale_read_text(self: Path, encoding: str | None = None, **kwargs: Any) -> str:
        return real_read_text(self, encoding="ascii" if encoding is None else encoding, **kwargs)

    monkeypatch.setattr(Path, "read_text", ascii_locale_read_text)
    assert connect_mod._reviewer_body(src) == "Тело — ревью\n" + EXTRA


def test_reviewer_body_extra_constant_is_exact():
    assert connect_mod.REVIEWER_BODY_EXTRA == EXTRA


# ---------------------------------------------------------------- _render_reviewer_agent


def test_render_agent_cursor_default_harness(tmp_path: Path):
    src = _src(tmp_path, SRC_MD)
    assert connect_mod._render_reviewer_agent(src, "m-1") == _cursor_md("m-1")


def test_render_agent_cursor_ignores_effort(tmp_path: Path):
    src = _src(tmp_path, SRC_MD)
    out = connect_mod._render_reviewer_agent(src, "m-2", harness="cursor", effort="high")
    assert out == _cursor_md("m-2")


def test_render_agent_claude_default_effort(tmp_path: Path):
    src = _src(tmp_path, SRC_MD)
    out = connect_mod._render_reviewer_agent(src, "m-3", harness="claude")
    assert out == _claude_md("m-3", "medium")


def test_render_agent_claude_explicit_effort(tmp_path: Path):
    src = _src(tmp_path, SRC_MD)
    out = connect_mod._render_reviewer_agent(src, "m-4", harness="claude", effort="high")
    assert out == _claude_md("m-4", "high")


def test_render_agent_other_harness_takes_cursor_shape(tmp_path: Path):
    src = _src(tmp_path, SRC_MD)
    out = connect_mod._render_reviewer_agent(src, "m-5", harness="codex", effort="high")
    assert out == _cursor_md("m-5")


def test_render_agent_strips_leading_blank_lines_of_body(tmp_path: Path):
    src = _src(tmp_path, "\n\n\nPlain body.\n")
    body = "Plain body.\n" + EXTRA
    assert connect_mod._render_reviewer_agent(src, "m") == _cursor_md("m", body)
    assert connect_mod._render_reviewer_agent(src, "m", harness="claude") == _claude_md(
        "m", "medium", body
    )


def test_render_agent_keeps_leading_spaces_and_x_of_body(tmp_path: Path):
    src = _src(tmp_path, "\n\n   Xindented first\n")
    body = "   Xindented first\n" + EXTRA
    assert connect_mod._render_reviewer_agent(src, "m") == _cursor_md("m", body)
    src2 = _src(tmp_path, "\nXray first\n", "src2.md")
    body2 = "Xray first\n" + EXTRA
    assert connect_mod._render_reviewer_agent(src2, "m", harness="claude") == _claude_md(
        "m", "medium", body2
    )


def test_render_agent_body_with_caveman_marker_kept_verbatim(tmp_path: Path):
    src = _src(tmp_path, "---\nname: r\n---\n\nCaveman / ultracave stays\n")
    assert connect_mod._render_reviewer_agent(src, "m") == _cursor_md(
        "m", "Caveman / ultracave stays"
    )


# ---------------------------------------------------------------- _render_reviewer_toml


def test_render_toml_exact_plain(tmp_path: Path):
    src = _src(tmp_path, SRC_MD)
    out = connect_mod._render_reviewer_toml(src, "gpt-x", "high")
    assert out == _toml("gpt-x", "high", BODY.rstrip())


def test_render_toml_escapes_backslash_and_triple_quotes(tmp_path: Path):
    src = _src(tmp_path, 'Path C:\\dir and """triple""" and \\""" end\nCaveman / ultracave\n')
    out = connect_mod._render_reviewer_toml(src, "m", "low")
    instr = 'Path C:\\\\dir and \\"""triple\\""" and \\\\\\""" end\nCaveman / ultracave'
    assert out == _toml("m", "low", instr)


def test_render_toml_single_quote_chars_untouched(tmp_path: Path):
    src = _src(tmp_path, "He said \"hi\" and 'yo'\nCaveman / ultracave\n")
    out = connect_mod._render_reviewer_toml(src, "m", "low")
    assert out == _toml("m", "low", "He said \"hi\" and 'yo'\nCaveman / ultracave")


def test_render_toml_trailing_whitespace_trimmed_once(tmp_path: Path):
    src = _src(tmp_path, "---\nname: r\n---\n\nTail   \n\n\nCaveman / ultracave  \n\n\n")
    out = connect_mod._render_reviewer_toml(src, "m", "e")
    assert out == _toml("m", "e", "Tail   \n\n\nCaveman / ultracave")


# ---------------------------------------------------------------- pin_reviewer_agents


def _agents_src(root: Path, text: str = SRC_MD) -> None:
    agents = root / "packages" / "shared" / "agents"
    agents.mkdir(parents=True)
    (agents / "reviewer.md").write_text(text, encoding="utf-8")


def _paths(root: Path, ctx: str = "context") -> dict[str, Path]:
    return {
        "ctx": root / ctx / "agents" / "reviewer.md",
        "cursor": root / ".cursor" / "agents" / "reviewer.md",
        "claude": root / ".claude" / "agents" / "reviewer.md",
        "toml": root / ".codex" / "agents" / "reviewer.toml",
    }


def _load_quality_returning(value: dict[str, Any]):
    return mock.patch("agentized.quality.load_quality", return_value=value)


def test_pin_reviewer_missing_src_returns_exact(tmp_path: Path):
    (tmp_path / "packages" / "shared" / "agents").mkdir(parents=True)
    assert pin_reviewer_agents(tmp_path, "context") == {
        "installed": [],
        "skipped": "missing-src",
    }
    assert sorted(p.name for p in tmp_path.iterdir()) == ["packages"]


def test_pin_reviewer_fresh_default_config_exact(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({"reviewer": {}}):
        result = pin_reviewer_agents(tmp_path, "context")
    p = _paths(tmp_path)
    assert result == {
        "installed": [str(p["ctx"]), str(p["cursor"]), str(p["claude"]), str(p["toml"])],
        "models": {
            "cursor": DEFAULT_MODEL,
            "claude": "claude-fable-5-2",
            "codex": "gpt-6-astra",
        },
        "model": DEFAULT_MODEL,
    }
    cursor_text = _cursor_md(DEFAULT_MODEL)
    claude_text = _claude_md("claude-fable-5-2", "medium")
    toml_text = _toml("gpt-6-astra", "medium", BODY.rstrip())
    assert p["ctx"].read_text(encoding="utf-8") == cursor_text
    assert p["cursor"].read_text(encoding="utf-8") == cursor_text
    assert p["claude"].read_text(encoding="utf-8") == claude_text
    assert p["toml"].read_text(encoding="utf-8") == toml_text
    assert (tmp_path / ".codex" / "agents").is_dir()
    assert sorted(x.name for x in (tmp_path / ".codex" / "agents").iterdir()) == ["reviewer.toml"]


def test_pin_reviewer_custom_reviewer_section_drives_models_and_efforts(tmp_path: Path):
    _agents_src(tmp_path)
    cfg = {
        "reviewer": {
            "harnesses": {
                "cursor": {"model": "cm", "effort": "ce"},
                "claude": {"model": "lm", "effort": "le"},
                "codex": {"model": "xm", "effort": "xe"},
            }
        }
    }
    with _load_quality_returning(cfg):
        result = pin_reviewer_agents(tmp_path, "context")
    p = _paths(tmp_path)
    assert result["models"] == {"cursor": "cm", "claude": "lm", "codex": "xm"}
    assert result["model"] == "cm"
    assert p["cursor"].read_text(encoding="utf-8") == _cursor_md("cm")
    assert p["ctx"].read_text(encoding="utf-8") == _cursor_md("cm")
    assert p["claude"].read_text(encoding="utf-8") == _claude_md("lm", "le")
    assert p["toml"].read_text(encoding="utf-8") == _toml("xm", "xe", BODY.rstrip())


def test_pin_reviewer_null_reviewer_section_falls_back_to_defaults(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({"reviewer": None}):
        result = pin_reviewer_agents(tmp_path, "context")
    assert result["models"] == {
        "cursor": DEFAULT_MODEL,
        "claude": "claude-fable-5-2",
        "codex": "gpt-6-astra",
    }


def test_pin_reviewer_missing_reviewer_key_falls_back_to_defaults(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({}):
        result = pin_reviewer_agents(tmp_path, "context")
    assert result["models"] == {
        "cursor": DEFAULT_MODEL,
        "claude": "claude-fable-5-2",
        "codex": "gpt-6-astra",
    }


def test_pin_reviewer_reads_quality_for_given_context(tmp_path: Path):
    _agents_src(tmp_path)
    for rel, model in (("context", "wrong-codex"), ("ctx/deep", "deep-codex")):
        cfg_path = tmp_path / rel / "quality.json"
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(
            json.dumps({"reviewer": {"harnesses": {"codex": {"model": model}}}}),
            encoding="utf-8",
        )
    result = pin_reviewer_agents(tmp_path, "ctx/deep")
    assert result["models"] == {
        "cursor": DEFAULT_MODEL,
        "claude": "claude-fable-5-2",
        "codex": "deep-codex",
    }


def test_pin_reviewer_real_quality_json_roundtrip(tmp_path: Path):
    _agents_src(tmp_path)
    (tmp_path / "context").mkdir()
    cfg_path = tmp_path / "context" / "quality.json"
    cfg_path.write_text(
        json.dumps({"reviewer": {"harnesses": {"codex": {"model": "q-codex"}}}}),
        encoding="utf-8",
    )
    result = pin_reviewer_agents(tmp_path, "context")
    assert result["models"]["codex"] == "q-codex"
    assert _paths(tmp_path)["toml"].read_text(encoding="utf-8") == _toml(
        "q-codex", "medium", BODY.rstrip()
    )


def test_pin_reviewer_saves_manifest_when_not_passed(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({"reviewer": {}}):
        pin_reviewer_agents(tmp_path, "context")
    saved = json.loads(
        (tmp_path / "context" / ".agentized" / "managed.json").read_text(encoding="utf-8")
    )
    assert saved == {
        "version": 1,
        "files": {
            ".claude/agents/reviewer.md": _sha(_claude_md("claude-fable-5-2", "medium")),
            ".codex/agents/reviewer.toml": _sha(_toml("gpt-6-astra", "medium", BODY.rstrip())),
            ".cursor/agents/reviewer.md": _sha(_cursor_md(DEFAULT_MODEL)),
            "context/agents/reviewer.md": _sha(_cursor_md(DEFAULT_MODEL)),
        },
    }


def test_pin_reviewer_passed_manifest_filled_not_saved(tmp_path: Path):
    _agents_src(tmp_path)
    man: dict[str, Any] = {"version": 1, "files": {}}
    with _load_quality_returning({"reviewer": {}}):
        pin_reviewer_agents(tmp_path, "context", manifest=man)
    assert man == {
        "version": 1,
        "files": {
            ".claude/agents/reviewer.md": _sha(_claude_md("claude-fable-5-2", "medium")),
            ".codex/agents/reviewer.toml": _sha(_toml("gpt-6-astra", "medium", BODY.rstrip())),
            ".cursor/agents/reviewer.md": _sha(_cursor_md(DEFAULT_MODEL)),
            "context/agents/reviewer.md": _sha(_cursor_md(DEFAULT_MODEL)),
        },
    }
    assert (tmp_path / "context" / ".agentized" / "managed.json").exists() is False


def test_pin_reviewer_loads_existing_manifest_from_context(tmp_path: Path):
    _agents_src(tmp_path)
    save_managed(tmp_path, "context", {"version": 1, "files": {"keep/me.txt": "abc"}})
    with _load_quality_returning({"reviewer": {}}):
        pin_reviewer_agents(tmp_path, "context")
    files = load_managed(tmp_path, "context")["files"]
    assert files["keep/me.txt"] == "abc"
    assert sorted(files) == [
        ".claude/agents/reviewer.md",
        ".codex/agents/reviewer.toml",
        ".cursor/agents/reviewer.md",
        "context/agents/reviewer.md",
        "keep/me.txt",
    ]


def test_pin_reviewer_nested_context_rel_creates_parents(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({"reviewer": {}}):
        result = pin_reviewer_agents(tmp_path, "ctx/deep")
    p = _paths(tmp_path, "ctx/deep")
    assert result["installed"][0] == str(p["ctx"])
    assert p["ctx"].read_text(encoding="utf-8") == _cursor_md(DEFAULT_MODEL)
    assert (tmp_path / "ctx" / "deep" / ".agentized" / "managed.json").is_file()


def test_pin_reviewer_second_run_reports_unchanged_as_installed(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({"reviewer": {}}):
        first = pin_reviewer_agents(tmp_path, "context")
        second = pin_reviewer_agents(tmp_path, "context")
    assert second == first


def test_pin_reviewer_removes_stale_codex_md_before_toml(tmp_path: Path):
    _agents_src(tmp_path)
    codex = tmp_path / ".codex" / "agents"
    codex.mkdir(parents=True)
    (codex / "reviewer.md").write_text("stale\n", encoding="utf-8")
    with _load_quality_returning({"reviewer": {}}):
        result = pin_reviewer_agents(tmp_path, "context")
    p = _paths(tmp_path)
    assert result["installed"] == [
        str(p["ctx"]),
        str(p["cursor"]),
        str(p["claude"]),
        f"removed:{codex / 'reviewer.md'}",
        str(p["toml"]),
    ]
    assert (codex / "reviewer.md").exists() is False


def test_pin_reviewer_user_edit_is_skipped_and_listed(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({"reviewer": {}}):
        pin_reviewer_agents(tmp_path, "context")
    p = _paths(tmp_path)
    p["claude"].write_text("my edit\n", encoding="utf-8")
    p["toml"].write_text("my toml\n", encoding="utf-8")
    with _load_quality_returning({"reviewer": {"harnesses": {"cursor": {"model": "new-m"}}}}):
        result = pin_reviewer_agents(tmp_path, "context")
    assert result == {
        "installed": [str(p["ctx"]), str(p["cursor"])],
        "models": {
            "cursor": "new-m",
            "claude": "claude-fable-5-2",
            "codex": "gpt-6-astra",
        },
        "model": "new-m",
        "skipped_user": [str(p["claude"]), str(p["toml"])],
    }
    assert p["claude"].read_text(encoding="utf-8") == "my edit\n"
    assert p["toml"].read_text(encoding="utf-8") == "my toml\n"
    assert p["cursor"].read_text(encoding="utf-8") == _cursor_md("new-m")
    assert p["ctx"].read_text(encoding="utf-8") == _cursor_md("new-m")


def test_pin_reviewer_force_overwrites_user_edit(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({"reviewer": {}}):
        pin_reviewer_agents(tmp_path, "context")
    p = _paths(tmp_path)
    p["claude"].write_text("my edit\n", encoding="utf-8")
    with _load_quality_returning({"reviewer": {}}):
        result = pin_reviewer_agents(tmp_path, "context", force=True)
    assert result["installed"] == [
        str(p["ctx"]),
        str(p["cursor"]),
        str(p["claude"]),
        str(p["toml"]),
    ]
    assert p["claude"].read_text(encoding="utf-8") == _claude_md("claude-fable-5-2", "medium")


def test_pin_reviewer_bootstraps_legacy_files_without_manifest(tmp_path: Path):
    _agents_src(tmp_path)
    p = _paths(tmp_path)
    for key in ("cursor", "claude"):
        p[key].parent.mkdir(parents=True)
        p[key].write_text(f"legacy {key}\n", encoding="utf-8")
    with _load_quality_returning({"reviewer": {}}):
        result = pin_reviewer_agents(tmp_path, "context")
    assert result == {
        "installed": [str(p["ctx"]), str(p["cursor"]), str(p["claude"]), str(p["toml"])],
        "models": {
            "cursor": DEFAULT_MODEL,
            "claude": "claude-fable-5-2",
            "codex": "gpt-6-astra",
        },
        "model": DEFAULT_MODEL,
        "bootstrapped": [str(p["cursor"]), str(p["claude"])],
    }
    assert p["cursor"].read_text(encoding="utf-8") == "legacy cursor\n"
    assert p["claude"].read_text(encoding="utf-8") == "legacy claude\n"
    files = load_managed(tmp_path, "context")["files"]
    assert files[".cursor/agents/reviewer.md"] == _sha("legacy cursor\n")
    assert files[".claude/agents/reviewer.md"] == _sha("legacy claude\n")


def test_pin_reviewer_skipped_and_bootstrapped_together(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({"reviewer": {}}):
        pin_reviewer_agents(tmp_path, "context")
    p = _paths(tmp_path)
    p["cursor"].write_text("user cursor\n", encoding="utf-8")
    man = load_managed(tmp_path, "context")
    del man["files"][".claude/agents/reviewer.md"]
    p["claude"].write_text("legacy claude\n", encoding="utf-8")
    save_managed(tmp_path, "context", man)
    with _load_quality_returning({"reviewer": {}}):
        result = pin_reviewer_agents(tmp_path, "context")
    assert result == {
        "installed": [str(p["ctx"]), str(p["claude"]), str(p["toml"])],
        "models": {
            "cursor": DEFAULT_MODEL,
            "claude": "claude-fable-5-2",
            "codex": "gpt-6-astra",
        },
        "model": DEFAULT_MODEL,
        "skipped_user": [str(p["cursor"])],
        "bootstrapped": [str(p["claude"])],
    }


def test_pin_reviewer_updates_untouched_pin_when_source_changes(tmp_path: Path):
    _agents_src(tmp_path)
    with _load_quality_returning({"reviewer": {}}):
        pin_reviewer_agents(tmp_path, "context")
    (tmp_path / "packages" / "shared" / "agents" / "reviewer.md").write_text(
        "---\nname: r\n---\n\nNew body.\n", encoding="utf-8"
    )
    with _load_quality_returning({"reviewer": {}}):
        result = pin_reviewer_agents(tmp_path, "context")
    p = _paths(tmp_path)
    body = "New body.\n" + EXTRA
    assert result["installed"] == [
        str(p["ctx"]),
        str(p["cursor"]),
        str(p["claude"]),
        str(p["toml"]),
    ]
    assert p["cursor"].read_text(encoding="utf-8") == _cursor_md(DEFAULT_MODEL, body)
    assert p["toml"].read_text(encoding="utf-8") == _toml("gpt-6-astra", "medium", body.rstrip())


def test_pin_reviewer_uses_installed_agents_when_target_has_no_packages(tmp_path: Path):
    installed = tmp_path / "installed"
    (installed / "packages" / "shared" / "agents").mkdir(parents=True)
    (installed / "packages" / "shared" / "agents" / "reviewer.md").write_text(
        SRC_MD, encoding="utf-8"
    )
    target = tmp_path / "target"
    target.mkdir()
    with (
        mock.patch.object(connect_mod, "installed_agentized_root", return_value=installed),
        _load_quality_returning({"reviewer": {}}),
    ):
        result = pin_reviewer_agents(target, "context")
    assert result["installed"][1] == str(target / ".cursor" / "agents" / "reviewer.md")
    assert (target / ".cursor" / "agents" / "reviewer.md").read_text(
        encoding="utf-8"
    ) == _cursor_md(DEFAULT_MODEL)
