"""Mutation oracles for orbit_import.py (mutmut test_orbit_import_*.py)."""

from __future__ import annotations

from pathlib import Path

from agentized.orbit_import import (
    OrbitTaskDraft,
    _id_from_filename,
    _parse_scalar,
    _strip_quotes,
    agentized_markdown,
    collect_orbit_task_files,
    draft_from_orbit_file,
    format_report,
    import_orbit_tasks,
    parse_yaml_front_matter,
)
from agentized.orbit_import import is_safe_task_id, resolve_dest_path
import agentized.orbit_import as oi_mod
from agentized.task_schema import (
    DEFAULT_VALUE,
    PLACEHOLDER_CLAIM,
    PLACEHOLDER_PARENT,
    PLACEHOLDER_SECTION,
)


def test_parse_scalar_and_yaml_continue():
    assert _strip_quotes("x") == "x"
    assert _strip_quotes("'a'") == "a"
    assert _strip_quotes("''") == ""
    assert _strip_quotes('""') == ""
    assert _strip_quotes("'ab'") == "ab"
    assert _strip_quotes("XaX") == "XaX"
    assert _parse_scalar("[]") == []
    assert _parse_scalar("[a, b]") == ["a", "b"]
    assert _parse_scalar("['a', \"b\"]") == ["a", "b"]
    assert _parse_scalar('"x"') == "x"
    assert _parse_scalar("'y'") == "y"
    assert _parse_scalar("  ") == ""
    assert _parse_scalar("[unterminated") == "[unterminated"
    assert _parse_scalar('"half') == '"half'
    assert _parse_scalar("'half") == "'half"
    assert _parse_scalar("plain") == "plain"
    meta, body = parse_yaml_front_matter("---\n# c\n\nid: T-1\nbad line\n---\nB\n")
    assert meta == {"id": "T-1"} and body == "B\n"
    meta2, _ = parse_yaml_front_matter("---\nbad\nid: T-2\ntitle: X\n---\n")
    assert meta2 == {"id": "T-2", "title": "X"}
    meta3, _ = parse_yaml_front_matter("---\n\n# only\nid: T-3\n---\n")
    assert meta3 == {"id": "T-3"}


def test_id_filename_collect_dedupe(tmp_path: Path):
    assert _id_from_filename("T-0023") == "T-0023"
    assert _id_from_filename("T-0023-slug") == "T-0023"
    assert _id_from_filename("T-260829-304") == "T-260829-304"
    assert _id_from_filename("T-260829-304-slug") == "T-260829-304"
    assert _id_from_filename("T-x") == "T-x"
    (tmp_path / "T-1.md").write_text("x", encoding="utf-8")
    nested = tmp_path / "docs"
    nested.mkdir()
    (nested / "T-2.md").write_text("x", encoding="utf-8")
    assert sorted(p.name for p in collect_orbit_task_files(tmp_path)) == [
        "T-1.md",
        "T-2.md",
    ]
    assert collect_orbit_task_files(tmp_path / "T-1.md") == [tmp_path / "T-1.md"]


def test_draft_encoding_spy_and_defaults(tmp_path: Path, monkeypatch):
    enc: list = []
    real_read = Path.read_text

    def fake_read(self, encoding=None, errors=None):
        enc.append(encoding)
        return real_read(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", fake_read)
    path = tmp_path / "T-0042-only.md"
    path.write_text("---\nid: T-0042\ntitle: Only\n---\nZ\n", encoding="utf-8")
    draft = draft_from_orbit_file(path)
    assert enc == ["utf-8"]
    assert draft is not None
    assert isinstance(draft.task_id, str) and draft.task_id == "T-0042"
    assert isinstance(draft.title, str) and draft.title == "Only"
    assert (
        draft.status,
        draft.kind,
        draft.priority,
        draft.owner,
        draft.blocked_by,
        draft.exit,
        draft.superseded_by,
        draft.depends_on,
        draft.tags,
    ) == ("idea", "", "", "", "", "", "", [], "")
    # missing title → title equals task_id (str, not None)
    p_miss = tmp_path / "T-0043-miss.md"
    p_miss.write_text("---\nid: T-0043\n---\nZ\n", encoding="utf-8")
    d_miss = draft_from_orbit_file(p_miss)
    assert d_miss is not None
    assert d_miss.title == "T-0043"
    # no id + non-T stem → empty string task_id (not None)
    p_none = tmp_path / "other.md"
    p_none.write_text("---\ntitle: Z\nstatus: open\n---\nB\n", encoding="utf-8")
    d_none = draft_from_orbit_file(p_none)
    assert d_none is not None
    assert d_none.task_id == ""
    p2 = tmp_path / "T-9.md"
    p2.write_text(
        "---\nid: T-9\ntitle: T\nstatus: open\ntags: [a, b]\ndepends_on: T-1, T-2\n"
        "kind: feature\npriority: p2\nowner: a\nblocked_by: w\nexit: e\n"
        "superseded_by: T-3\n---\nBody\n",
        encoding="utf-8",
    )
    d2 = draft_from_orbit_file(p2)
    assert d2 is not None
    assert (d2.tags, d2.depends_on, d2.kind, d2.priority, d2.owner) == (
        "a, b",
        ["T-1", "T-2"],
        "feature",
        "p2",
        "a",
    )
    assert (d2.blocked_by, d2.exit, d2.superseded_by) == ("w", "e", "T-3")
    assert d2.blocked_reason == "w"  # falls back to blocked_by
    assert d2.blocked_deadline == "" and d2.review_note == "" and d2.pr == ""
    assert d2.error == "" and d2.warnings == []
    p3 = tmp_path / "T-8.md"
    p3.write_text(
        "---\nid: T-8\ntitle:\nstatus:\ntags: solo\ndepends_on: 12\n---\nZ\n",
        encoding="utf-8",
    )
    d3 = draft_from_orbit_file(p3)
    assert d3 is not None
    assert (d3.title, d3.status, d3.tags, d3.depends_on) == ("T-8", "idea", "solo", ["12"])
    assert d3.body == "Z\n"
    # empty id string falls back to filename
    p3c = tmp_path / "T-0055-empty-id.md"
    p3c.write_text("---\nid:\ntitle: E\nstatus: open\n---\nBody\n", encoding="utf-8")
    d3c = draft_from_orbit_file(p3c)
    assert d3c is not None and d3c.task_id == "T-0055"
    # literal XXXX id is kept (not treated as empty sentinel)
    p3d = tmp_path / "T-0056-xxxx.md"
    p3d.write_text("---\nid: XXXX\ntitle: E\nstatus: XXXX\n---\nBody\n", encoding="utf-8")
    d3d = draft_from_orbit_file(p3d)
    assert d3d is not None
    assert d3d.task_id == "XXXX"
    assert d3d.status == "" and "unknown" in d3d.error
    # status None via monkeypatch
    real_parse2 = parse_yaml_front_matter

    def none_status(text):
        meta, body = real_parse2(text)
        meta = dict(meta)
        meta["status"] = None
        return meta, body

    monkeypatch.setattr("agentized.orbit_import.parse_yaml_front_matter", none_status)
    p3e = tmp_path / "T-0057.md"
    p3e.write_text("---\nid: T-0057\ntitle: N\nstatus: open\n---\nB\n", encoding="utf-8")
    assert draft_from_orbit_file(p3e).status == "idea"
    monkeypatch.setattr("agentized.orbit_import.parse_yaml_front_matter", real_parse2)
    p3b = tmp_path / "T-88.md"
    p3b.write_text("---\nid: T-88\ntitle: X\nstatus: open\n---\nZ\n", encoding="utf-8")
    real_parse = parse_yaml_front_matter

    def fake_parse(text):
        meta, body = real_parse(text)
        meta = dict(meta)
        meta["depends_on"] = 99
        return meta, body

    monkeypatch.setattr("agentized.orbit_import.parse_yaml_front_matter", fake_parse)
    assert draft_from_orbit_file(p3b).depends_on == []
    monkeypatch.setattr("agentized.orbit_import.parse_yaml_front_matter", real_parse)
    p4 = tmp_path / "T-0024-shell.md"
    p4.write_text("---\ntitle: Shell\nstatus: open\n---\n\n# Shell\n", encoding="utf-8")
    assert draft_from_orbit_file(p4).task_id == "T-0024"
    p5 = tmp_path / "T-9999-mismatch.md"
    p5.write_text(
        "---\nid: T-0017\ntitle: Exact Title\nstatus: open\n---\nBody\n", encoding="utf-8"
    )
    d5 = draft_from_orbit_file(p5)
    assert d5.task_id == "T-0017" and d5.title == "Exact Title"
    p6 = tmp_path / "T-rev.md"
    p6.write_text("---\nid: T-rev\ntitle: R\nstatus: review\n---\nB\n", encoding="utf-8")
    d6 = draft_from_orbit_file(p6)
    assert d6.status == "for-review"
    assert d6.warnings == ["T-rev: Orbit status review → for-review (human)"]
    p7 = tmp_path / "T-blk.md"
    p7.write_text(
        "---\nid: T-blk\ntitle: B\nstatus: blocked\nblocked_by: x\n"
        "blocked_reason: why\nblocked_deadline: 2026-11-21\n"
        "review_note: rn\npr: #26\n---\nB\n",
        encoding="utf-8",
    )
    d7 = draft_from_orbit_file(p7)
    assert d7.blocked_reason == "why" and d7.blocked_deadline == "2026-11-21"
    assert d7.review_note == "rn" and d7.pr == "#26" and d7.error == ""


def test_agentized_markdown_exact():
    draft = OrbitTaskDraft(
        source=Path("T-9.md"),
        task_id="T-9",
        title="T",
        status="in-progress",
        kind="feature",
        priority="p2",
        owner="a",
        tags="a, b",
        depends_on=["T-1", "T-2"],
        blocked_by="w",
        exit="e",
        superseded_by="T-3",
        body="Body\n",
    )
    expected = (
        "# T-9 — T\n\nстатус: in-progress\nтеги: a, b\n"
        f"родитель: {PLACEHOLDER_PARENT}\nclaim: {PLACEHOLDER_CLAIM}\n"
        "kind: feature\npriority: p2\nowner: a\ndepends_on: [T-1, T-2]\n"
        "blocked_by: w\nexit: e\nsuperseded_by: T-3\n\n"
        f"Ценность: {DEFAULT_VALUE}\n\n## Цель\n\n"
        "Imported from orbit-tasks fixture (see preserved body below).\n\n"
        f"## Progress\n\n{PLACEHOLDER_SECTION}\n\n## Decision Log\n\n"
        f"{PLACEHOLDER_SECTION}\n\n"
        "## Imported body (preserved ids / history links)\n\n"
        "_source: `T-9.md`_\n\nBody\n"
    )
    assert agentized_markdown(draft) == expected
    done = OrbitTaskDraft(
        source=Path("T-9.md"), task_id="T-9", title="T", status="done", exit="shipped", body="B\n"
    )
    md = agentized_markdown(done)
    assert "acceptance_note: shipped" in md
    assert "статус: done" in md
    empty = OrbitTaskDraft(
        source=Path("T-9.md"), task_id="T-9", title="T", status="open", body="   \n"
    )
    assert "_source: `T-9.md`_" in agentized_markdown(empty)
    rich = OrbitTaskDraft(
        source=Path("T-9.md"),
        task_id="T-9",
        title="T",
        status="blocked",
        blocked_reason="why",
        blocked_deadline="2026-11-21",
        review_note="rn",
        pr="#26",
        body="B\n",
    )
    rich_md = agentized_markdown(rich)
    assert rich_md.splitlines()[6:10] == [
        "blocked_reason: why",
        "blocked_deadline: 2026-11-21",
        "review_note: rn",
        "pr: #26",
    ]


def test_import_report_format_and_write(tmp_path: Path, monkeypatch):
    assert is_safe_task_id("T-261116-abcd") and not is_safe_task_id("T-foo/bar")
    assert not is_safe_task_id("") and resolve_dest_path(tmp_path, "T-../../tmp") is None
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "T-bad.md").write_text("nope\n", encoding="utf-8")
    (src / "T-ok.md").write_text(
        "---\nid: T-261116-ok01\ntitle: OK\nstatus: open\ndepends_on: [T-1]\n---\nB\n",
        encoding="utf-8",
    )
    (src / "T-trav.md").write_text(
        "---\nid: T-../../tmp/x\ntitle: X\nstatus: open\n---\nB\n", encoding="utf-8"
    )
    (src / "T-wip2.md").write_text(
        "---\nid: T-261116-wip1\ntitle: W\nstatus: wip\n---\nB\n", encoding="utf-8"
    )
    (src / "T-bin.md").write_bytes(b"---\nid: T-261116-bin1\n---\n\xff\xfe")
    (src / "T-badkind.md").write_text(
        "---\nid: T-261116-kind\ntitle: K\nstatus: open\nkind: nope\npriority: p9\n---\nB\n",
        encoding="utf-8",
    )
    (src / "T-zzok.md").write_text(
        "---\nid: T-261116-zzok\ntitle: Z\nstatus: open\n---\nB\n",
        encoding="utf-8",
    )
    report = import_orbit_tasks(src, dest)
    assert report.dry_run is True
    ok_path = str(src / "T-ok.md")
    bad_path = str(src / "T-bad.md")
    trav = str(src / "T-trav.md")
    wip = str(src / "T-wip2.md")
    binp = str(src / "T-bin.md")
    kindp = str(src / "T-badkind.md")
    dest_ok = str(dest / "T-261116-ok01.md")
    d = report.as_dict()
    assert d["dry_run"] is True
    dest_zz = str(dest / "T-261116-zzok.md")
    assert d["count"] == 2
    assert d["would_write"] == [dest_ok, dest_zz]
    assert ok_path in d["sources"] and bad_path in d["sources"]
    assert bad_path in d["skipped"]
    assert any("no front matter" in w for w in d["warnings"])
    assert any("unsafe id" in e or "path escape" in e for e in d["errors"])
    assert any("unknown Orbit status" in e for e in d["errors"])
    assert any("read error" in e for e in d["errors"])
    assert any("unknown kind" in e for e in d["errors"])
    assert d["errors"] == report.errors
    assert d["warnings"] == report.warnings
    assert d["skipped"] == report.skipped
    assert d["sources"] == report.sources
    assert set(d) == {"dry_run", "sources", "would_write", "skipped", "warnings", "errors", "count"}
    assert not any("no front matter" in e for e in d["errors"])
    assert (
        trav in d["sources"]
        and wip in d["sources"]
        and binp in d["sources"]
        and kindp in d["sources"]
    )
    assert str(src / "T-zzok.md") in d["sources"] and dest_zz in d["would_write"]
    assert any(trav in e for e in d["errors"]) or any("unsafe" in e for e in d["errors"])

    assert bad_path in d["skipped"]
    assert binp in d["skipped"] and any(binp in e for e in d["errors"])
    assert trav in d["skipped"] and any("unsafe id" in e or "path escape" in e for e in d["errors"])
    assert wip in d["skipped"] and any("unknown Orbit status" in e for e in d["errors"])
    assert kindp in d["skipped"]
    ke = next(e for e in d["errors"] if "unknown kind" in e)
    assert "XX; XX" not in ke and "unknown kind" in ke and "unknown priority" in ke
    text = format_report(report)
    assert text.startswith("orbit-import DRY-RUN\n")
    assert text.endswith("\n")
    assert f"  + {dest_ok}\n" in text
    assert "  depends_on T-261116-ok01: [T-1]\n" in text
    assert f"  ERR: " in text and f"  WARN: " in text and f"  skip: " in text
    assert "  sources: " in text and "  would_write: 2" in text
    assert "  errors: " in text and "  skipped: " in text

    mk: list = []
    enc: list = []
    real_mkdir, real_write = Path.mkdir, Path.write_text

    def fake_mkdir(self, parents=False, exist_ok=False):
        mk.append((parents, exist_ok))
        return real_mkdir(self, parents=parents, exist_ok=exist_ok)

    def fake_write(self, data, encoding=None, errors=None, newline=None):
        enc.append(encoding)
        return real_write(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    monkeypatch.setattr(Path, "write_text", fake_write)
    wrote = import_orbit_tasks(src, dest, dry_run=False)
    assert wrote.dry_run is False and (dest / "T-261116-ok01.md").exists()
    assert format_report(wrote).startswith("orbit-import WRITE\n")
    assert mk == [(True, True), (True, True)] and enc == ["utf-8", "utf-8"]
    (dest / "T-261116-ok01.md").write_text("existing\n", encoding="utf-8")
    over = import_orbit_tasks(src, dest, dry_run=False)
    assert sum(1 for e in over.errors if "no overwrite" in e) >= 2 and "None" not in over.skipped
    src2, dest2 = tmp_path / "src2", tmp_path / "dest2"
    src2.mkdir()
    dest2.mkdir()
    (src2 / "T-0023-slug.md").write_text(
        "---\nid: T-0023\ntitle: Short\nstatus: open\n---\nBody\n", encoding="utf-8"
    )
    short = import_orbit_tasks(src2, dest2, dry_run=False)
    assert not short.errors and "orbit_id: T-0023" in Path(short.would_write[0]).read_text(
        encoding="utf-8"
    )
    assert any("converted →" in w for w in short.warnings)
    src4, dest4 = tmp_path / "src4", tmp_path / "dest4"
    src4.mkdir()
    dest4.mkdir()
    for name, oid in (("T-a.md", "T-0091"), ("T-b.md", "T-0092")):
        (src4 / name).write_text(
            f"---\nid: {oid}\ntitle: S\nstatus: open\n---\nB\n", encoding="utf-8"
        )
    ids = ["T-261116-fix", "T-261116-fix", "T-261116-next"]
    real_alloc = oi_mod.allocate_task_id

    def _alloc(dest, **_k):
        assert dest is not None
        return ids.pop(0)

    monkeypatch.setattr("agentized.orbit_import.allocate_task_id", _alloc)
    coll = import_orbit_tasks(src4, dest4, dry_run=True)
    assert coll.would_write == [str(dest4 / "T-261116-fix.md"), str(dest4 / "T-261116-next.md")]
    monkeypatch.setattr("agentized.orbit_import.allocate_task_id", real_alloc)
    src3 = tmp_path / "src3"
    src3.mkdir()
    for name in ("T-a.md", "T-b.md"):
        (src3 / name).write_text(
            "---\nid: T-261116-same\ntitle: A\nstatus: open\n---\nB\n", encoding="utf-8"
        )
    (src3 / "T-c.md").write_text(
        "---\nid: T-261116-uniq\ntitle: C\nstatus: open\n---\nB\n", encoding="utf-8"
    )
    dup = import_orbit_tasks(src3, tmp_path / "d3")
    assert (
        any("duplicate id" in e for e in dup.errors)
        and str(tmp_path / "d3" / "T-261116-uniq.md") in dup.would_write
    )
    assert "None" not in dup.skipped

    (src2 / "T-0098.md").write_text(
        "---\nid: T-0098\ntitle: S\nstatus: open\n---\nB\n", encoding="utf-8"
    )
    monkeypatch.setattr("agentized.orbit_import.resolve_dest_path", lambda *a, **k: None)
    esc = import_orbit_tasks(src2, dest2, dry_run=True)
    assert sum(1 for e in esc.errors if "path escape" in e) >= 2 and "None" not in esc.skipped
