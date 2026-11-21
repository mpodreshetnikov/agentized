"""Exact oracles + spies for context_layout (mutmut selects test_context_layout_*)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agentized.context_layout import (
    BRIDGE_GITIGNORE_MARKER,
    BRIDGE_NAMES,
    ENV_CHECK_DOC,
    ERR_BRIDGE_CONFLICT,
    ERR_EMPTY_PATH,
    ERR_INVALID_EXTERNAL,
    ERR_INVALID_EXTERNAL_FIELD,
    ERR_INVALID_JSON,
    ERR_INVALID_OBJECT,
    ERR_INVALID_PLACEMENT,
    ERR_PATH_INSIDE,
    ERR_UNREADABLE,
    PLACEMENT_EXTERNAL,
    PLACEMENT_NESTED,
    ContextLayout,
    _bridge_preflight,
    _clear_empty_bridge_dir,
    _path_is_empty_dir,
    _registry_label,
    apply_external_env_check,
    default_layout_config,
    ensure_bridge_gitignore,
    ensure_code_context_bridges,
    ensure_external_registry_skeleton,
    ensure_layout_config,
    external_clone_problems,
    external_context_gate,
    is_git_checkout,
    is_gitignored,
    is_path_inside,
    load_layout_config,
    merge_external_result,
    preflight_bridge_conflicts,
    prepare_connect_layout,
    require_registry_ready,
    resolve_external_path,
    resolve_layout,
    session_lease_warn,
    session_nav_reminder,
)
from agentized.leases import render_lease_file
from agentized.tasks import render_task_file


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


def _write_layout(root: Path, data: dict, *, context_rel: str = "context") -> None:
    cfg = root / context_rel
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "context.json").write_text(json.dumps(data), encoding="utf-8")


def test_paths_invalid_gitignore_dirs(tmp_path: Path):
    from agentized import env_check as ec

    assert default_layout_config() == {
        "version": 1,
        "placement": PLACEMENT_NESTED,
        "external": {"path": "", "remote": ""},
    }
    (tmp_path / "context").mkdir()
    layout = resolve_layout(tmp_path)
    root = (tmp_path / "context").resolve()
    assert layout.registry_root == root == layout.code_context
    assert layout.tasks_dir() == root / "tasks"
    assert layout.decisions_dir() == root / "decisions"
    assert layout.goals_dir() == root / "goals"
    assert layout.leases_dir() == root / "leases"
    assert layout.digests_dir() == root / "digests"
    assert layout.nav_path() == root / "NAV.md"
    ctx = tmp_path / "context"
    (ctx / "context.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match=ERR_INVALID_JSON):
        load_layout_config(tmp_path)
    (ctx / "context.json").write_text("[1,2]", encoding="utf-8")
    with pytest.raises(ValueError, match=ERR_INVALID_OBJECT):
        load_layout_config(tmp_path)
    (ctx / "context.json").write_text(json.dumps({"placement": "weird"}), encoding="utf-8")
    with pytest.raises(ValueError, match=ERR_INVALID_PLACEMENT):
        load_layout_config(tmp_path)
    (ctx / "context.json").write_text(
        json.dumps({"placement": "external", "external": "bad"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=ERR_INVALID_EXTERNAL):
        load_layout_config(tmp_path)
    (ctx / "context.json").unlink()
    (ctx / "context.json").mkdir()
    with pytest.raises(ValueError, match=ERR_UNREADABLE):
        load_layout_config(tmp_path)
    (ctx / "context.json").rmdir()
    code = tmp_path / "code"
    code.mkdir()
    _write_layout(code, {"placement": "external", "external": {"path": "", "remote": "r"}})
    with pytest.raises(ValueError, match=ERR_EMPTY_PATH):
        resolve_layout(code)
    _git_init(code)
    inside = code / "vendor-context"
    inside.mkdir()
    _write_layout(
        code, {"placement": "external", "external": {"path": "vendor-context", "remote": "r"}}
    )
    with pytest.raises(ValueError, match=ERR_PATH_INSIDE):
        resolve_layout(code)
    (code / ".gitignore").write_text("vendor-context/\n", encoding="utf-8")
    assert is_gitignored(code, inside) is True
    assert resolve_layout(code).registry_root == inside.resolve()
    (tmp_path / "sibling").mkdir()
    assert resolve_external_path(tmp_path, "sibling") == (tmp_path / "sibling").resolve()
    with pytest.raises(ValueError, match=ERR_EMPTY_PATH):
        resolve_external_path(tmp_path, "  ")
    abs_target = (tmp_path / "abs-ext").resolve()
    abs_target.mkdir()
    assert resolve_external_path(tmp_path, str(abs_target)) == abs_target
    assert is_path_inside(tmp_path, tmp_path / "sibling") and not is_path_inside(
        tmp_path, tmp_path.parent
    )
    assert is_git_checkout(tmp_path / "sibling") is False
    file_path = tmp_path / "file"
    file_path.write_text("x", encoding="utf-8")
    assert external_clone_problems(
        ContextLayout(
            placement=PLACEMENT_EXTERNAL,
            code_context=tmp_path / "context",
            registry_root=file_path,
            remote="",
            path_config=str(file_path),
        )
    ) == [f"external Context path is not a directory: {file_path}"]
    bare = tmp_path / "bare"
    bare.mkdir()
    probs = external_clone_problems(
        ContextLayout(
            placement=PLACEMENT_EXTERNAL,
            code_context=tmp_path / "context",
            registry_root=bare,
            remote="",
            path_config=str(bare),
        )
    )
    assert probs[0].startswith("external Context is not a git checkout")
    assert any("NAV.md" in p for p in probs) and any("tasks/" in p for p in probs)
    ext = tmp_path / "ext-ok"
    ext.mkdir()
    _git_init(ext)
    (ext / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    _write_layout(code, {"placement": "external", "external": {"path": str(ext), "remote": "r"}})
    result = apply_external_env_check(
        ec.check(env={}, repo_root=code, home=tmp_path / "home"),
        code,
    )
    assert result["ok"] and result["external_context"]["ok"]


def test_load_layout_normalize_custom_rel_message_encoding(tmp_path: Path, monkeypatch):
    _write_layout(
        tmp_path,
        {"placement": " NESTED ", "external": {"path": None, "remote": None}},
        context_rel="pc",
    )
    assert load_layout_config(tmp_path, "pc") == {
        "version": 1,
        "placement": "nested",
        "external": {"path": "", "remote": ""},
    }
    # missing path/remote keys → empty strings (kills .get default mutants)
    miss = tmp_path / "pc-miss" / "context.json"
    miss.parent.mkdir(parents=True, exist_ok=True)
    miss.write_text(json.dumps({"placement": "nested", "external": {}}), encoding="utf-8")
    assert load_layout_config(tmp_path, "pc-miss")["external"] == {"path": "", "remote": ""}
    only_r = tmp_path / "pc-or" / "context.json"
    only_r.parent.mkdir(parents=True, exist_ok=True)
    only_r.write_text(
        json.dumps({"placement": "nested", "external": {"remote": "only"}}), encoding="utf-8"
    )
    assert load_layout_config(tmp_path, "pc-or")["external"] == {"path": "", "remote": "only"}
    only_p = tmp_path / "pc-op" / "context.json"
    only_p.parent.mkdir(parents=True, exist_ok=True)
    only_p.write_text(
        json.dumps({"placement": "nested", "external": {"path": "only"}}), encoding="utf-8"
    )
    assert load_layout_config(tmp_path, "pc-op")["external"] == {"path": "only", "remote": ""}
    _write_layout(
        tmp_path,
        {"placement": "nested", "external": {"path": 123, "remote": ""}},
        context_rel="pc-num",
    )
    with pytest.raises(ValueError, match=ERR_INVALID_EXTERNAL_FIELD):
        load_layout_config(tmp_path, "pc-num")
    null_p = tmp_path / "pc2" / "context.json"
    null_p.parent.mkdir(parents=True, exist_ok=True)
    null_p.write_text(json.dumps({"placement": None}), encoding="utf-8")
    with pytest.raises(ValueError) as null_ei:
        load_layout_config(tmp_path, "pc2")
    assert str(null_ei.value) == f"{ERR_INVALID_PLACEMENT} (got None): {null_p}"
    assert not (tmp_path / "context" / "context.json").exists()
    bad = tmp_path / "pc" / "context.json"
    bad.write_text(json.dumps({"placement": "nope"}), encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        load_layout_config(tmp_path, "pc")
    assert str(ei.value) == f"{ERR_INVALID_PLACEMENT} (got 'nope'): {bad}"
    _write_layout(tmp_path, {"placement": "nested"})
    seen: list[dict] = []
    real = Path.read_text

    def spy(self, *a, **k):
        seen.append(dict(k))
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy)
    load_layout_config(tmp_path)
    assert any(x.get("encoding") == "utf-8" for x in seen)


def test_ensure_layout_exact_mkdir_write_spies(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    mkdir_calls: list[dict] = []
    write_calls: list[dict] = []
    real_mkdir, real_write = Path.mkdir, Path.write_text

    def spy_mkdir(self, *a, **k):
        mkdir_calls.append(dict(k))
        return real_mkdir(self, *a, **k)

    def spy_write(self, data, *a, **k):
        write_calls.append({"data": data, **dict(k)})
        return real_write(self, data, *a, **k)

    monkeypatch.setattr(Path, "mkdir", spy_mkdir)
    monkeypatch.setattr(Path, "write_text", spy_write)
    assert ensure_layout_config(root, "pc") == {"path": "pc/context.json", "created": True}
    assert {"parents": True, "exist_ok": True} in mkdir_calls
    assert any(c.get("encoding") == "utf-8" for c in write_calls)
    assert (root / "pc" / "context.json").read_text(encoding="utf-8") == (
        json.dumps(default_layout_config(), indent=2) + "\n"
    )
    assert ensure_layout_config(root, "pc") == {"path": "pc/context.json", "created": False}


def test_registry_label_gitignore_config_path(tmp_path: Path, monkeypatch):
    from agentized import context_layout as cl

    code, outside = tmp_path / "code", tmp_path / "outside"
    code.mkdir()
    outside.mkdir()
    (code / "context").mkdir()
    assert _registry_label(code, code / "context") == "context"
    assert _registry_label(code, outside) == str(outside.resolve())
    assert (
        resolve_layout(code).config_path("quality.json")
        == (code / "context" / "quality.json").resolve()
    )
    calls: list[dict] = []

    def fake_run(args, **kwargs):
        calls.append(
            {"args": list(args), "cwd": kwargs.get("cwd"), "cap": kwargs.get("capture_output")}
        )

        class P:
            returncode = 0

        return P()

    monkeypatch.setattr(cl.subprocess, "run", fake_run)
    outside_p = tmp_path / "outside-dir" / "x"
    assert is_gitignored(tmp_path / "repo", outside_p) is True
    assert calls == [
        {
            "args": ["git", "check-ignore", "-q", "--", str(outside_p)],
            "cwd": tmp_path / "repo",
            "cap": True,
        }
    ]


def test_resolve_custom_rel_remote_default(tmp_path: Path):
    code = tmp_path / "code"
    code.mkdir()
    _write_layout(
        code,
        {"placement": "external", "external": {"path": str(tmp_path / "ext"), "remote": None}},
        context_rel="pc",
    )
    (tmp_path / "ext").mkdir()
    (code / "context").mkdir()
    assert resolve_layout(code, "context").is_external is False
    layout = resolve_layout(code, "pc")
    assert layout.is_external is True
    assert layout.remote == ""
    assert layout.path_config == str(tmp_path / "ext")


def test_external_problems_and_require_ready(tmp_path: Path):
    missing = Path("/tmp/agentized-missing-ext-oracle-path")
    assert external_clone_problems(
        ContextLayout(
            placement=PLACEMENT_EXTERNAL,
            code_context=Path("/tmp/ctx"),
            registry_root=missing,
            remote="git@x/y.git",
            path_config=str(missing),
        )
    ) == [f"external Context path missing: {missing} remote=git@x/y.git"]
    assert external_clone_problems(
        ContextLayout(
            placement=PLACEMENT_EXTERNAL,
            code_context=Path("/tmp/ctx"),
            registry_root=missing,
            remote="",
            path_config=str(missing),
        )
    ) == [f"external Context path missing: {missing}"]
    bare = tmp_path / "bare"
    bare.mkdir()
    _git_init(bare)
    assert external_clone_problems(
        ContextLayout(
            placement=PLACEMENT_EXTERNAL,
            code_context=tmp_path / "context",
            registry_root=bare,
            remote="",
            path_config=str(bare),
        )
    ) == [
        f"external Context missing NAV.md: {bare / 'NAV.md'}",
        f"external Context missing tasks/: {bare / 'tasks'}",
    ]
    code = tmp_path / "code"
    code.mkdir()
    miss = tmp_path / "missing"
    _write_layout(code, {"placement": "external", "external": {"path": str(miss), "remote": "r"}})
    layout = resolve_layout(code)
    probs = external_clone_problems(layout)
    assert probs == [f"external Context path missing: {miss.resolve()} remote=r"]
    with pytest.raises(ValueError) as ei:
        require_registry_ready(layout)
    assert str(ei.value) == "external Context not ready: " + "; ".join(probs)
    empty = ContextLayout(
        placement=PLACEMENT_EXTERNAL,
        code_context=tmp_path / "context",
        registry_root=tmp_path / "gone",
        remote="r",
        path_config="",
    )
    assert external_clone_problems(empty) == ["context.json external.path is empty"]
    multi = ContextLayout(
        placement=PLACEMENT_EXTERNAL,
        code_context=tmp_path / "context",
        registry_root=bare,
        remote="",
        path_config=str(bare),
    )
    mprobs = external_clone_problems(multi)
    assert len(mprobs) >= 2
    with pytest.raises(ValueError) as ei2:
        require_registry_ready(multi)
    assert str(ei2.value) == "external Context not ready: " + "; ".join(mprobs)


def test_session_nav_exact_agents_custom_rel(tmp_path: Path, monkeypatch):
    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(ext)
    (ext / "NAV.md").write_text("# NAV\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    (ext / "leases").mkdir()
    (code / "AGENTS.md").write_text("see NAV.md\n", encoding="utf-8")
    _write_layout(code, {"placement": "external", "external": {"path": str(ext), "remote": "r"}})
    label = str(ext.resolve())
    assert session_nav_reminder(code) == "\n".join(
        [
            "Agentized session check:",
            f"- Project Context: external → {label}",
            f"- Read {label}/NAV.md first; follow only its links.",
            f"- Live board: {label}/tasks/INDEX.md (no full tasks/ listing).",
            f"- Leases warn-only: {label}/leases/INDEX.md",
            f"OK: {label}/NAV.md present.",
        ]
    )
    (code / "AGENTS.md").unlink()
    assert [ln for ln in session_nav_reminder(code).splitlines() if ln.startswith("WARN:")] == [
        "WARN: AGENTS.md missing."
    ]
    (code / "AGENTS.md").write_text("no pointer here\n", encoding="utf-8")
    assert [ln for ln in session_nav_reminder(code).splitlines() if ln.startswith("WARN:")] == [
        "WARN: AGENTS.md has no NAV.md pointer — run agentized connect."
    ]
    seen: list[dict] = []
    real = Path.read_text

    def spy(self, *a, **k):
        seen.append(dict(k))
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy)
    session_nav_reminder(code)
    assert seen and all(x.get("encoding") == "utf-8" for x in seen)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "ctx").mkdir()
    (nested / "ctx" / "NAV.md").write_text("# n\n", encoding="utf-8")
    (nested / "AGENTS.md").write_text("NAV.md\n", encoding="utf-8")
    _write_layout(nested, {"placement": "nested"}, context_rel="ctx")
    assert session_nav_reminder(nested, "ctx").splitlines()[1] == "- Project Context: ctx/"
    (nested / "context").mkdir()
    assert session_nav_reminder(nested, "context").splitlines()[1] == "- Project Context: context/"
    (tmp_path / "pc").mkdir()
    (tmp_path / "pc" / "context.json").write_text("{bad", encoding="utf-8")
    err = session_nav_reminder(tmp_path, "pc")
    assert err.startswith("Agentized session check:\n- Project Context config error:")
    assert ERR_INVALID_JSON in err
    assert err.endswith("- Fix pc/context.json then re-run session.")


def test_session_lease_ignore_custom_rel(tmp_path: Path):
    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(ext)
    (ext / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    (ext / "leases").mkdir()
    (ext / "leases" / "T-1.md").write_text(
        render_lease_file("T-1", "a", ["runtime"]), encoding="utf-8"
    )
    _write_layout(
        code,
        {"placement": "external", "external": {"path": str(ext), "remote": "r"}},
        context_rel="pc",
    )
    assert "LEASE WARN" in session_lease_warn(code, ["runtime/x.py"], context_rel="pc")
    assert session_lease_warn(code, ["runtime/x.py"], ignore_task="T-1", context_rel="pc") == ""
    assert session_lease_warn(code, [], context_rel="pc") == ""
    (code / "context").mkdir()
    assert session_lease_warn(code, ["runtime/x.py"]) == ""
    (tmp_path / "badpc").mkdir()
    (tmp_path / "badpc" / "context.json").write_text("{bad", encoding="utf-8")
    err = session_lease_warn(tmp_path, ["runtime/x.py"], context_rel="badpc")
    assert err.startswith("Project Context config error:")
    assert ERR_INVALID_JSON in err


def test_external_gate_invalid_and_multi_exact(tmp_path: Path):
    code = tmp_path / "code"
    code.mkdir()
    _write_layout(code, {"placement": "external", "external": {"path": "", "remote": "r"}})
    bad = external_context_gate(code, "context")
    assert bad == {
        "ok": False,
        "refused": True,
        "message": bad["message"],
        "audience": "external-context",
    }
    assert bad["message"].startswith(
        "agent-env-check: REFUSED. External Project Context config is invalid "
    )
    assert ENV_CHECK_DOC in bad["message"] and "Fix context/context.json" in bad["message"]
    bare = tmp_path / "bare"
    bare.mkdir()
    _git_init(bare)
    _write_layout(code, {"placement": "external", "external": {"path": str(bare), "remote": "r"}})
    detail = (
        f"external Context missing NAV.md: {bare / 'NAV.md'}; "
        f"external Context missing tasks/: {bare / 'tasks'}"
    )
    expected = (
        "agent-env-check: REFUSED. External Project Context clone is missing or incomplete "
        f"({detail}). Code repo and Context repo must both be present. "
        f"Clone `external.remote` to `external.path` from context/context.json. "
        f"See {ENV_CHECK_DOC}."
    )
    assert external_context_gate(code, "context") == {
        "ok": False,
        "refused": True,
        "message": expected,
        "audience": "external-context",
    }


def test_external_gate_ok_custom_rel(tmp_path: Path):
    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(ext)
    (ext / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    _write_layout(code, {"placement": "external", "external": {"path": str(ext), "remote": "r"}})
    assert external_context_gate(code, "context") == {
        "ok": True,
        "refused": False,
        "message": f"agent-env-check: external Context OK at {ext.resolve()} (remote=r)",
        "audience": "external-context",
    }
    _write_layout(code, {"placement": "external", "external": {"path": str(ext), "remote": ""}})
    assert external_context_gate(code, "context") == {
        "ok": True,
        "refused": False,
        "message": f"agent-env-check: external Context OK at {ext.resolve()}",
        "audience": "external-context",
    }
    bare_root = tmp_path / "nested-root"
    bare_root.mkdir()
    (bare_root / "context").mkdir()
    assert external_context_gate(bare_root, "context") is None
    other = tmp_path / "other"
    other.mkdir()
    _write_layout(other, {"placement": "nope"}, context_rel="pc")
    (other / "context").mkdir()
    assert external_context_gate(other, "context") is None
    bad = external_context_gate(other, "pc")
    assert bad == {
        "ok": False,
        "refused": True,
        "message": bad["message"],
        "audience": "external-context",
    }


def test_merge_external_result_exact():
    base = {"ok": True, "refused": False, "message": "base", "audience": "local"}
    assert merge_external_result(base, None) is base
    refuse = {"ok": False, "refused": True, "message": "nope", "audience": "external-context"}
    assert merge_external_result(base, refuse) is refuse
    ext = {
        "ok": True,
        "refused": False,
        "message": "extra line",
        "audience": "external-context",
    }
    merged = merge_external_result(base, ext)
    assert merged["message"] == "base\nextra line"
    assert merged["external_context"] == ext
    assert merged["audience"] == "local"
    assert (
        merge_external_result(
            {"ok": True, "message": "extra line already", "audience": "local"}, ext
        )["message"]
        == "extra line already"
    )
    merged2 = merge_external_result(
        {"ok": True, "audience": "local"}, {"ok": True, "audience": "external-context"}
    )
    assert "message" not in merged2
    assert (
        merge_external_result({"ok": True}, {"ok": True, "message": "only-ext"})["message"]
        == "\nonly-ext"
    )
    assert (
        merge_external_result({"ok": True, "message": None}, {"ok": True, "message": "line"})[
            "message"
        ]
        == "\nline"
    )


def test_apply_external_env_check_short_circuit(tmp_path: Path):
    code = tmp_path / "code"
    code.mkdir()
    _write_layout(code, {"placement": "external", "external": {"path": "", "remote": "r"}})
    base = {"ok": True, "refused": False, "message": "base-ok", "audience": "core"}
    bad = apply_external_env_check(base, code, "context")
    assert bad["ok"] is False and bad["refused"] is True
    assert bad["audience"] == "external-context"
    assert "cloud" not in bad and "env_keys" not in bad
    hooks_fail = {"ok": False, "refused": True, "message": "hooks", "audience": "cursor"}
    assert apply_external_env_check(hooks_fail, code, "context") == hooks_fail


def test_bridges_and_prepare_connect(tmp_path: Path, monkeypatch):
    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(ext)
    (ext / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    (ext / "leases").mkdir()
    (ext / "tasks" / "T-261116-aaa.md").write_text(
        render_task_file("T-261116-aaa", "Ext", status="in-progress", claim="alice"),
        encoding="utf-8",
    )
    _write_layout(code, {"placement": "external", "external": {"path": str(ext), "remote": "r"}})
    layout = resolve_layout(code)
    mkdir_calls: list[dict] = []
    real_mkdir = Path.mkdir

    def spy_mkdir(self, *a, **k):
        mkdir_calls.append(dict(k))
        return real_mkdir(self, *a, **k)

    monkeypatch.setattr(Path, "mkdir", spy_mkdir)
    from agentized.context_layout import ERR_BRIDGE_FOREIGN

    assert ensure_code_context_bridges(layout) == ["tasks", "leases", "NAV.md"]
    assert {"parents": True, "exist_ok": True} in mkdir_calls
    assert (code / "context" / "tasks").resolve() == (ext / "tasks").resolve()
    assert ensure_code_context_bridges(layout) == []
    (code / "context" / "leases").unlink()
    assert ensure_code_context_bridges(layout) == ["leases"]
    (code / "context" / "leases").unlink()
    (code / "context" / "leases").mkdir()
    (code / "context" / "NAV.md").unlink()
    assert ensure_code_context_bridges(layout) == ["leases", "NAV.md"]
    (code / "context" / "leases").unlink()
    (code / "context" / "leases").mkdir()
    (code / "context" / "leases" / "stale.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match=ERR_BRIDGE_CONFLICT):
        ensure_code_context_bridges(layout)
    import shutil

    shutil.rmtree(code / "context" / "leases")
    wrong = tmp_path / "wrong-target"
    wrong.mkdir()
    (code / "context" / "tasks").unlink()
    (code / "context" / "tasks").symlink_to(wrong)
    with pytest.raises(ValueError, match=ERR_BRIDGE_FOREIGN):
        ensure_code_context_bridges(layout)
    (code / "context" / "tasks").unlink()
    created = ensure_code_context_bridges(layout)
    assert "tasks" in created and "leases" in created
    (code / "context" / "goals").mkdir()
    (code / "context" / "goals" / "G.md").write_text("g", encoding="utf-8")
    assert "goals" in ensure_code_context_bridges(layout)
    assert (ext / "goals" / "G.md").read_text(encoding="utf-8") == "g"
    (ext / "decisions").mkdir()
    assert "decisions" in ensure_code_context_bridges(layout)
    (ext / "decisions").rmdir()
    (code / "context" / "decisions").unlink(missing_ok=True)
    from agentized.process_control import active_claims

    (code / "context" / "tasks").unlink(missing_ok=True)
    assert ensure_code_context_bridges(layout) == ["tasks"]
    assert any("T-261116-aaa" in c for c in active_claims(code))
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "context").mkdir()
    assert ensure_code_context_bridges(resolve_layout(nested)) == []
    ready = prepare_connect_layout(code)
    assert ready.is_external and ready.registry_root == ext.resolve()
    assert not Path((code / "context" / "tasks").readlink()).is_absolute()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert (code / "context" / "tasks").resolve() == (ext / "tasks").resolve()
    assert ensure_code_context_bridges(layout) == []
    custom = tmp_path / "custom"
    custom.mkdir()
    _write_layout(
        custom,
        {"placement": "external", "external": {"path": str(ext), "remote": "r"}},
        context_rel="pc",
    )
    custom_layout = prepare_connect_layout(custom, context_rel="pc")
    assert custom_layout.code_context == (custom / "pc").resolve()
    assert (custom / "pc" / "tasks").resolve() == (ext / "tasks").resolve()
    assert not (custom / "context").exists()
    nested_ready = prepare_connect_layout(nested)
    assert (
        not nested_ready.is_external
        and nested_ready.registry_root == (nested / "context").resolve()
    )
    _write_layout(
        code,
        {"placement": "external", "external": {"path": str(tmp_path / "missing"), "remote": "r"}},
    )
    with pytest.raises(
        ValueError, match="external Context not ready|external Context path missing"
    ):
        prepare_connect_layout(code)


def test_empty_external_registry_skeleton_and_preflight(tmp_path: Path):
    """Seed empty external clone; preflight conflicts before bridges."""
    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(ext)
    _write_layout(
        code,
        {"placement": "external", "external": {"path": str(ext), "remote": "r"}},
    )
    layout = resolve_layout(code)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "context").mkdir()
    assert ensure_external_registry_skeleton(resolve_layout(nested)) == []

    created = ensure_external_registry_skeleton(layout)
    assert created == [
        str(ext / "NAV.md"),
        str(ext / "tasks" / "INDEX.md"),
        str(ext / "leases" / "INDEX.md"),
    ]
    assert (ext / "NAV.md").read_text(encoding="utf-8") == (
        "# NAV — external Project Context\n\nSee tasks/INDEX.md and leases/INDEX.md.\n"
    )
    assert "_(empty)_" in (ext / "tasks" / "INDEX.md").read_text(encoding="utf-8")
    assert "| path | task | owner | expires |" in (ext / "leases" / "INDEX.md").read_text(
        encoding="utf-8"
    )
    assert ensure_external_registry_skeleton(layout) == []  # idempotent
    require_registry_ready(layout)
    preflight_bridge_conflicts(layout)  # clean — no raise

    # Partial seed: existing NAV must not stop tasks/leases creation (continue≠break).
    partial = tmp_path / "partial-ext"
    partial.mkdir()
    _git_init(partial)
    (partial / "NAV.md").write_text("# keep\n", encoding="utf-8")
    code_partial = tmp_path / "code-partial"
    code_partial.mkdir()
    _write_layout(
        code_partial,
        {"placement": "external", "external": {"path": str(partial), "remote": "r"}},
    )
    partial_created = ensure_external_registry_skeleton(resolve_layout(code_partial))
    assert (partial / "NAV.md").read_text(encoding="utf-8") == "# keep\n"
    assert partial_created == [
        str(partial / "tasks" / "INDEX.md"),
        str(partial / "leases" / "INDEX.md"),
    ]

    (code / "context" / "tasks").mkdir(parents=True)
    (code / "context" / "tasks" / "stale.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match=ERR_BRIDGE_CONFLICT):
        preflight_bridge_conflicts(layout)
    # prepare_connect_layout seeds empty clone then fails preflight before bridges
    empty = tmp_path / "empty-ext"
    empty.mkdir()
    _git_init(empty)
    code2 = tmp_path / "code2"
    code2.mkdir()
    _write_layout(
        code2,
        {"placement": "external", "external": {"path": str(empty), "remote": "r"}},
    )
    (code2 / "context" / "tasks").mkdir(parents=True)
    (code2 / "context" / "tasks" / "x.md").write_text("y", encoding="utf-8")
    with pytest.raises(ValueError, match=ERR_BRIDGE_CONFLICT):
        prepare_connect_layout(code2, bridges=False)
    assert (empty / "NAV.md").is_file()  # seeded before preflight

    bad = tmp_path / "code-bad"
    bad.mkdir()
    _write_layout(
        bad,
        {"placement": "external", "external": {"path": str(tmp_path / "nope"), "remote": "r"}},
    )
    with pytest.raises(ValueError, match="missing or not a directory"):
        ensure_external_registry_skeleton(resolve_layout(bad))
    not_git = tmp_path / "not-git"
    not_git.mkdir()
    _write_layout(
        bad,
        {"placement": "external", "external": {"path": str(not_git), "remote": "r"}},
    )
    with pytest.raises(ValueError, match="not a git checkout"):
        ensure_external_registry_skeleton(resolve_layout(bad))
    file_ext = tmp_path / "file-ext"
    file_ext.write_text("x", encoding="utf-8")
    _write_layout(
        bad,
        {"placement": "external", "external": {"path": str(file_ext), "remote": "r"}},
    )
    with pytest.raises(ValueError, match="missing or not a directory"):
        ensure_external_registry_skeleton(resolve_layout(bad))


def test_bridge_link_target_cwd_independent(tmp_path: Path, monkeypatch):
    import os

    from agentized.context_layout import _bridge_link_target

    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(ext)
    (ext / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    _write_layout(code, {"placement": "external", "external": {"path": str(ext), "remote": "r"}})
    layout = resolve_layout(code)
    # Deep trap: start=str(None) must not match dest.parent depth (kills mutmut_6).
    trap = tmp_path / "deep" / "cwd_trap"
    trap.mkdir(parents=True)
    monkeypatch.chdir(trap)
    assert ensure_code_context_bridges(layout) == ["tasks", "NAV.md"]
    dest, src = code / "context" / "tasks", ext / "tasks"
    expected = os.path.relpath(str(src.resolve()), start=str(dest.parent.resolve()))
    assert _bridge_link_target(src, dest) == expected
    assert dest.readlink() == Path(expected) and dest.resolve() == src.resolve()
    assert not Path(expected).is_absolute()


def test_claim_via_bridges_equals_registry(tmp_path: Path):
    from agentized.process_control import active_claims

    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(ext)
    (ext / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ext / "tasks").mkdir()
    (ext / "tasks" / "T-261116-reg.md").write_text(
        "# T-261116-reg — t\n\nстатус: in-progress\nтеги:\nродитель:\nclaim: reg\n",
        encoding="utf-8",
    )
    _write_layout(code, {"placement": "external", "external": {"path": str(ext), "remote": "r"}})
    stale = code / "context" / "tasks"
    stale.mkdir()
    (stale / "T-stale.md").write_text(
        "# T-stale — t\n\nстатус: in-progress\nтеги:\nродитель:\nclaim: stale\n", encoding="utf-8"
    )
    layout = resolve_layout(code)
    with pytest.raises(ValueError, match="blocks external bridge"):
        ensure_code_context_bridges(layout)
    for child in stale.iterdir():
        child.unlink()
    stale.rmdir()
    assert "tasks" in ensure_code_context_bridges(layout)
    claims = active_claims(code)
    assert any("T-261116-reg" in c and "reg" in c for c in claims)
    assert not any("T-stale" in c for c in claims)


def test_bridges_atomic_gitkeep_gitignore_oracles(tmp_path: Path, monkeypatch):
    """Atomic preflight, .gitkeep-empty, gitignore exactness, skip≠break, custom rel."""
    import shutil

    f = tmp_path / "not-dir"
    f.write_text("x", encoding="utf-8")
    assert _path_is_empty_dir(f) is False
    junk = tmp_path / "junk-dir"
    junk.mkdir()
    (junk / "other.txt").write_text("o", encoding="utf-8")
    with pytest.raises(OSError):
        _clear_empty_bridge_dir(junk)
    assert (junk / "other.txt").exists()
    only = tmp_path / "only-gk"
    only.mkdir()
    (only / ".gitkeep").write_text("", encoding="utf-8")
    assert _path_is_empty_dir(only) is True
    _clear_empty_bridge_dir(only)
    assert not only.exists()

    code, ext = tmp_path / "code", tmp_path / "ext"
    code.mkdir()
    ext.mkdir()
    _git_init(ext)
    (ext / "NAV.md").write_text("# n\n", encoding="utf-8")
    for name in ("tasks", "leases", "digests"):
        (ext / name).mkdir()
    _write_layout(code, {"placement": "external", "external": {"path": str(ext), "remote": "r"}})
    layout = resolve_layout(code)
    (code / "context").mkdir(parents=True, exist_ok=True)
    conflict = code / "context" / "digests"
    conflict.mkdir()
    (conflict / "stale.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match=ERR_BRIDGE_CONFLICT):
        ensure_code_context_bridges(layout)
    assert not (code / "context" / "tasks").exists()
    shutil.rmtree(conflict)
    leases = code / "context" / "leases"
    leases.mkdir()
    (leases / ".gitkeep").write_text("", encoding="utf-8")
    created = ensure_code_context_bridges(layout)
    assert created == ["tasks", "leases", "digests", "NAV.md"]
    # skip must continue (not break): unlink one bridge, recreate only that name
    (code / "context" / "leases").unlink()
    assert ensure_code_context_bridges(layout) == ["leases"]

    assert _bridge_preflight(tmp_path / "no-src", tmp_path / "no-dest") == "skip"
    link_src, link_dest = tmp_path / "link-src", tmp_path / "link-dest"
    link_src.mkdir()
    assert _bridge_preflight(link_src, link_dest) == "link"

    writes: list[dict] = []
    reads: list[dict] = []
    real_write, real_read = Path.write_text, Path.read_text

    def spy_write(self, data, *a, **k):
        writes.append({"path": self, "data": data, **dict(k)})
        return real_write(self, data, *a, **k)

    def spy_read(self, *a, **k):
        reads.append({"path": self, **dict(k)})
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", spy_write)
    monkeypatch.setattr(Path, "read_text", spy_read)
    expected_block = (
        BRIDGE_GITIGNORE_MARKER + "\n" + "\n".join(f"context/{n}" for n in BRIDGE_NAMES) + "\n"
    )
    (code / ".gitignore").write_text("keep-me\n", encoding="utf-8")
    assert ensure_bridge_gitignore(code) is True
    assert any(r.get("encoding") == "utf-8" and r["path"].name == ".gitignore" for r in reads)
    assert writes[-1]["encoding"] == "utf-8"
    assert writes[-1]["data"] == "keep-me\n\n" + expected_block
    assert ensure_bridge_gitignore(code) is False
    bare = tmp_path / "bare-gi"
    bare.mkdir()
    (bare / ".gitignore").write_text("solo", encoding="utf-8")
    assert ensure_bridge_gitignore(bare) is True
    assert writes[-1]["data"] == "solo\n\n" + expected_block
    fresh = tmp_path / "fresh-gi"
    fresh.mkdir()
    assert ensure_bridge_gitignore(fresh) is True
    assert writes[-1]["encoding"] == "utf-8"
    assert writes[-1]["data"] == expected_block
    custom = tmp_path / "custom"
    custom.mkdir()
    _write_layout(
        custom,
        {"placement": "external", "external": {"path": str(ext), "remote": "r"}},
        context_rel="pc",
    )
    prepare_connect_layout(custom, context_rel="pc")
    gi_pc = (custom / ".gitignore").read_text(encoding="utf-8")
    assert all(f"pc/{n}" in gi_pc for n in BRIDGE_NAMES)
    assert "context/tasks" not in gi_pc

    # switch: gitignore + rm --cached → clean status
    repo, ext2 = tmp_path / "repo", tmp_path / "ext2"
    repo.mkdir()
    ext2.mkdir()
    _git_init(repo)
    _git_init(ext2)
    for cmd in (["git", "config", "user.email", "t@e.com"], ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    ctx = repo / "context"
    ctx.mkdir()
    (ctx / "tasks").mkdir()
    (ctx / "tasks" / "T-1.md").write_text("# T-1 — t\n\nстатус: open\n", encoding="utf-8")
    (ctx / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ctx / "context.json").write_text(
        json.dumps({"placement": "nested", "external": {"path": "", "remote": ""}}),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "n"], cwd=repo, check=True, capture_output=True)
    (ext2 / "tasks").mkdir()
    (ext2 / "tasks" / "T-1.md").write_text(
        (ctx / "tasks" / "T-1.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (ext2 / "NAV.md").write_text("# n\n", encoding="utf-8")
    (ctx / "context.json").write_text(
        json.dumps({"placement": "external", "external": {"path": str(ext2), "remote": "r"}}),
        encoding="utf-8",
    )
    shutil.rmtree(ctx / "tasks")
    (ctx / "NAV.md").unlink()
    prepare_connect_layout(repo)
    subprocess.run(
        ["git", "rm", "-r", "--cached", "context/tasks", "context/NAV.md"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "context/context.json", ".gitignore"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "commit", "-m", "ext"], cwd=repo, check=True, capture_output=True)
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        == ""
    )
    assert (ctx / "tasks").is_symlink() and is_gitignored(repo, ctx / "tasks")
