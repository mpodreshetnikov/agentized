"""AGE-68 A-tests: mutation oracles for connect config/marker helpers.

Tests-only; no runtime change. Targets survivors on
``_upsert_marked_block``, ``ensure_env_check_config`` and
``ensure_quality_config`` (leftovers not owned by the AGE-95 connect/pin work).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentized.connect import (
    _upsert_marked_block,
    ensure_env_check_config,
    ensure_quality_config,
)
from agentized.quality import load_quality, save_quality

BEGIN = "<!-- B -->"
END = "<!-- E -->"


def _spy_text_io(monkeypatch: pytest.MonkeyPatch) -> tuple[list, list]:
    """Record the ``encoding`` argument of every Path read_text / write_text call."""
    reads: list[str | None] = []
    writes: list[str | None] = []
    real_r = Path.read_text
    real_w = Path.write_text

    def wrap_r(self: Path, encoding: str | None = None, **kwargs):
        reads.append(encoding)
        return real_r(self, encoding=encoding, **kwargs)

    def wrap_w(self: Path, data: str, encoding: str | None = None, **kwargs):
        writes.append(encoding)
        return real_w(self, data, encoding=encoding, **kwargs)

    monkeypatch.setattr(Path, "read_text", wrap_r)
    monkeypatch.setattr(Path, "write_text", wrap_w)
    return reads, writes


# ---------------------------------------------------------------------------
# _upsert_marked_block
# ---------------------------------------------------------------------------


def test_upsert_missing_file_without_create_is_noop(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    assert _upsert_marked_block(path, BEGIN, END, "body", create=False) is False
    assert not path.exists()


def test_upsert_missing_file_with_create_writes_rstripped_body_once(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    body = f"{BEGIN}\nпривет\n{END}  \n\n\n"
    assert _upsert_marked_block(path, BEGIN, END, body, create=True) is True
    assert path.read_bytes() == f"{BEGIN}\nпривет\n{END}\n".encode("utf-8")


def test_upsert_create_does_not_strip_leading_whitespace(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    assert _upsert_marked_block(path, BEGIN, END, "\n  lead\n", create=True) is True
    assert path.read_text(encoding="utf-8") == "\n  lead\n"


def test_upsert_replaces_block_between_markers_keeping_head_and_tail(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"head\n\n{BEGIN}\nold\n{END}\ntail\n", encoding="utf-8")
    new = f"{BEGIN}\nnew\n{END}\n"
    assert _upsert_marked_block(path, BEGIN, END, new, create=False) is True
    assert path.read_text(encoding="utf-8") == f"head\n\n{BEGIN}\nnew\n{END}\ntail\n"


def test_upsert_replace_normalises_whitespace_around_block(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"head   \n\n\n{BEGIN}\nold\n{END}\n\n\n  tail\n", encoding="utf-8")
    new = f"{BEGIN}\nnew\n{END}\n\n\n"
    assert _upsert_marked_block(path, BEGIN, END, new, create=False) is True
    assert path.read_text(encoding="utf-8") == f"head\n\n{BEGIN}\nnew\n{END}\n  tail\n"


def test_upsert_replace_adds_trailing_newline_when_tail_has_none(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"head\n{BEGIN}\nold\n{END} tail", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, f"{BEGIN}\nnew\n{END}", create=False) is True
    assert path.read_text(encoding="utf-8") == f"head\n\n{BEGIN}\nnew\n{END}\n tail\n"


def test_upsert_replace_block_at_end_of_file(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"head\n{BEGIN}\nold\n{END}\n", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, f"{BEGIN}\nnew\n{END}\n", create=False) is True
    assert path.read_text(encoding="utf-8") == f"head\n\n{BEGIN}\nnew\n{END}\n"


def test_upsert_replace_block_at_start_of_file(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"{BEGIN}\nold\n{END}\ntail\n", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, f"{BEGIN}\nnew\n{END}\n", create=False) is True
    assert path.read_text(encoding="utf-8") == f"\n\n{BEGIN}\nnew\n{END}\ntail\n"


def test_upsert_splits_on_first_end_marker_after_first_begin(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"a\n{BEGIN}\nx\n{END}\nmid\n{END}\nz\n", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, f"{BEGIN}\nn\n{END}\n", create=False) is True
    assert path.read_text(encoding="utf-8") == f"a\n\n{BEGIN}\nn\n{END}\nmid\n{END}\nz\n"


def test_upsert_unchanged_returns_false_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "AGENTS.md"
    text = f"head\n\n{BEGIN}\nsame\n{END}\ntail\n"
    path.write_text(text, encoding="utf-8")
    reads, writes = _spy_text_io(monkeypatch)
    assert _upsert_marked_block(path, BEGIN, END, f"{BEGIN}\nsame\n{END}\n", create=False) is False
    assert reads == ["utf-8"]
    assert writes == []
    assert path.read_text(encoding="utf-8") == text


def test_upsert_only_begin_marker_appends_instead_of_replacing(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"keep\n{BEGIN}\nhalf\n", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, f"{BEGIN}\nnew\n{END}\n", create=False) is True
    assert path.read_text(encoding="utf-8") == f"keep\n{BEGIN}\nhalf\n\n{BEGIN}\nnew\n{END}\n"


def test_upsert_only_end_marker_appends_instead_of_replacing(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"keep\nhalf\n{END}\n", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, f"{BEGIN}\nnew\n{END}\n", create=False) is True
    assert path.read_text(encoding="utf-8") == f"keep\nhalf\n{END}\n\n{BEGIN}\nnew\n{END}\n"


def test_upsert_appends_after_rstripped_text_without_markers(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text("keep  \n\n\n", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, "BODY  \n\n", create=False) is True
    assert path.read_text(encoding="utf-8") == "keep\n\nBODY\n"


def test_upsert_append_on_create_true_for_existing_file(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text("keep\n", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, "BODY", create=True) is True
    assert path.read_text(encoding="utf-8") == "keep\n\nBODY\n"


def test_upsert_all_text_io_is_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    create_path = tmp_path / "create.md"
    replace_path = tmp_path / "replace.md"
    append_path = tmp_path / "append.md"
    replace_path.write_text(f"{BEGIN}\nстарый\n{END}\n", encoding="utf-8")
    append_path.write_text("текст\n", encoding="utf-8")
    reads, writes = _spy_text_io(monkeypatch)
    assert _upsert_marked_block(create_path, BEGIN, END, "новый", create=True) is True
    assert reads == []
    assert writes == ["utf-8"]
    assert _upsert_marked_block(replace_path, BEGIN, END, f"{BEGIN}\nновый\n{END}\n", create=False)
    assert reads == ["utf-8"]
    assert writes == ["utf-8", "utf-8"]
    assert _upsert_marked_block(append_path, BEGIN, END, "новый", create=False) is True
    assert reads == ["utf-8", "utf-8"]
    assert writes == ["utf-8", "utf-8", "utf-8"]
    assert create_path.read_text(encoding="utf-8") == "новый\n"
    assert replace_path.read_text(encoding="utf-8") == f"\n\n{BEGIN}\nновый\n{END}\n"
    assert append_path.read_text(encoding="utf-8") == "текст\n\nновый\n"


# ---------------------------------------------------------------------------
# ensure_env_check_config
# ---------------------------------------------------------------------------

ENV_CHECK_JSON = (
    '{\n  "version": 1,\n  "cloud_git_hooks": "warn",\n  "unknown_agent": "refuse"\n}\n'
)


def test_env_check_creates_default_file_exact_text_and_result(tmp_path: Path):
    (tmp_path / "context").mkdir()
    info = ensure_env_check_config(tmp_path, "context")
    assert info == {"path": "context/env-check.json", "created": True}
    assert (tmp_path / "context" / "env-check.json").read_bytes() == ENV_CHECK_JSON.encode("utf-8")


def test_env_check_creates_nested_context_dir(tmp_path: Path):
    info = ensure_env_check_config(tmp_path, "deep/nested/ctx")
    assert info == {"path": "deep/nested/ctx/env-check.json", "created": True}
    written = tmp_path / "deep" / "nested" / "ctx" / "env-check.json"
    assert written.read_text(encoding="utf-8") == ENV_CHECK_JSON


def test_env_check_mkdir_uses_parents_and_exist_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    seen: list[tuple[str, dict]] = []
    real = Path.mkdir

    def wrapped(self: Path, *args, **kwargs):
        seen.append((self.name, dict(kwargs)))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", wrapped)
    (tmp_path / "context").mkdir()
    seen.clear()
    ensure_env_check_config(tmp_path, "context")
    assert seen == [("context", {"parents": True, "exist_ok": True})]


def test_env_check_existing_file_is_never_clobbered(tmp_path: Path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    custom = '{"cloud_git_hooks": "refuse"}'
    (ctx / "env-check.json").write_text(custom, encoding="utf-8")
    info = ensure_env_check_config(tmp_path, "context")
    assert info == {"path": "context/env-check.json", "created": False}
    assert (ctx / "env-check.json").read_text(encoding="utf-8") == custom


def test_env_check_write_is_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reads, writes = _spy_text_io(monkeypatch)
    ensure_env_check_config(tmp_path, "context")
    assert reads == []
    assert writes == ["utf-8"]


# ---------------------------------------------------------------------------
# ensure_quality_config
# ---------------------------------------------------------------------------


def test_quality_created_result_and_default_file(tmp_path: Path):
    (tmp_path / "context").mkdir()
    info = ensure_quality_config(tmp_path, "context")
    assert info == {
        "path": "context/quality.json",
        "created": True,
        "coverage_pct": None,
        "upgraded_modes": [],
    }
    saved = json.loads((tmp_path / "context" / "quality.json").read_text(encoding="utf-8"))
    assert saved == load_quality(tmp_path, "context")
    assert saved["coverage"] == {"lines": 80.0, "branches": 80.0}
    assert saved["test_smells"]["mode"] == "hard"
    assert saved["architecture"]["mode"] == "hard"


def test_quality_created_with_coverage_sets_both_thresholds(tmp_path: Path):
    (tmp_path / "context").mkdir()
    info = ensure_quality_config(tmp_path, "context", coverage_pct=88.5)
    assert info == {
        "path": "context/quality.json",
        "created": True,
        "coverage_pct": 88.5,
        "upgraded_modes": [],
    }
    assert load_quality(tmp_path, "context")["coverage"] == {"lines": 88.5, "branches": 88.5}


def test_quality_zero_coverage_is_applied_not_skipped(tmp_path: Path):
    (tmp_path / "context").mkdir()
    info = ensure_quality_config(tmp_path, "context", coverage_pct=0)
    assert info["coverage_pct"] == 0
    assert load_quality(tmp_path, "context")["coverage"] == {"lines": 0.0, "branches": 0.0}


def test_quality_created_in_nested_context_uses_context_rel(tmp_path: Path):
    info = ensure_quality_config(tmp_path, "deep/ctx", coverage_pct=70)
    assert info["path"] == "deep/ctx/quality.json"
    assert load_quality(tmp_path, "deep/ctx")["coverage"] == {"lines": 70.0, "branches": 70.0}
    assert not (tmp_path / "context").exists()


def test_quality_existing_without_warn_is_not_rewritten(tmp_path: Path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    raw = '{"coverage":{"lines":90,"branches":91},"test_smells":{"mode":"hard"},"architecture":{"mode":"off"}}'
    (ctx / "quality.json").write_text(raw, encoding="utf-8")
    info = ensure_quality_config(tmp_path, "context")
    assert info == {
        "path": "context/quality.json",
        "created": False,
        "coverage_pct": None,
        "upgraded_modes": [],
    }
    assert (ctx / "quality.json").read_text(encoding="utf-8") == raw


def test_quality_upgrades_only_warn_smells_and_keeps_architecture_off(tmp_path: Path):
    save_quality(
        tmp_path,
        {
            "coverage": {"lines": 77, "branches": 66},
            "test_smells": {"mode": "warn"},
            "architecture": {"mode": "off"},
        },
        "context",
    )
    info = ensure_quality_config(tmp_path, "context")
    assert info["upgraded_modes"] == ["test_smells"]
    cfg = load_quality(tmp_path, "context")
    assert cfg["test_smells"]["mode"] == "hard"
    assert cfg["architecture"]["mode"] == "off"
    assert cfg["coverage"] == {"lines": 77.0, "branches": 66.0}


def test_quality_upgrades_only_warn_architecture_and_keeps_smells_hard(tmp_path: Path):
    save_quality(
        tmp_path,
        {"test_smells": {"mode": "hard"}, "architecture": {"mode": "warn", "tool": "builtin"}},
        "context",
    )
    info = ensure_quality_config(tmp_path, "context")
    assert info["upgraded_modes"] == ["architecture"]
    cfg = load_quality(tmp_path, "context")
    assert cfg["test_smells"]["mode"] == "hard"
    assert cfg["architecture"]["mode"] == "hard"
    assert cfg["architecture"]["tool"] == "builtin"


def test_quality_upgrade_order_and_case_insensitive_warn(tmp_path: Path):
    save_quality(
        tmp_path,
        {"test_smells": {"mode": "WARN"}, "architecture": {"mode": "Warn"}},
        "context",
    )
    info = ensure_quality_config(tmp_path, "context")
    assert info["upgraded_modes"] == ["test_smells", "architecture"]
    cfg = load_quality(tmp_path, "context")
    assert cfg["test_smells"]["mode"] == "hard"
    assert cfg["architecture"]["mode"] == "hard"


def test_quality_null_mode_is_not_treated_as_warn(tmp_path: Path):
    ctx = tmp_path / "context"
    ctx.mkdir()
    raw = '{"test_smells":{"mode":null},"architecture":{"mode":null}}'
    (ctx / "quality.json").write_text(raw, encoding="utf-8")
    info = ensure_quality_config(tmp_path, "context")
    assert info["upgraded_modes"] == []
    assert (ctx / "quality.json").read_text(encoding="utf-8") == raw


def test_quality_upgrade_then_coverage_applies_both(tmp_path: Path):
    save_quality(tmp_path, {"test_smells": {"mode": "warn"}}, "context")
    info = ensure_quality_config(tmp_path, "context", coverage_pct=91)
    assert info == {
        "path": "context/quality.json",
        "created": False,
        "coverage_pct": 91,
        "upgraded_modes": ["test_smells"],
    }
    cfg = load_quality(tmp_path, "context")
    assert cfg["test_smells"]["mode"] == "hard"
    assert cfg["coverage"] == {"lines": 91.0, "branches": 91.0}


def test_quality_existing_coverage_only_updates_thresholds(tmp_path: Path):
    save_quality(tmp_path, {"coverage": {"lines": 50, "branches": 40}}, "context")
    info = ensure_quality_config(tmp_path, "context", coverage_pct=95)
    assert info["created"] is False
    assert info["upgraded_modes"] == []
    assert load_quality(tmp_path, "context")["coverage"] == {"lines": 95.0, "branches": 95.0}


def test_quality_create_ignores_default_context_quality_for_other_context_rel(tmp_path: Path):
    save_quality(tmp_path, {"coverage": {"lines": 55, "branches": 55}}, "context")
    info = ensure_quality_config(tmp_path, "ctx2")
    assert info == {
        "path": "ctx2/quality.json",
        "created": True,
        "coverage_pct": None,
        "upgraded_modes": [],
    }
    assert load_quality(tmp_path, "ctx2")["coverage"] == {"lines": 80.0, "branches": 80.0}
    assert load_quality(tmp_path, "context")["coverage"] == {"lines": 55.0, "branches": 55.0}


def test_quality_upgrade_reads_and_writes_given_context_rel_only(tmp_path: Path):
    save_quality(tmp_path, {"test_smells": {"mode": "hard"}}, "context")
    save_quality(tmp_path, {"test_smells": {"mode": "warn"}}, "ctx2")
    info = ensure_quality_config(tmp_path, "ctx2")
    assert info["upgraded_modes"] == ["test_smells"]
    assert load_quality(tmp_path, "ctx2")["test_smells"]["mode"] == "hard"
    assert load_quality(tmp_path, "context")["test_smells"]["mode"] == "hard"
    ctx_default = json.loads((tmp_path / "context" / "quality.json").read_text(encoding="utf-8"))
    assert ctx_default["test_smells"]["mode"] == "hard"
    ctx2_saved = json.loads((tmp_path / "ctx2" / "quality.json").read_text(encoding="utf-8"))
    assert ctx2_saved["test_smells"]["mode"] == "hard"


def test_upsert_replace_cuts_at_first_begin_when_begin_repeats(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"a\n{BEGIN}\nx\n{BEGIN}\ny\n{END}\ntail\n", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, f"{BEGIN}\nn\n{END}\n", create=False) is True
    assert path.read_text(encoding="utf-8") == f"a\n\n{BEGIN}\nn\n{END}\ntail\n"


def test_upsert_replace_strips_only_newlines_from_tail_start(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"{BEGIN}\nold\n{END}\n\nXtail\n", encoding="utf-8")
    assert _upsert_marked_block(path, BEGIN, END, f"{BEGIN}\nn\n{END}\n", create=False) is True
    assert path.read_text(encoding="utf-8") == f"\n\n{BEGIN}\nn\n{END}\nXtail\n"
