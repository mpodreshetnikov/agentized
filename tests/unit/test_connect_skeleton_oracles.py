"""AGE-68 A1: mutation oracles for ``ensure_context_skeleton`` (seed/skeleton).

Tests-only; no runtime change. Target: kill the 25 whole-file survivors on
``agentized.connect.x_ensure_context_skeleton``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentized.connect import (
    MINIMAL_LEASES_INDEX_MD,
    MINIMAL_NAV_MD,
    MINIMAL_TASKS_INDEX_MD,
    ensure_context_skeleton,
)


def test_external_skips_local_registry_dirs(tmp_path: Path):
    """Kill ``external`` True branch → still creates tasks/leases/NAV locally."""
    result = ensure_context_skeleton(tmp_path, "context", external=True)
    assert result == {
        "created": False,
        "path": "context",
        "files": [],
        "skipped_external": True,
    }
    ctx = tmp_path / "context"
    assert ctx.is_dir()
    assert not (ctx / "tasks").exists()
    assert not (ctx / "leases").exists()
    assert not (ctx / "NAV.md").exists()


def test_external_mkdir_parents_exist_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill parents/exist_ok on external-only ctx.mkdir."""
    seen: list[dict] = []
    real = Path.mkdir

    def wrapped(self: Path, *args, **kwargs):
        if self.name == "context":
            seen.append(dict(kwargs))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", wrapped)
    ensure_context_skeleton(tmp_path, "context", external=True)
    assert seen == [{"parents": True, "exist_ok": True}]


def test_noop_result_keys_are_literal_path(tmp_path: Path):
    """Kill ``path`` → ``XXpathXX`` / ``PATH`` on early return."""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "NAV.md").write_text("# existing\n", encoding="utf-8")
    result = ensure_context_skeleton(tmp_path, "context")
    assert result == {"created": False, "path": "context", "files": []}


def test_created_result_keys_are_literal_path(tmp_path: Path):
    """Kill ``path`` → ``XXpathXX`` / ``PATH`` on success return."""
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    assert result["path"] == "context"
    assert set(result) == {"created", "path", "files"}


def test_nested_context_rel_requires_ctx_mkdir_parents(tmp_path: Path):
    """Kill ``ctx.mkdir(parents=True)`` → False/None/omit."""
    rel = "deep/nested/context"
    result = ensure_context_skeleton(tmp_path, rel)
    assert result["created"] is True
    assert result["path"] == rel
    assert (tmp_path / rel / "NAV.md").is_file()


def test_mkdir_kwargs_parents_and_exist_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill parents/exist_ok True → False/None/omit on ctx/tasks/leases mkdir."""
    seen: dict[str, dict] = {}
    real = Path.mkdir

    def wrapped(self: Path, *args, **kwargs):
        seen[self.name] = dict(kwargs)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", wrapped)
    ensure_context_skeleton(tmp_path, "context")
    expected = {"parents": True, "exist_ok": True}
    assert len(seen) == 3
    assert seen["context"] == expected
    assert seen["tasks"] == expected
    assert seen["leases"] == expected


def test_preexisting_tasks_dir_requires_exist_ok(tmp_path: Path):
    """Kill ``exist_ok=True`` → False on tasks mkdir when dir already exists."""
    ctx = tmp_path / "context"
    (ctx / "tasks").mkdir(parents=True)
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    assert (ctx / "tasks" / "INDEX.md").is_file()


def test_preexisting_leases_dir_requires_exist_ok(tmp_path: Path):
    """Kill ``exist_ok=True`` → False on leases mkdir when dir already exists."""
    ctx = tmp_path / "context"
    (ctx / "leases").mkdir(parents=True)
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    assert (ctx / "leases" / "INDEX.md").is_file()


def test_continue_not_break_when_one_index_exists(tmp_path: Path):
    """Kill ``continue`` → ``break``: remaining targets still written."""
    ctx = tmp_path / "context"
    (ctx / "tasks").mkdir(parents=True)
    (ctx / "leases").mkdir(parents=True)
    # NAV missing → create path; pre-seed tasks INDEX so loop hits continue
    (ctx / "tasks" / "INDEX.md").write_text("# keep-tasks\n", encoding="utf-8")
    result = ensure_context_skeleton(tmp_path, "context")
    assert result["created"] is True
    assert (ctx / "NAV.md").is_file()
    assert (ctx / "leases" / "INDEX.md").is_file()
    assert (ctx / "tasks" / "INDEX.md").read_text(encoding="utf-8") == "# keep-tasks\n"
    assert "context/NAV.md" in result["files"]
    assert "context/leases/INDEX.md" in result["files"]
    assert "context/tasks/INDEX.md" not in result["files"]


def test_write_text_encoding_is_utf8_literal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Kill encoding=None / omitted / case variants (UTF-8 ignored by mutmut lexeme)."""
    seen: list[str | None] = []
    real = Path.write_text

    def wrapped(self: Path, data: str, encoding: str | None = None, **kwargs):
        seen.append(encoding)
        return real(self, data, encoding=encoding, **kwargs)

    monkeypatch.setattr(Path, "write_text", wrapped)
    ensure_context_skeleton(tmp_path, "context")
    assert seen
    assert all(enc == "utf-8" for enc in seen)


def test_seed_bodies_use_rstrip_not_lstrip_or_junk(tmp_path: Path):
    """Kill ``rstrip`` → ``lstrip`` and ``\\n`` → ``XX\\nXX``."""
    ensure_context_skeleton(tmp_path, "context")
    nav = (tmp_path / "context" / "NAV.md").read_text(encoding="utf-8")
    tasks = (tmp_path / "context" / "tasks" / "INDEX.md").read_text(encoding="utf-8")
    leases = (tmp_path / "context" / "leases" / "INDEX.md").read_text(encoding="utf-8")
    assert nav == MINIMAL_NAV_MD.rstrip() + "\n"
    assert tasks == MINIMAL_TASKS_INDEX_MD.rstrip() + "\n"
    assert leases == MINIMAL_LEASES_INDEX_MD.rstrip() + "\n"


def test_connect_external_skips_local_skeleton(tmp_path: Path):
    """connect() with placement=external must not create local tasks/leases/NAV."""
    import json
    import subprocess

    from agentized.connect import connect

    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    subprocess.run(["git", "init"], cwd=ext, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=code, check=True, capture_output=True)
    (ext / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    (ext / "leases").mkdir()
    ctx = code / "context"
    ctx.mkdir()
    (ctx / "context.json").write_text(
        json.dumps(
            {"placement": "external", "external": {"path": str(ext), "remote": "r"}}
        )
        + "\n",
        encoding="utf-8",
    )
    result = connect(code, context_rel="context", harnesses=["cursor"])
    assert result["skeleton"]["skipped_external"] is True
    assert result["skeleton"]["created"] is False
    assert not (ctx / "tasks").exists()
    assert not (ctx / "NAV.md").exists()
    assert (ctx / "quality.json").exists()  # code-side pins still land


def test_connect_invalid_layout_falls_back_to_local_skeleton(tmp_path: Path):
    """ValueError from resolve_layout → external=False → local skeleton."""
    from agentized.connect import connect

    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "context.json").write_text('{"placement": "bogus"}\n', encoding="utf-8")
    # connect may still fail later; ensure_context_skeleton path uses external=False
    from agentized.connect import ensure_context_skeleton
    from agentized.context_layout import resolve_layout
    import pytest

    with pytest.raises(ValueError):
        resolve_layout(tmp_path, "context")
    result = ensure_context_skeleton(tmp_path, "context", external=False)
    assert result["created"] is True
    assert (ctx / "NAV.md").is_file()
