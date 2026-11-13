from __future__ import annotations

from pathlib import Path

from agentized.connect import (
    QUALITY_MARKER,
    _copy_tree,
    _safe_install_template,
    _upsert_marked_block,
    pin_context_skills_hooks,
)
from agentized.hook_common import extract_paths, nav_reminder, read_stdin_json
from agentized.leases import list_leases, rebuild_lease_index
from agentized.paths import CONNECT_MARKER_BEGIN, CONNECT_MARKER_END
from agentized.quality import default_quality_config, load_quality, module_thresholds, save_quality


def test_upsert_and_copy(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    body = f"{CONNECT_MARKER_BEGIN}\nA\n{CONNECT_MARKER_END}\n"
    assert _upsert_marked_block(path, CONNECT_MARKER_BEGIN, CONNECT_MARKER_END, body, create=True)
    _upsert_marked_block(path, CONNECT_MARKER_BEGIN, CONNECT_MARKER_END, body, create=True)
    assert path.read_text(encoding="utf-8").count(CONNECT_MARKER_BEGIN) == 1
    other = tmp_path / "OTHER.md"
    other.write_text("keep\n", encoding="utf-8")
    assert _upsert_marked_block(other, CONNECT_MARKER_BEGIN, CONNECT_MARKER_END, body, create=False)
    assert "keep" in other.read_text(encoding="utf-8")
    assert not _upsert_marked_block(tmp_path / "nope.md", "B", "E", "x", create=False)
    src = tmp_path / "src"; (src / "a").mkdir(parents=True)
    (src / "a" / "f.txt").write_text("1", encoding="utf-8")
    assert any(p.endswith("f.txt") for p in _copy_tree(src, tmp_path / "dst"))
    assert _copy_tree(tmp_path / "missing", tmp_path / "dst") == []
    (tmp_path / "packages/shared/skills/navigate").mkdir(parents=True)
    (tmp_path / "packages/shared/skills/navigate/SKILL.md").write_text("x", encoding="utf-8")
    (tmp_path / "packages/shared/hooks/scripts").mkdir(parents=True)
    (tmp_path / "packages/shared/hooks/scripts/session_start.py").write_text("x", encoding="utf-8")
    ctx = tmp_path / "context"; (ctx / "skills").mkdir(parents=True); (ctx / "hooks").mkdir(parents=True)
    (ctx / "skills/.gitkeep").write_text("", encoding="utf-8")
    (ctx / "hooks/.gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert (ctx / "skills/navigate/SKILL.md").exists()
    src2 = tmp_path / "tpl"; src2.write_text(f"# {QUALITY_MARKER}\nA\n", encoding="utf-8")
    dst = tmp_path / "out"; dst.write_text("# custom\n", encoding="utf-8")
    assert _safe_install_template(src2, dst) == "skipped-user-file"


def test_hook_and_lease_edges(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.stdin", type("S", (), {"read": lambda self: '{"a":1}'})())
    assert read_stdin_json()["a"] == 1
    assert extract_paths({"filePath": "a.py", "edits": ["b.py"], "files": [{"path": "c.py"}]})
    (tmp_path / "AGENTS.md").write_text("no pointer\n", encoding="utf-8")
    assert "WARN" in nav_reminder(tmp_path)
    (tmp_path / "A.md").write_text("task: A\nowner: o\nstatus: active\npaths:\n- runtime\n", encoding="utf-8")
    (tmp_path / "B.md").write_text("task: B\nowner: o\nstatus: released\npaths:\n- other\n", encoding="utf-8")
    assert list_leases(tmp_path, active_only=True)
    assert "Path leases" in rebuild_lease_index(tmp_path)


def test_quality_invalid(tmp_path: Path):
    path = tmp_path / "context/quality.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]\n", encoding="utf-8")
    try:
        load_quality(tmp_path)
        ok = False
    except ValueError:
        ok = True
    assert ok
    save_quality(tmp_path, {"version": 1, "coverage": {"lines": 81}, "modules": []})
    assert load_quality(tmp_path)["coverage"]["lines"] == 81.0



def test_quality_normalize_and_module_thresholds(tmp_path: Path):
    save_quality(tmp_path, {
        "version": 1,
        "coverage": {"lines": 77, "branches": 78},
        "modules": [{"id": "m", "source": ["x"], "thresholds": {"lines": 70}}],
        "mutation": {"gate": "hard", "min_score_covered": 55},
        "gates": {"ci": ["coverage"]},
    })
    data = load_quality(tmp_path)
    assert data["coverage"]["lines"] == 77.0
    assert data["coverage"]["branches"] == 78.0
    assert data["mutation"]["min_score_covered"] == 55
    assert data["gates"]["ci"] == ["coverage"]
    lines, branches = module_thresholds(data, data["modules"][0])
    assert lines == 70.0 and branches == 78.0
    lines2, branches2 = module_thresholds(data, {"thresholds": {}})
    assert lines2 == 77.0 and branches2 == 78.0
