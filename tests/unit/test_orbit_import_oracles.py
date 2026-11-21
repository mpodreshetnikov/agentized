"""Mutation oracles for orbit_import.py (mutmut test_orbit_import_*.py)."""

from __future__ import annotations

from pathlib import Path

import agentized.orbit_import as oi_mod
from agentized.orbit_import import (
    MSG_NO_FM,
    MSG_NO_STATUS,
    VALUE_PLACEHOLDER,
    OrbitTaskDraft,
    _id_from_filename,
    _parse_scalar,
    _strip_quotes,
    agentized_markdown,
    collect_orbit_task_files,
    draft_from_orbit_file,
    existing_orbit_id_map,
    find_dest_by_orbit_id,
    format_report,
    import_orbit_tasks,
    is_safe_task_id,
    parse_yaml_front_matter,
    resolve_dest_path,
)
from agentized.task_schema import PLACEHOLDER_CLAIM, PLACEHOLDER_PARENT, PLACEHOLDER_SECTION, PLACEHOLDER_TAGS

def _fm(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path
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
def test_id_filename_collect_files(tmp_path: Path):
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
def test_draft_requires_status(tmp_path: Path):
    path = _fm(tmp_path / "T-0042.md", "---\nid: T-0042\ntitle: Only\n---\nZ\n")
    draft = draft_from_orbit_file(path)
    assert draft is not None
    assert draft.error == MSG_NO_STATUS
    assert draft.status == ""
def test_draft_fields_and_review_map(tmp_path: Path):
    path = _fm(
        tmp_path / "T-9.md",
        "---\nid: T-0009\ntitle: Rich\nstatus: review\nkind: feature\n"
        "priority: p2\nowner: a\nblocked_by: w\nexit: e\n"
        "depends_on: [T-0024]\nsuperseded_by: T-3\ntags: [a, b]\n"
        "value: From Orbit\n---\nBODY\n",
    )
    d = draft_from_orbit_file(path)
    assert d is not None
    assert d.status == "for-review"
    assert d.value == "From Orbit"
    assert d.depends_on == ["T-0024"]
    assert d.superseded_by == "T-3"
    assert any("review → for-review" in w for w in d.warnings)
def test_no_front_matter_is_error(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    _fm(src / "T-nofm.md", "# no yaml\n")
    dest = tmp_path / "dest"
    dest.mkdir()
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any(MSG_NO_FM in e for e in report.errors)
    assert report.would_write == []
def test_missing_status_is_error(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    _fm(src / "T-ns.md", "---\nid: T-0099\ntitle: X\n---\nB\n")
    dest = tmp_path / "dest"
    dest.mkdir()
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any(MSG_NO_STATUS in e for e in report.errors)
    assert report.would_write == []
def test_double_import_orbit_id_no_overwrite(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    _fm(
        src / "T-0023-live.md",
        "---\nid: T-0023\ntitle: Live\nstatus: open\nkind: feature\n"
        "priority: p3\n---\nB\n",
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    first = import_orbit_tasks(src, dest, dry_run=False)
    assert first.errors == []
    assert len(first.would_write) == 1
    written = Path(first.would_write[0])
    assert written.exists()
    assert "orbit_id: T-0023\n" in written.read_text(encoding="utf-8")
    assert (dest / "INDEX.md").exists()
    second = import_orbit_tasks(src, dest, dry_run=False)
    assert any("exists, no overwrite" in e and "orbit_id T-0023" in e for e in second.errors)
    assert second.would_write == []
    assert len(list(dest.glob("T-*.md"))) == 1
    assert str(src / "T-0023-live.md") in second.skipped
def test_depends_on_remapped_via_this_run(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    _fm(
        src / "T-0024.md",
        "---\nid: T-0024\ntitle: Dep\nstatus: open\nkind: feature\npriority: p3\n---\nB\n",
    )
    _fm(
        src / "T-0023.md",
        "---\nid: T-0023\ntitle: Live\nstatus: blocked\nkind: feature\n"
        "priority: p3\ndepends_on: [T-0024]\n---\nB\n",
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    assert len(report.drafts) == 2
    live = next(d for d in report.drafts if d.orbit_id == "T-0023")
    dep = next(d for d in report.drafts if d.orbit_id == "T-0024")
    assert live.depends_on == [dep.task_id]
    body = (dest / f"{live.task_id}.md").read_text(encoding="utf-8")
    assert f"depends_on: [{dep.task_id}]" in body
def test_unresolved_depends_on_errors_and_writes_nothing(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    _fm(
        src / "T-0023.md",
        "---\nid: T-0023\ntitle: Live\nstatus: open\nkind: feature\n"
        "priority: p3\ndepends_on: [T-missing]\n---\nB\n",
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert any("unresolved id 'T-missing'" in e for e in report.errors)
    assert report.would_write == []
    assert list(dest.glob("T-*.md")) == []
    assert not (dest / "INDEX.md").exists()
def test_unresolved_superseded_by_errors(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    _fm(
        src / "T-0017.md",
        "---\nid: T-0017\ntitle: Debt\nstatus: open\nkind: debt\n"
        "priority: p1\nsuperseded_by: T-ghost\n---\nB\n",
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert any("unresolved id 'T-ghost'" in e for e in report.errors)
    assert list(dest.glob("T-*.md")) == []
def test_partial_write_aborts_all(tmp_path: Path):
    """One bad file among many → no files written."""
    src = tmp_path / "src"
    src.mkdir()
    _fm(
        src / "T-ok.md",
        "---\nid: T-0100\ntitle: Ok\nstatus: open\nkind: feature\npriority: p2\n---\nB\n",
    )
    _fm(
        src / "T-bad.md",
        "---\nid: T-0101\ntitle: Bad\nstatus: open\nkind: feature\n"
        "priority: p2\ndepends_on: [T-ghost]\n---\nB\n",
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors
    assert list(dest.glob("T-*.md")) == []
def test_value_placeholder_when_missing(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    _fm(
        src / "T-v.md",
        "---\nid: T-0200\ntitle: V\nstatus: open\nkind: chore\npriority: p2\n---\nB\n",
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    assert any("no Orbit value" in w for w in report.warnings)
    text = Path(report.would_write[0]).read_text(encoding="utf-8")
    assert f"Ценность: {VALUE_PLACEHOLDER}\n" in text
def test_safe_path_and_format_report(tmp_path: Path, monkeypatch):
    assert is_safe_task_id("T-261116-abcd") is True
    assert is_safe_task_id("") is False
    assert is_safe_task_id("../x") is False
    assert resolve_dest_path(tmp_path, "T-261116-abcd") == (
        tmp_path / "T-261116-abcd.md"
    ).resolve()
    assert resolve_dest_path(tmp_path, "../escape") is None
    assert resolve_dest_path(tmp_path, "") is None
    real_resolve = Path.resolve
    def boom_resolve(self, *a, **k):
        if self.name == "T-261116-esc.md":
            class Escape(type(self)):
                def relative_to(self, _other):
                    raise ValueError("escape")
            return Escape(self)
        return real_resolve(self, *a, **k)
    monkeypatch.setattr(Path, "resolve", boom_resolve)
    assert resolve_dest_path(tmp_path, "T-261116-esc") is None
    empty = oi_mod.ImportReport(
        dry_run=True,
        sources=[],
        would_write=[],
        skipped=[],
        warnings=[],
        errors=[],
    )
    text = format_report(empty)
    assert "DRY-RUN" in text and "sources: 0" in text
def test_superseded_by_remapped_via_existing_orbit_id(tmp_path: Path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "T-261116-oldx.md").write_text(
        "# T-261116-oldx — Old\n\nстатус: done\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\norbit_id: T-0099\n"
        "acceptance_note: prior\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    _fm(
        src / "T-0017.md",
        "---\nid: T-0017\ntitle: Debt\nstatus: review\nkind: debt\n"
        "priority: p1\nsuperseded_by: T-0099\n---\nB\n",
    )
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    draft = report.drafts[0]
    assert draft.superseded_by == "T-261116-oldx"
    assert draft.status == "for-review"
def test_unknown_status_and_id_from_stem(tmp_path: Path):
    path = _fm(
        tmp_path / "T-0042-slug.md",
        "---\ntitle: NoId\nstatus: wip\nkind: feature\npriority: p2\n---\nB\n",
    )
    d = draft_from_orbit_file(path)
    assert d is not None
    assert d.task_id == "T-0042"
    assert "unknown Orbit status" in d.error
def test_tags_deps_variants(tmp_path: Path, monkeypatch):
    path = _fm(
        tmp_path / "T-x.md",
        "---\nid: T-0300\ntitle: V\nstatus: open\nkind: feature\n"
        "priority: p2\ntags: solo\ndepends_on: T-0024\n---\nB\n",
    )
    d = draft_from_orbit_file(path)
    assert d is not None
    assert d.tags == "solo"
    assert d.depends_on == ["T-0024"]
    path2 = _fm(
        tmp_path / "T-y.md",
        "---\nid: T-0301\ntitle: V\nstatus: open\nkind: feature\n"
        "priority: p2\ndepends_on: T-0024, T-0025\n---\nB\n",
    )
    d2 = draft_from_orbit_file(path2)
    assert d2 is not None
    assert "T-0024" in d2.depends_on
    d3 = draft_from_orbit_file(
        _fm(
            tmp_path / "T-z.md",
            "---\nid: T-0302\ntitle: V\nstatus: open\nkind: feature\n"
            "priority: p2\n---\nB\n",
        )
    )
    assert d3 is not None
    assert d3.depends_on == []
    real_parse = oi_mod.parse_yaml_front_matter
    def fake_parse(text: str):
        meta, body = real_parse(text)
        assert meta is not None
        meta["depends_on"] = 42  # neither str nor list
        return meta, body
    monkeypatch.setattr(oi_mod, "parse_yaml_front_matter", fake_parse)
    d4 = draft_from_orbit_file(
        _fm(
            tmp_path / "T-w.md",
            "---\nid: T-0303\ntitle: V\nstatus: open\nkind: feature\n"
            "priority: p2\ndepends_on: [T-1]\n---\nB\n",
        )
    )
    assert d4 is not None
    assert d4.depends_on == []
def test_import_read_error_unsafe_kind_dup_exists(tmp_path: Path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    bad = src / "T-bad.md"
    bad.write_bytes(b"\xff\xfe not utf8")
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any("read error" in e for e in report.errors)
    _fm(
        src / "T-unsafe.md",
        "---\nid: '../escape'\ntitle: X\nstatus: open\nkind: feature\n"
        "priority: p2\n---\nB\n",
    )
    report2 = import_orbit_tasks(src / "T-unsafe.md", dest, dry_run=True)
    assert any("unsafe id" in e for e in report2.errors)
    _fm(
        src / "T-kp.md",
        "---\nid: T-0400\ntitle: X\nstatus: open\nkind: nope\npriority: p9\n---\nB\n",
    )
    report3 = import_orbit_tasks(src / "T-kp.md", dest, dry_run=True)
    assert any("unknown kind" in e for e in report3.errors)
    tid_path = dest / "T-261116-zzzz.md"
    tid_path.write_text(
        "# T-261116-zzzz — Z\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\n",
        encoding="utf-8",
    )
    _fm(
        src / "T-zzzz.md",
        "---\nid: T-261116-zzzz\ntitle: Z\nstatus: open\nkind: feature\n"
        "priority: p2\n---\nB\n",
    )
    report4 = import_orbit_tasks(src / "T-zzzz.md", dest, dry_run=False)
    assert any("exists, no overwrite" in e for e in report4.errors)
def test_reserved_collision_realloc(tmp_path: Path, monkeypatch):
    import agentized.orbit_import as mod
    from agentized import task_schema as schema
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    ids = iter(["T-261121-aaaa", "T-261121-aaaa", "T-261121-bbbb"])
    alloc_args: list = []
    def fake_alloc(dest_arg):
        alloc_args.append(dest_arg)
        return next(ids)
    monkeypatch.setattr(schema, "allocate_task_id", fake_alloc)
    monkeypatch.setattr(mod, "allocate_task_id", fake_alloc)
    _fm(
        src / "T-1.md",
        "---\nid: T-0500\ntitle: A\nstatus: open\nkind: feature\npriority: p2\n---\nB\n",
    )
    _fm(
        src / "T-2.md",
        "---\nid: T-0501\ntitle: B\nstatus: open\nkind: feature\npriority: p2\n---\nB\n",
    )
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    assert {d.task_id for d in report.drafts} == {"T-261121-aaaa", "T-261121-bbbb"}
    assert alloc_args and all(a is dest for a in alloc_args)
    assert len(alloc_args) >= 3
def test_duplicate_id_in_batch_clears_writes(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    body = (
        "---\nid: T-261116-same\ntitle: A\nstatus: open\nkind: feature\n"
        "priority: p2\norbit_id: T-0777\n---\nB\n"
    )
    _fm(src / "T-a.md", body)
    _fm(src / "T-b.md", body.replace("title: A", "title: B"))
    _fm(
        src / "T-c.md",
        "---\nid: T-261116-uniq\ntitle: C\nstatus: open\nkind: feature\n"
        "priority: p2\n---\nB\n",
    )
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any("duplicate id" in e for e in report.errors)
    assert report.would_write == []
    assert str(src / "T-c.md") in report.sources
    assert str(src / "T-b.md") in report.skipped
def test_agentized_id_preserves_orbit_id_field(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    _fm(
        src / "T-one.md",
        "---\nid: T-261116-one1\ntitle: A\nstatus: open\nkind: feature\n"
        "priority: p2\norbit_id: T-0777\nvalue: Keep\n---\nB\n",
    )
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    assert report.drafts[0].orbit_id == "T-0777"
    text = Path(report.would_write[0]).read_text(encoding="utf-8")
    assert "orbit_id: T-0777" in text.splitlines()
    assert "Ценность: Keep" in text.splitlines()
def test_resolve_dest_none_after_safe_check(tmp_path: Path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    _fm(
        src / "T-aaa-escape.md",
        "---\nid: T-0600\ntitle: X\nstatus: open\nkind: feature\npriority: p2\n---\nB\n",
    )
    _fm(
        src / "T-zzz-after.md",
        "---\nid: T-0601\ntitle: Y\nstatus: open\nkind: feature\npriority: p2\n---\nB\n",
    )
    calls: list[str] = []
    def escape_then_ok(dest_tasks, task_id):
        calls.append(task_id)
        if task_id == "T-261121-esc1":
            return None
        return dest_tasks / f"{task_id}.md"
    alloc_ids = iter(["T-261121-esc1", "T-261121-esc2"])
    monkeypatch.setattr(oi_mod, "allocate_task_id", lambda _d: next(alloc_ids))
    monkeypatch.setattr(oi_mod, "resolve_dest_path", escape_then_ok)
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any("path escape" in e for e in report.errors)
    assert str(src / "T-zzz-after.md") in report.sources
    assert "T-261121-esc1" in calls and "T-261121-esc2" in calls
    assert str(src / "T-aaa-escape.md") in report.skipped
def test_draft_encoding_spy_and_field_matrix(tmp_path: Path, monkeypatch):
    enc: list = []
    real_read = Path.read_text
    def fake_read(self, encoding=None, errors=None):
        enc.append(encoding)
        return real_read(self, encoding=encoding, errors=errors)
    monkeypatch.setattr(Path, "read_text", fake_read)
    path = _fm(tmp_path / "T-0042-only.md", "---\nid: T-0042\ntitle: Only\nstatus: open\n---\nZ\n")
    draft = draft_from_orbit_file(path)
    assert enc == ["utf-8"]
    assert draft is not None
    assert (draft.task_id, draft.title, draft.status, draft.error) == ("T-0042", "Only", "open", "")
    assert (
        draft.kind,
        draft.priority,
        draft.owner,
        draft.blocked_by,
        draft.exit,
        draft.superseded_by,
        draft.depends_on,
        draft.tags,
    ) == ("", "", "", "", "", "", [], "")
    p_miss = _fm(tmp_path / "T-0043-miss.md", "---\nid: T-0043\nstatus: open\n---\nZ\n")
    assert draft_from_orbit_file(p_miss).title == "T-0043"
    p_none = _fm(tmp_path / "other.md", "---\ntitle: Z\nstatus: open\n---\nB\n")
    assert draft_from_orbit_file(p_none).task_id == ""
    p2 = _fm(
        tmp_path / "T-9.md",
        "---\nid: T-9\ntitle: T\nstatus: open\ntags: [a, b]\ndepends_on: T-1, T-2\n"
        "kind: feature\npriority: p2\nowner: a\nblocked_by: w\nexit: e\n"
        "superseded_by: T-3\n---\nBody\n",
    )
    d2 = draft_from_orbit_file(p2)
    assert (d2.tags, d2.depends_on, d2.kind, d2.priority, d2.owner) == (
        "a, b",
        ["T-1", "T-2"],
        "feature",
        "p2",
        "a",
    )
    assert (d2.blocked_by, d2.exit, d2.superseded_by) == ("w", "e", "T-3")
    assert d2.blocked_reason == "w"
    assert d2.blocked_deadline == "" and d2.review_note == "" and d2.pr == ""
    assert d2.error == "" and d2.warnings == []
    p3 = _fm(
        tmp_path / "T-8.md",
        "---\nid: T-8\ntitle:\nstatus:\ntags: solo\ndepends_on: 12\n---\nZ\n",
    )
    d3 = draft_from_orbit_file(p3)
    assert (d3.title, d3.status, d3.error, d3.tags, d3.depends_on) == (
        "T-8",
        "",
        MSG_NO_STATUS,
        "solo",
        ["12"],
    )
    assert d3.body == "Z\n"
    p3c = _fm(tmp_path / "T-0055-empty-id.md", "---\nid:\ntitle: E\nstatus: open\n---\nBody\n")
    assert draft_from_orbit_file(p3c).task_id == "T-0055"
    p3d = _fm(tmp_path / "T-0056-xxxx.md", "---\nid: XXXX\ntitle: E\nstatus: XXXX\n---\nBody\n")
    d3d = draft_from_orbit_file(p3d)
    assert d3d.task_id == "XXXX"
    assert d3d.status == "" and "unknown" in d3d.error
    real_parse2 = parse_yaml_front_matter
    def none_status(text):
        meta, body = real_parse2(text)
        meta = dict(meta)
        meta["status"] = None
        return meta, body
    monkeypatch.setattr(oi_mod, "parse_yaml_front_matter", none_status)
    p3e = _fm(tmp_path / "T-0057.md", "---\nid: T-0057\ntitle: N\nstatus: open\n---\nB\n")
    d3e = draft_from_orbit_file(p3e)
    assert d3e.status == "" and d3e.error == MSG_NO_STATUS
    monkeypatch.setattr(oi_mod, "parse_yaml_front_matter", real_parse2)
    p4 = _fm(tmp_path / "T-0024-shell.md", "---\ntitle: Shell\nstatus: open\n---\n\n# Shell\n")
    assert draft_from_orbit_file(p4).task_id == "T-0024"
    p5 = _fm(
        tmp_path / "T-9999-mismatch.md",
        "---\nid: T-0017\ntitle: Exact Title\nstatus: open\n---\nBody\n",
    )
    d5 = draft_from_orbit_file(p5)
    assert d5.task_id == "T-0017" and d5.title == "Exact Title"
    p6 = _fm(tmp_path / "T-rev.md", "---\nid: T-rev\ntitle: R\nstatus: review\n---\nB\n")
    d6 = draft_from_orbit_file(p6)
    assert d6.status == "for-review"
    assert d6.warnings == ["T-rev: Orbit status review → for-review (human)"]
    p7 = _fm(
        tmp_path / "T-blk.md",
        "---\nid: T-blk\ntitle: B\nstatus: blocked\nblocked_by: x\n"
        "blocked_reason: why\nblocked_deadline: 2026-11-21\n"
        "review_note: rn\npr: #26\nvalue: Ценность Orbit\n---\nB\n",
    )
    d7 = draft_from_orbit_file(p7)
    assert d7.blocked_reason == "why" and d7.blocked_deadline == "2026-11-21"
    assert d7.review_note == "rn" and d7.pr == "#26" and d7.error == ""
    assert d7.value == "Ценность Orbit"
def test_agentized_markdown_exact_matrix():
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
        value="V",
        body="Body\n",
    )
    expected = (
        "# T-9 — T\n\nстатус: in-progress\nтеги: a, b\n"
        f"родитель: {PLACEHOLDER_PARENT}\nclaim: {PLACEHOLDER_CLAIM}\n"
        "kind: feature\npriority: p2\nowner: a\ndepends_on: [T-1, T-2]\n"
        "blocked_by: w\nexit: e\nsuperseded_by: T-3\n\n"
        "Ценность: V\n\n## Цель\n\n"
        "Imported from orbit-tasks fixture (see preserved body below).\n\n"
        f"## Progress\n\n{PLACEHOLDER_SECTION}\n\n## Decision Log\n\n"
        f"{PLACEHOLDER_SECTION}\n\n"
        "## Imported body (preserved ids / history links)\n\n"
        "_source: `T-9.md`_\n\nBody\n"
    )
    assert agentized_markdown(draft) == expected
    empty_tags = OrbitTaskDraft(
        source=Path("T-9.md"),
        task_id="T-9",
        title="T",
        status="open",
        tags="",
        value="",
        body="B\n",
    )
    md_tags = agentized_markdown(empty_tags)
    assert f"теги: {PLACEHOLDER_TAGS}" in md_tags.splitlines()
    assert "acceptance_note:" not in md_tags
    rich = OrbitTaskDraft(
        source=Path("T-9.md"),
        task_id="T-9",
        title="T",
        status="blocked",
        blocked_reason="why",
        blocked_deadline="2026-11-21",
        review_note="rn",
        pr="#26",
        value=VALUE_PLACEHOLDER,
        body="B\n",
    )
    rich_md = agentized_markdown(rich)
    assert rich_md.splitlines()[6:10] == [
        "blocked_reason: why",
        "blocked_deadline: 2026-11-21",
        "review_note: rn",
        "pr: #26",
    ]
def test_import_report_as_dict_format_continue(tmp_path: Path, monkeypatch):
    """Strong oracles: as_dict keys, format WRITE/ERR/skip, continue-not-break."""
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "T-bad.md").write_text("nope\n", encoding="utf-8")
    (src / "T-ok.md").write_text(
        "---\nid: T-261116-ok01\ntitle: OK\nstatus: open\nkind: feature\n"
        "priority: p2\n---\nB\n",
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
        "---\nid: T-261116-zzok\ntitle: Z\nstatus: open\nkind: chore\npriority: p3\n---\nB\n",
        encoding="utf-8",
    )
    report = import_orbit_tasks(src, dest)
    assert report.dry_run is True
    assert report.errors
    assert report.would_write == []
    assert report.drafts == []
    d = report.as_dict()
    assert set(d) == {
        "dry_run",
        "sources",
        "would_write",
        "skipped",
        "warnings",
        "errors",
        "count",
    }
    assert d["dry_run"] is True
    assert d["count"] == 0
    assert d["would_write"] == []
    assert d["errors"] == report.errors
    assert d["warnings"] == report.warnings
    assert d["skipped"] == report.skipped
    assert d["sources"] == report.sources
    bad_path = str(src / "T-bad.md")
    assert bad_path in d["sources"] and bad_path in d["skipped"]
    assert str(src / "T-ok.md") in d["sources"]
    assert str(src / "T-zzok.md") in d["sources"]
    assert any(MSG_NO_FM in e for e in d["errors"])
    assert any("unsafe id" in e or "path escape" in e for e in d["errors"])
    assert any("unknown Orbit status" in e for e in d["errors"])
    assert any("read error" in e for e in d["errors"])
    assert any("unknown kind" in e for e in d["errors"])
    assert "None" not in "".join(d["skipped"])
    ke = next(e for e in d["errors"] if "unknown kind" in e)
    assert "XX; XX" not in ke and "unknown priority" in ke
    text = format_report(report)
    assert text.startswith("orbit-import DRY-RUN\n")
    assert text.endswith("\n")
    assert "  ERR: " in text and "  WARN: " in text and "  skip: " in text
    assert "  sources: " in text and "  would_write: 0" in text
    src2, dest2 = tmp_path / "src2", tmp_path / "dest2"
    src2.mkdir()
    dest2.mkdir()
    (src2 / "T-0023-slug.md").write_text(
        "---\nid: T-0023\ntitle: Short\nstatus: open\nkind: feature\npriority: p3\n---\nBody\n",
        encoding="utf-8",
    )
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
    wrote = import_orbit_tasks(src2, dest2, dry_run=False)
    assert wrote.dry_run is False
    assert wrote.errors == []
    assert format_report(wrote).startswith("orbit-import WRITE\n")
    assert "utf-8" in enc
    assert (True, True) in mk
    body = Path(wrote.would_write[0]).read_text(encoding="utf-8")
    assert "orbit_id: T-0023" in body
    assert any("converted →" in w for w in wrote.warnings)
    dest3 = tmp_path / "dest3"
    dest3.mkdir()
    real_map = oi_mod.existing_orbit_id_map
    monkeypatch.setattr(
        oi_mod, "existing_orbit_id_map", lambda _d: {"T-0888": "T-261116-miss"}
    )
    assert find_dest_by_orbit_id(dest3, "T-0888") is None
    monkeypatch.setattr(oi_mod, "existing_orbit_id_map", real_map)
    (dest3 / "T-261116-empty.md").write_text(
        "# T-261116-empty — E\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\norbit_id:\n",
        encoding="utf-8",
    )
    assert existing_orbit_id_map(dest3) == {}
    skip_rep = oi_mod.ImportReport(
        dry_run=True, sources=[], would_write=[], skipped=[], warnings=[], errors=[]
    )
    oi_mod._skip(skip_rep, Path("/tmp/skip-me.md"), "msg")
    assert skip_rep.skipped == ["/tmp/skip-me.md"]
    assert skip_rep.errors == ["msg"]
def test_import_kill_remaining_mutants(tmp_path: Path, monkeypatch):
    """Kill remaining import_orbit_tasks / value-fallback mutants."""
    real_parse = parse_yaml_front_matter
    def value_cyr(text):
        meta, body = real_parse(text)
        meta = dict(meta)
        meta.pop("value", None)
        meta["Ценность"] = "Only Cyrillic"
        return meta, body
    monkeypatch.setattr(oi_mod, "parse_yaml_front_matter", value_cyr)
    p_val = _fm(
        tmp_path / "T-val.md",
        "---\nid: T-0700\ntitle: V\nstatus: open\nkind: chore\npriority: p2\n---\nB\n",
    )
    d_val = draft_from_orbit_file(p_val)
    assert d_val is not None
    assert d_val.value == "Only Cyrillic"
    monkeypatch.setattr(oi_mod, "parse_yaml_front_matter", real_parse)
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    alloc_args: list = []
    real_alloc = oi_mod.allocate_task_id
    ids = iter(["T-261121-aa01", "T-261121-aa02"])
    def spy_alloc(dest_arg, **_k):
        alloc_args.append(dest_arg)
        try:
            return next(ids)
        except StopIteration:
            return real_alloc(dest_arg)
    monkeypatch.setattr(oi_mod, "allocate_task_id", spy_alloc)
    _fm(
        src / "T-0024.md",
        "---\nid: T-0024\ntitle: Dep\nstatus: open\nkind: feature\npriority: p3\n---\nB\n",
    )
    _fm(
        src / "T-0023.md",
        "---\nid: T-0023\ntitle: Live\nstatus: open\nkind: feature\n"
        "priority: p3\ndepends_on: [T-0024]\n---\nB\n",
    )
    enc: list = []
    real_write = Path.write_text
    def spy_write(self, data, encoding=None, errors=None, newline=None):
        enc.append((self.name, encoding))
        return real_write(self, data, encoding=encoding, errors=errors, newline=newline)
    monkeypatch.setattr(Path, "write_text", spy_write)
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    assert alloc_args and all(a == dest for a in alloc_args)
    assert any(w.startswith("T-0023:") or w.startswith("T-0024:") for w in report.warnings)
    live = next(d for d in report.drafts if d.orbit_id == "T-0023")
    dep = next(d for d in report.drafts if d.orbit_id == "T-0024")
    assert live.depends_on == [dep.task_id]
    assert live.task_id is not None and dep.task_id is not None
    assert ("INDEX.md", "utf-8") in enc
    assert {e for _, e in enc} == {"utf-8"}
    src_empty, dest_empty = tmp_path / "srcE", tmp_path / "destE"
    src_empty.mkdir()
    dest_empty.mkdir()
    mk: list = []
    real_mkdir = Path.mkdir
    def spy_mkdir(self, parents=False, exist_ok=False):
        mk.append(self)
        return real_mkdir(self, parents=parents, exist_ok=exist_ok)
    monkeypatch.setattr(Path, "mkdir", spy_mkdir)
    empty_rep = import_orbit_tasks(src_empty, dest_empty, dry_run=False)
    assert empty_rep.would_write == [] and mk == []
    src3, dest3 = tmp_path / "src3", tmp_path / "dest3"
    src3.mkdir()
    dest3.mkdir()
    (dest3 / "T-261116-seed.md").write_text(
        "# T-261116-seed — S\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\norbit_id: T-0090\n",
        encoding="utf-8",
    )
    _fm(
        src3 / "T-0090.md",
        "---\nid: T-0090\ntitle: DupOrbit\nstatus: open\nkind: feature\npriority: p2\n---\nB\n",
    )
    _fm(
        src3 / "T-0091.md",
        "---\nid: T-0091\ntitle: After\nstatus: open\nkind: feature\npriority: p2\n---\nB\n",
    )
    r3 = import_orbit_tasks(src3, dest3, dry_run=True)
    assert str(src3 / "T-0091.md") in r3.sources
    assert any("exists, no overwrite" in e and "orbit_id T-0090" in e for e in r3.errors)
    assert str(src3 / "T-0090.md") in r3.skipped
    src4, dest4 = tmp_path / "src4", tmp_path / "dest4"
    src4.mkdir()
    dest4.mkdir()
    (dest4 / "T-261116-have.md").write_text("x\n", encoding="utf-8")
    _fm(
        src4 / "T-have.md",
        "---\nid: T-261116-have\ntitle: H\nstatus: open\nkind: feature\npriority: p2\n---\nB\n",
    )
    _fm(
        src4 / "T-later.md",
        "---\nid: T-261116-late\ntitle: L\nstatus: open\nkind: feature\npriority: p2\n---\nB\n",
    )
    r4 = import_orbit_tasks(src4, dest4, dry_run=True)
    assert str(src4 / "T-later.md") in r4.sources
    assert any("exists, no overwrite" in e for e in r4.errors)
    assert str(src4 / "T-have.md") in r4.skipped
def test_import_kill_source_id_and_id_map(tmp_path: Path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    _fm(
        src / "T-dep.md",
        "---\nid: T-261116-dep1\ntitle: Dep\nstatus: open\nkind: feature\n"
        "priority: p2\norbit_id: T-0880\nvalue: HasValue\n---\nB\n",
    )
    _fm(
        src / "T-live.md",
        "---\nid: T-261116-liv1\ntitle: Live\nstatus: open\nkind: feature\n"
        "priority: p2\ndepends_on: [T-261116-dep1, T-0880]\n---\nB\n",
    )
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert report.errors == []
    live = next(d for d in report.drafts if d.task_id == "T-261116-liv1")
    assert live.depends_on == ["T-261116-dep1", "T-261116-dep1"]
    ph = [
        w
        for w in report.warnings
        if "no Orbit value" in w and "T-261116-liv1" in w
    ]
    assert len(ph) == 1
    assert ph[0].startswith("T-261116-liv1:")
    assert "None:" not in "".join(report.warnings)
    src2, dest2 = tmp_path / "src2", tmp_path / "dest2"
    src2.mkdir()
    dest2.mkdir()
    _fm(
        src2 / "T-bad.md",
        "---\nid: T-261116-bad1\ntitle: Bad\nstatus: open\nkind: feature\n"
        "priority: p2\ndepends_on: [T-261116-miss]\n---\nB\n",
    )
    bad = import_orbit_tasks(src2, dest2, dry_run=True)
    assert bad.errors
    assert any("unresolved id" in e for e in bad.errors)
    assert all(isinstance(w, str) for w in bad.warnings)
    assert None not in bad.warnings
    assert any(
        isinstance(w, str) and "T-261116-bad1" in w and "unresolved id" in w
        for w in bad.warnings
    )
    src3, dest3 = tmp_path / "src3", tmp_path / "dest3"
    src3.mkdir()
    dest3.mkdir()
    _fm(
        src3 / "T-a.md",
        "---\nid: T-261116-aaa1\ntitle: A\nstatus: open\nkind: feature\n"
        "priority: p2\nvalue: V\n---\nB\n",
    )
    _fm(
        src3 / "T-b.md",
        "---\nid: T-261116-bbb1\ntitle: B\nstatus: open\nkind: feature\n"
        "priority: p2\ndepends_on: [T-261116-aaa1]\nvalue: V\n---\nB\n",
    )
    ok = import_orbit_tasks(src3, dest3, dry_run=True)
    assert ok.errors == []
    b = next(d for d in ok.drafts if d.task_id == "T-261116-bbb1")
    assert b.depends_on == ["T-261116-aaa1"]
def test_kill_done_acceptance_orbit_placeholder_skip_paths(tmp_path: Path):
    done = OrbitTaskDraft(source=Path("T-d.md"), task_id="T-d", title="D", status="done", exit="shipped", value="V", body="B\n")
    assert "acceptance_note: shipped" in agentized_markdown(done).splitlines()
    assert "acceptance_note:" not in agentized_markdown(OrbitTaskDraft(source=Path("T-o.md"), task_id="T-o", title="O", status="open", exit="x", value="V", body="B\n"))
    (tmp_path / "T-261116-uscr.md").write_text("# T-261116-uscr — U\n\nстатус: open\nтеги: _(нет)_\nродитель: _(пусто)_\nclaim: _(пусто)_\norbit_id: _(пусто)_\n", encoding="utf-8")
    assert existing_orbit_id_map(tmp_path) == {}
    assert existing_orbit_id_map(tmp_path / "missing") == {}
    rep = oi_mod.ImportReport(dry_run=True, sources=[], would_write=[], skipped=[], warnings=[], errors=[])
    oi_mod._skip(rep, Path("/t.md"), "warn-only", err=False)
    assert rep.warnings == ["warn-only"] and rep.errors == []
    d = OrbitTaskDraft(source=Path("a.md"), task_id="T-261116-a", title="A", status="open", depends_on=["T-1"], value="V", body="B")
    fr = oi_mod.ImportReport(dry_run=True, sources=[], would_write=[], skipped=[], warnings=[], errors=[], drafts=[d])
    text = format_report(fr)
    assert f"  depends_on T-261116-a: {oi_mod.format_id_list(['T-1'])}" in text.splitlines()
