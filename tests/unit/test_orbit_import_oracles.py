"""Mutation oracles for orbit_import.py (mutmut test_orbit_import_*.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import agentized.orbit_import as oi_mod
import agentized.task_schema as _ts
from agentized.orbit_import import (
    MSG_NO_FM,
    MSG_NO_STATUS,
    MSG_NO_VALUE,
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
from agentized.task_schema import TASK_ID_RE


def _fm(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _orb(
    path: Path,
    tid: str | None = "T-0001",
    title: str | None = "T",
    status: str | None = "open",
    value: str | None = "V",
    body: str = "B\n",
    **fields,
) -> Path:
    lines: list[str] = []
    if tid is not None:
        lines.append(f"id: {tid}")
    if title is not None:
        lines.append(f"title: {title}")
    if status is not None:
        lines.append(f"status: {status}")
    lines.extend(f"{k}: {v}" for k, v in fields.items())
    if value is not None:
        lines.append(f"value: {value}")
    return _fm(path, "---\n" + "\n".join(lines) + f"\n---\n{body}")


def _feat(path: Path, tid: str, title: str = "T", priority: str = "p2", **kw) -> Path:
    return _orb(path, tid=tid, title=title, kind="feature", priority=priority, **kw)


def _sd(tmp: Path, src_n: str = "src", dest_n: str = "dest") -> tuple[Path, Path]:
    src, dest = tmp / src_n, tmp / dest_n
    src.mkdir(exist_ok=True)
    dest.mkdir(exist_ok=True)
    return src, dest


def _dr(tmp: Path, name: str, **kw):
    return draft_from_orbit_file(_orb(tmp / name, **kw))


def _draft(**kw):
    base = dict(source=Path("x.md"), task_id="T-x", title="T", status="open", value="V", body="B\n")
    base.update(kw)
    return OrbitTaskDraft(**base)


def test_parse_scalar_and_yaml_continue():
    assert (
        _strip_quotes("x"),
        _strip_quotes("'a'"),
        _strip_quotes("''"),
        _strip_quotes('""'),
        _strip_quotes("'ab'"),
        _strip_quotes("XaX"),
    ) == ("x", "a", "", "", "ab", "XaX")
    assert _parse_scalar("[]") == []
    assert _parse_scalar("[a, b]") == ["a", "b"]
    assert _parse_scalar("['a', \"b\"]") == ["a", "b"]
    assert (
        _parse_scalar('"x"'),
        _parse_scalar("'y'"),
        _parse_scalar("  "),
        _parse_scalar("[unterminated"),
        _parse_scalar('"half'),
        _parse_scalar("'half"),
        _parse_scalar("plain"),
    ) == ("x", "y", "", "[unterminated", '"half', "'half", "plain")
    meta, body = parse_yaml_front_matter("---\n# c\n\nid: T-1\nbad line\n---\nB\n")
    assert meta == {"id": "T-1"} and body == "B\n"
    meta2, _ = parse_yaml_front_matter("---\nbad\nid: T-2\ntitle: X\n---\n")
    assert meta2 == {"id": "T-2", "title": "X"}
    meta3, _ = parse_yaml_front_matter("---\n\n# only\nid: T-3\n---\n")
    assert meta3 == {"id": "T-3"}


def test_id_filename_collect_files(tmp_path: Path):
    assert [
        _id_from_filename(x)
        for x in ("T-0023", "T-0023-slug", "T-260829-304", "T-260829-304-slug", "T-x")
    ] == ["T-0023", "T-0023", "T-260829-304", "T-260829-304", "T-x"]
    (tmp_path / "T-1.md").write_text("x", encoding="utf-8")
    nested = tmp_path / "docs"
    nested.mkdir()
    (nested / "T-2.md").write_text("x", encoding="utf-8")
    assert sorted(p.name for p in collect_orbit_task_files(tmp_path)) == ["T-1.md", "T-2.md"]
    assert collect_orbit_task_files(tmp_path / "T-1.md") == [tmp_path / "T-1.md"]


def test_draft_requires_status(tmp_path: Path):
    draft = draft_from_orbit_file(
        _orb(tmp_path / "T-0042.md", tid="T-0042", title="Only", status=None, value="V", body="Z\n")
    )
    assert draft is not None
    assert draft.error == MSG_NO_STATUS
    assert draft.status == ""


def test_draft_fields_and_review_map(tmp_path: Path):
    d = draft_from_orbit_file(
        _feat(
            tmp_path / "T-9.md",
            "T-0009",
            title="Rich",
            status="review",
            owner="a",
            blocked_by="w",
            exit="e",
            depends_on="[T-0024]",
            superseded_by="T-3",
            tags="[a, b]",
            value="From Orbit",
            body="BODY\n",
        )
    )
    assert d is not None
    assert d.status == "for-review"
    assert d.value == "From Orbit"
    assert d.depends_on == ["T-0024"]
    assert d.superseded_by == "T-3"
    assert any("review → for-review" in w for w in d.warnings)


def test_no_front_matter_is_error(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _fm(src / "T-nofm.md", "# no yaml\n")
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any(MSG_NO_FM in e for e in report.errors)
    assert report.would_write == []


def test_missing_status_is_error(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _orb(src / "T-ns.md", tid="T-0099", title="X", status=None, value="V")
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any(MSG_NO_STATUS in e for e in report.errors)
    assert report.would_write == []


def test_double_import_orbit_id_no_overwrite(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _feat(src / "T-0023-live.md", "T-0023", title="Live", priority="p3", value="V")
    first = import_orbit_tasks(src, dest, dry_run=False)
    assert first.errors == []
    assert len(first.would_write) == 1
    written = Path(first.would_write[0])
    assert written.exists()
    assert "orbit_id: T-0023\n" in written.read_text(encoding="utf-8")
    assert (dest / "INDEX.md").exists()
    second = import_orbit_tasks(src, dest, dry_run=False)
    assert second.errors == []
    assert any("exists, no overwrite" in w and "orbit_id T-0023" in w for w in second.warnings)
    assert second.would_write == []
    assert len(list(dest.glob("T-*.md"))) == 1
    assert str(src / "T-0023-live.md") in second.skipped
    dry = import_orbit_tasks(src, dest, dry_run=True)
    assert dry.errors == []
    assert str(src / "T-0023-live.md") in dry.skipped


def test_depends_on_remapped_via_this_run(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _orb(src / "T-0024.md", tid="T-0024", title="Dep", kind="feature", priority="p3")
    _feat(
        src / "T-0023.md",
        "T-0023",
        title="Live",
        status="blocked",
        priority="p3",
        depends_on="[T-0024]",
    )
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    assert len(report.drafts) == 2
    live = next(d for d in report.drafts if d.orbit_id == "T-0023")
    dep = next(d for d in report.drafts if d.orbit_id == "T-0024")
    assert live.depends_on == [dep.task_id]
    body = (dest / f"{live.task_id}.md").read_text(encoding="utf-8")
    assert f"depends_on: [{dep.task_id}]" in body


def test_unresolved_depends_on_errors_and_writes_nothing(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _feat(src / "T-0023.md", "T-0023", title="Live", priority="p3", depends_on="[T-missing]")
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert any("unresolved id 'T-missing'" in e for e in report.errors)
    assert report.would_write == []
    assert list(dest.glob("T-*.md")) == []
    assert not (dest / "INDEX.md").exists()


def test_unresolved_superseded_by_errors(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _orb(
        src / "T-0017.md",
        tid="T-0017",
        title="Debt",
        kind="debt",
        priority="p1",
        superseded_by="T-ghost",
    )
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert any("unresolved id 'T-ghost'" in e for e in report.errors)
    assert list(dest.glob("T-*.md")) == []


def test_partial_write_aborts_all(tmp_path: Path):
    """One bad file among many → no files written."""
    src, dest = _sd(tmp_path)
    _orb(src / "T-ok.md", tid="T-0100", title="Ok", kind="feature", priority="p2")
    _feat(src / "T-bad.md", "T-0101", title="Bad", depends_on="[T-ghost]")
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors
    assert list(dest.glob("T-*.md")) == []


def test_missing_value_skips_with_clear_error(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _orb(src / "T-v.md", tid="T-0200", title="V", kind="chore", priority="p2", value=None)
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert any(MSG_NO_VALUE in e for e in report.errors)
    assert report.would_write == []
    assert list(dest.glob("T-*.md")) == []


def test_safe_path_and_format_report(tmp_path: Path, monkeypatch):
    assert is_safe_task_id("T-261116-abcd") is True
    assert is_safe_task_id("") is False and is_safe_task_id("../x") is False
    assert resolve_dest_path(tmp_path, "T-261116-abcd") == (tmp_path / "T-261116-abcd.md").resolve()
    assert (
        resolve_dest_path(tmp_path, "../escape") is None and resolve_dest_path(tmp_path, "") is None
    )
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
        dry_run=True, sources=[], would_write=[], skipped=[], warnings=[], errors=[]
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
    _orb(
        src / "T-0017.md",
        tid="T-0017",
        title="Debt",
        status="review",
        kind="debt",
        priority="p1",
        superseded_by="T-0099",
    )
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    draft = report.drafts[0]
    assert draft.superseded_by == "T-261116-oldx"
    assert draft.status == "for-review"


def test_unknown_status_and_id_from_stem(tmp_path: Path):
    d = draft_from_orbit_file(
        _orb(
            tmp_path / "T-0042-slug.md",
            tid=None,
            title="NoId",
            status="wip",
            kind="feature",
            priority="p2",
        )
    )
    assert d is not None
    assert d.task_id == "T-0042"
    assert "unknown Orbit status" in d.error


def test_tags_deps_variants(tmp_path: Path, monkeypatch):
    d = draft_from_orbit_file(
        _feat(tmp_path / "T-x.md", "T-0300", title="V", tags="solo", depends_on="T-0024")
    )
    assert d is not None
    assert d.tags == "solo"
    assert d.depends_on == ["T-0024"]
    d2 = draft_from_orbit_file(
        _feat(tmp_path / "T-y.md", "T-0301", title="V", depends_on="T-0024, T-0025")
    )
    assert d2 is not None
    assert "T-0024" in d2.depends_on
    d3 = draft_from_orbit_file(
        _orb(tmp_path / "T-z.md", tid="T-0302", title="V", kind="feature", priority="p2")
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
    d4 = draft_from_orbit_file(_feat(tmp_path / "T-w.md", "T-0303", title="V", depends_on="[T-1]"))
    assert d4 is not None
    assert d4.depends_on == []


def test_import_read_error_unsafe_kind_dup_exists(tmp_path: Path, monkeypatch):
    src, dest = _sd(tmp_path)
    (src / "T-bad.md").write_bytes(b"\xff\xfe not utf8")
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any("read error" in e for e in report.errors)
    _feat(src / "T-unsafe.md", "T-../escape", title="X")
    report2 = import_orbit_tasks(src / "T-unsafe.md", dest, dry_run=True)
    assert any("unsafe id" in e for e in report2.errors)
    _orb(src / "T-kp.md", tid="T-0400", title="X", kind="nope", priority="p9")
    report3 = import_orbit_tasks(src / "T-kp.md", dest, dry_run=True)
    assert any("unknown kind" in e for e in report3.errors)
    (dest / "T-261116-zzzz.md").write_text(
        "# T-261116-zzzz — Z\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\n",
        encoding="utf-8",
    )
    _orb(src / "T-zzzz.md", tid="T-261116-zzzz", title="Z", kind="feature", priority="p2")
    report4 = import_orbit_tasks(src / "T-zzzz.md", dest, dry_run=False)
    assert report4.errors == []
    assert any("exists, no overwrite" in w for w in report4.warnings)


def test_reserved_collision_stable_id(tmp_path: Path, monkeypatch):
    """First digest slot occupied → _stable_task_id advances to next suffix."""
    import hashlib
    import agentized.orbit_import as mod
    from agentized.task_schema import utc_now_stamp

    src, dest = _sd(tmp_path)
    day = utc_now_stamp()
    digest = hashlib.sha256(b"T-0500").hexdigest()
    first = f"T-{day}-{digest[:4]}"
    (dest / f"{first}.md").write_text("# occupied\n", encoding="utf-8")
    _orb(src / "T-1.md", tid="T-0500", title="A", kind="feature", priority="p2")
    dry = import_orbit_tasks(src, dest, dry_run=True)
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert dry.errors == report.errors == []
    assert len(report.drafts) == 1
    second = f"T-{day}-{digest[4:8]}"
    assert dry.drafts[0].task_id == report.drafts[0].task_id == second
    assert TASK_ID_RE.match(report.drafts[0].task_id)
    assert second != first
    assert callable(mod._stable_task_id)  # mutmut path coverage


def test_duplicate_id_in_batch_clears_writes(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _feat(src / "T-a.md", "T-261116-same", title="A", orbit_id="T-0777")
    _feat(src / "T-b.md", "T-261116-same", title="B", orbit_id="T-0777")
    _orb(src / "T-c.md", tid="T-261116-uniq", title="C", kind="feature", priority="p2")
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any("duplicate id" in e for e in report.errors)
    assert report.would_write == []
    assert str(src / "T-c.md") in report.sources
    assert str(src / "T-b.md") in report.skipped


def test_agentized_id_preserves_orbit_id_field(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _feat(src / "T-one.md", "T-261116-one1", title="A", orbit_id="T-0777", value="Keep")
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    assert report.drafts[0].orbit_id == "T-0777"
    text = Path(report.would_write[0]).read_text(encoding="utf-8")
    assert "orbit_id: T-0777" in text.splitlines()
    assert "Ценность: Keep" in text.splitlines()


def test_resolve_dest_none_after_safe_check(tmp_path: Path, monkeypatch):
    src, dest = _sd(tmp_path)
    _orb(src / "T-aaa-escape.md", tid="T-0600", title="X", kind="feature", priority="p2")
    _orb(src / "T-zzz-after.md", tid="T-0601", title="Y", kind="feature", priority="p2")
    calls: list[str] = []

    def escape_then_ok(dest_tasks, task_id):
        calls.append(task_id)
        if task_id == "T-261121-esc1":
            return None
        return dest_tasks / f"{task_id}.md"

    alloc_ids = iter(["T-261121-esc1", "T-261121-esc2"])
    monkeypatch.setattr(oi_mod, "_stable_task_id", lambda _d, _oid, _r: next(alloc_ids))
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
    draft = _dr(tmp_path, "T-0042-only.md", tid="T-0042", title="Only", body="Z\n")
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
    assert _dr(tmp_path, "T-0043-miss.md", tid="T-0043", title=None, body="Z\n").title == "T-0043"
    assert _dr(tmp_path, "other.md", tid=None, title="Z").task_id == ""
    d2 = _dr(
        tmp_path,
        "T-9.md",
        tid="T-9",
        tags="[a, b]",
        depends_on="T-1, T-2",
        kind="feature",
        priority="p2",
        owner="a",
        blocked_by="w",
        exit="e",
        superseded_by="T-3",
        body="Body\n",
    )
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
    d3 = draft_from_orbit_file(
        _fm(
            tmp_path / "T-8.md",
            "---\nid: T-8\ntitle:\nstatus:\ntags: solo\ndepends_on: 12\nvalue: V\n---\nZ\n",
        )
    )
    assert (d3.title, d3.status, d3.error, d3.tags, d3.depends_on) == (
        "T-8",
        "",
        MSG_NO_STATUS,
        "solo",
        ["12"],
    )
    assert d3.body == "Z\n"
    assert (
        draft_from_orbit_file(
            _fm(
                tmp_path / "T-0055-empty-id.md",
                "---\nid:\ntitle: E\nstatus: open\nvalue: V\n---\nBody\n",
            )
        ).task_id
        == "T-0055"
    )
    d3d = _dr(tmp_path, "T-0056-xxxx.md", tid="XXXX", title="E", status="XXXX", body="Body\n")
    assert d3d.task_id == "XXXX"
    assert d3d.status == "" and "unknown" in d3d.error
    real_parse2 = parse_yaml_front_matter

    def none_status(text):
        meta, body = real_parse2(text)
        meta = dict(meta)
        meta["status"] = None
        return meta, body

    monkeypatch.setattr(oi_mod, "parse_yaml_front_matter", none_status)
    d3e = _dr(tmp_path, "T-0057.md", tid="T-0057", title="N")
    assert d3e.status == "" and d3e.error == MSG_NO_STATUS
    monkeypatch.setattr(oi_mod, "parse_yaml_front_matter", real_parse2)
    assert (
        _dr(tmp_path, "T-0024-shell.md", tid=None, title="Shell", body="\n# Shell\n").task_id
        == "T-0024"
    )
    d5 = _dr(tmp_path, "T-9999-mismatch.md", tid="T-0017", title="Exact Title", body="Body\n")
    assert d5.task_id == "T-0017" and d5.title == "Exact Title"
    d6 = _dr(tmp_path, "T-rev.md", tid="T-rev", title="R", status="review")
    assert d6.status == "for-review"
    assert d6.warnings == ["T-rev: Orbit status review → for-review (human)"]
    d7 = _dr(
        tmp_path,
        "T-blk.md",
        tid="T-blk",
        title="B",
        status="blocked",
        blocked_by="x",
        blocked_reason="why",
        blocked_deadline="2026-11-21",
        review_note="rn",
        pr="#26",
        value="Ценность Orbit",
    )
    assert d7.blocked_reason == "why" and d7.blocked_deadline == "2026-11-21"
    assert d7.review_note == "rn" and d7.pr == "#26" and d7.error == ""
    assert d7.value == "Ценность Orbit"


def test_agentized_markdown_exact_matrix():
    draft = _draft(
        source=Path("T-9.md"),
        task_id="T-9",
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
        f"родитель: {_ts.PLACEHOLDER_EMPTY}\nclaim: {_ts.PLACEHOLDER_EMPTY}\n"
        "kind: feature\npriority: p2\nowner: a\ndepends_on: [T-1, T-2]\n"
        "blocked_by: w\nexit: e\nsuperseded_by: T-3\n\n"
        "Ценность: V\n\n## Цель\n\n"
        "Imported from orbit-tasks fixture (see preserved body below).\n\n"
        f"## Progress\n\n{_ts.PLACEHOLDER_SECTION}\n\n## Decision Log\n\n"
        f"{_ts.PLACEHOLDER_SECTION}\n\n"
        "## Imported body (preserved ids / history links)\n\n"
        "_source: `T-9.md`_\n\nBody\n"
    )
    assert agentized_markdown(draft) == expected
    md_tags = agentized_markdown(
        _draft(source=Path("T-9.md"), task_id="T-9", tags="", value="V", body="B\n")
    )
    assert f"теги: {_ts.PLACEHOLDER_TAGS}" in md_tags.splitlines()
    assert "acceptance_note:" not in md_tags
    rich_md = agentized_markdown(
        _draft(
            source=Path("T-9.md"),
            task_id="T-9",
            status="blocked",
            blocked_reason="why",
            blocked_deadline="2026-11-21",
            review_note="rn",
            pr="#26",
            value="V",
            body="B\n",
        )
    )
    assert rich_md.splitlines()[6:10] == [
        "blocked_reason: why",
        "blocked_deadline: 2026-11-21",
        "review_note: rn",
        "pr: #26",
    ]


def test_import_report_as_dict_format_continue(tmp_path: Path, monkeypatch):
    """Strong oracles: as_dict keys, format WRITE/ERR/skip, continue-not-break."""
    src, dest = _sd(tmp_path)
    (src / "T-bad.md").write_text("nope\n", encoding="utf-8")
    _feat(src / "T-ok.md", "T-261116-ok01", title="OK")
    _orb(src / "T-trav.md", tid="T-../../tmp/x", title="X")
    _orb(src / "T-wip2.md", tid="T-261116-wip1", title="W", status="wip")
    (src / "T-bin.md").write_bytes(b"---\nid: T-261116-bin1\nvalue: V\n---\n\xff\xfe")
    _orb(src / "T-badkind.md", tid="T-261116-kind", title="K", kind="nope", priority="p9")
    _orb(src / "T-zzok.md", tid="T-261116-zzok", title="Z", kind="chore", priority="p3")
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
    src2, dest2 = _sd(tmp_path, "src2", "dest2")
    _feat(src2 / "T-0023-slug.md", "T-0023", title="Short", priority="p3", body="Body\n")
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
    monkeypatch.setattr(oi_mod, "existing_orbit_id_map", lambda _d: {"T-0888": "T-261116-miss"})
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


def test_non_orbit_md_warned_and_zero_sources_errors(tmp_path: Path):
    src, dest = _sd(tmp_path)
    (src / "README.md").write_text("# hi\n", encoding="utf-8")
    (src / "notes.md").write_text("x\n", encoding="utf-8")
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert report.sources == []
    assert report.errors == ["no Orbit task files (T-*.md) found under source"]
    assert any("README.md" in w for w in report.warnings)
    assert any("notes.md" in w for w in report.warnings)


def test_kill_survivors_pack(tmp_path: Path, monkeypatch):
    assert (
        "acceptance_note: shipped"
        in agentized_markdown(
            _draft(source=Path("T-d.md"), task_id="T-d", title="D", status="done", exit="shipped")
        ).splitlines()
    )
    assert "acceptance_note:" not in agentized_markdown(
        _draft(source=Path("T-o.md"), task_id="T-o", title="O", exit="x")
    )
    (tmp_path / "T-261116-uscr.md").write_text(
        "# T-261116-uscr — U\n\nстатус: open\nтеги: _(нет)_\nродитель: _(пусто)_\n"
        "claim: _(пусто)_\norbit_id: _(пусто)_\n",
        encoding="utf-8",
    )
    assert existing_orbit_id_map(tmp_path) == existing_orbit_id_map(tmp_path / "missing") == {}
    assert oi_mod._remap_id("T-1", {"T-1": "T-261116-aaa"}) == "T-261116-aaa"
    assert oi_mod._remap_id("T-miss", {"T-1": "T-261116-aaa"}) is None
    d = _draft(source=Path("a.md"), task_id="T-261116-aaa", title="A", depends_on=["T-1"], body="B")
    rep = oi_mod.ImportReport(
        dry_run=True, sources=[], would_write=[], skipped=[], warnings=[], errors=[], drafts=[d]
    )
    assert (
        f"  depends_on T-261116-aaa: {oi_mod.format_id_list(['T-1'])}"
        in format_report(rep).splitlines()
    )
    real_parse = parse_yaml_front_matter

    def value_cyr(raw):
        meta, body = real_parse(raw)
        return {**dict(meta), "Ценность": "Only Cyrillic"}, body

    monkeypatch.setattr(oi_mod, "parse_yaml_front_matter", value_cyr)
    assert (
        draft_from_orbit_file(
            _orb(
                tmp_path / "T-val.md",
                tid="T-0700",
                title="V",
                kind="chore",
                priority="p2",
                value=None,
            )
        ).value
        == "Only Cyrillic"
    )
    monkeypatch.setattr(oi_mod, "parse_yaml_front_matter", real_parse)
    src, dest = _sd(tmp_path)
    alloc_args: list = []
    real_stable = oi_mod._stable_task_id
    ids = iter(["T-261121-aa01", "T-261121-aa02"])

    def spy_stable(dest_arg, orbit_id, reserved):
        alloc_args.append(dest_arg)
        try:
            return next(ids)
        except StopIteration:
            return real_stable(dest_arg, orbit_id, reserved)

    monkeypatch.setattr(oi_mod, "_stable_task_id", spy_stable)
    _orb(src / "T-0024.md", tid="T-0024", title="Dep", kind="feature", priority="p3")
    _feat(src / "T-0023.md", "T-0023", title="Live", priority="p3", depends_on="[T-0024]")
    enc: list = []
    real_write = Path.write_text

    def spy_write(self, data, encoding=None, errors=None, newline=None):
        enc.append((self.name, encoding))
        return real_write(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", spy_write)
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == [] and alloc_args and all(a == dest for a in alloc_args)
    live = next(x for x in report.drafts if x.orbit_id == "T-0023")
    dep = next(x for x in report.drafts if x.orbit_id == "T-0024")
    assert live.depends_on == [dep.task_id]
    assert ("INDEX.md", "utf-8") in enc and {e for _, e in enc} == {"utf-8"}
    src_o, dest_o = _sd(tmp_path, "srcO", "destO")
    (dest_o / "T-261116-seed.md").write_text(
        "# T-261116-seed — S\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\norbit_id: T-0090\n",
        encoding="utf-8",
    )
    _orb(src_o / "T-0090.md", tid="T-0090", title="D", kind="feature", priority="p2")
    _orb(src_o / "T-0091.md", tid="T-0091", title="A", kind="feature", priority="p2")
    r_o = import_orbit_tasks(src_o, dest_o, dry_run=True)
    assert str(src_o / "T-0090.md") in r_o.skipped and len(r_o.would_write) == 1
    src_h, dest_h = _sd(tmp_path, "srcH", "destH")
    (dest_h / "T-261116-have.md").write_text("x\n", encoding="utf-8")
    _orb(src_h / "T-have.md", tid="T-261116-have", title="H", kind="feature", priority="p2")
    _orb(src_h / "T-later.md", tid="T-261116-late", title="L", kind="feature", priority="p2")
    r_h = import_orbit_tasks(src_h, dest_h, dry_run=True)
    assert str(src_h / "T-have.md") in r_h.skipped and len(r_h.would_write) == 1
    src_d, dest_d = tmp_path / "srcD", tmp_path / "destD"
    src_d.mkdir()
    _orb(src_d / "T-ok.md", tid="T-261116-ok99", title="OK", kind="feature", priority="p2")
    mk: list = []
    real_mkdir = Path.mkdir

    def spy_mkdir(self, parents=False, exist_ok=False):
        mk.append(self)
        return real_mkdir(self, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", spy_mkdir)
    dry = import_orbit_tasks(src_d, dest_d, dry_run=True)
    assert dry.would_write and mk == [] and not dest_d.exists()
    src2, dest2 = _sd(tmp_path, "src2", "dest2")
    _feat(src2 / "T-dep.md", "T-261116-dep1", title="Dep", value="HasValue")
    _feat(src2 / "T-orb.md", "T-261116-orb1", title="Orb", orbit_id="T-0990", value="HasValue")
    _feat(
        src2 / "T-live.md",
        "T-261116-liv1",
        title="Live",
        depends_on="[T-261116-dep1, T-0990]",
        value="LiveVal",
    )
    r2 = import_orbit_tasks(src2, dest2, dry_run=True)
    assert r2.errors == []
    live2 = next(x for x in r2.drafts if x.task_id == "T-261116-liv1")
    assert live2.depends_on == ["T-261116-dep1", "T-261116-orb1"]
    assert live2.value == "LiveVal"
    src3, dest3 = _sd(tmp_path, "src3", "dest3")
    _feat(src3 / "T-bad.md", "T-261116-bad1", title="Bad", depends_on="[T-261116-miss]")
    bad = import_orbit_tasks(src3, dest3, dry_run=True)
    assert bad.errors and None not in bad.warnings
    assert any("T-261116-bad1" in w and "unresolved id" in w for w in bad.warnings)


def test_dry_run_ids_match_write_ids(tmp_path: Path):
    src, dest = _sd(tmp_path)
    _orb(src / "T-0023.md", tid="T-0023", title="Live", kind="feature", priority="p3")
    dry = import_orbit_tasks(src, dest, dry_run=True)
    assert dry.errors == []
    dry_ids = sorted(d.task_id for d in dry.drafts)
    write = import_orbit_tasks(src, dest, dry_run=False)
    assert write.errors == []
    write_ids = sorted(d.task_id for d in write.drafts)
    assert dry_ids == write_ids
    assert dry_ids[0].startswith("T-") and TASK_ID_RE.match(dry_ids[0])


def test_non_t_id_clear_error(tmp_path: Path):
    from agentized.orbit_import import MSG_BAD_ID

    src, dest = _sd(tmp_path)
    _orb(src / "T-bad.md", tid="BAD-1", title="X", kind="feature", priority="p2")
    _orb(src / "T-ok.md", tid="T-0800", title="Ok", kind="feature", priority="p2")
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any(MSG_BAD_ID.format(raw="BAD-1") in e for e in report.errors)
    assert str(src / "T-bad.md") in report.skipped
    assert str(src / "T-ok.md") in report.sources  # continue not break
    assert str(src / "T-ok.md") not in report.skipped


def test_missing_value_continue_not_break(tmp_path: Path):
    src, dest = _sd(tmp_path)
    # Lexical: T-aaa-noval before T-zzz-has so break would drop later source.
    _feat(src / "T-aaa-noval.md", "T-0810", title="No", value=None)
    _orb(src / "T-zzz-has.md", tid="T-0811", title="Yes", kind="feature", priority="p2")
    report = import_orbit_tasks(src, dest, dry_run=True)
    assert any(MSG_NO_VALUE in e for e in report.errors)
    assert str(src / "T-aaa-noval.md") in report.skipped
    assert str(src / "T-zzz-has.md") in report.sources
    assert str(src / "T-zzz-has.md") not in report.skipped


def test_reserved_tracks_converted_ids(tmp_path: Path, monkeypatch):
    src, dest = _sd(tmp_path)
    calls: list[frozenset[str]] = []

    def fake_stable(dest_arg, orbit_id, reserved):
        calls.append(frozenset(reserved))
        if "T-261121-same" not in reserved:
            return "T-261121-same"
        return "T-261121-diff"

    monkeypatch.setattr(oi_mod, "_stable_task_id", fake_stable)
    _orb(src / "T-a.md", tid="T-0900", title="A", kind="feature", priority="p2")
    _orb(src / "T-b.md", tid="T-0901", title="B", kind="feature", priority="p2")
    report = import_orbit_tasks(src, dest, dry_run=False)
    assert report.errors == []
    ids = [d.task_id for d in report.drafts]
    assert ids == ["T-261121-same", "T-261121-diff"]
    assert calls[1] == frozenset({"T-261121-same"})


def test_stable_id_exhausted_raises(tmp_path: Path):
    import hashlib
    from agentized.orbit_import import _stable_task_id
    from agentized.task_schema import utc_now_stamp

    dest = tmp_path / "dest"
    dest.mkdir()
    day = utc_now_stamp()
    digest = hashlib.sha256(b"T-EXHAUST").hexdigest()
    for i in range(16):
        (dest / f"T-{day}-{digest[i * 4 : i * 4 + 4]}.md").write_text("# x\n", encoding="utf-8")
    with pytest.raises(RuntimeError) as ei:
        _stable_task_id(dest, "T-EXHAUST", set())
    assert str(ei.value) == "no free stable id for orbit_id 'T-EXHAUST'"
