"""Mutation oracles for task_schema.py (mutmut test_task_schema_*.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentized import task_schema as ts
from agentized.task_schema import (
    DEFAULT_GOAL,
    ID_ALLOCATE_ERROR,
    INDEX_ACTIVE_STATUSES,
    INDEX_FOOTER,
    INDEX_INTRO,
    INDEX_SEARCH,
    INDEX_TITLE,
    PLACEHOLDER_CLAIM,
    PLACEHOLDER_EMPTY,
    PLACEHOLDER_PARENT,
    PLACEHOLDER_SECTION,
    PLACEHOLDER_TAGS,
    _strip_one_quote,
    _strip_outer_brackets,
    allocate_task_id,
    append_progress,
    dependency_cycles_for_dir,
    dependency_graph,
    find_dependency_cycles,
    parse_id_list,
    parse_task,
    rebuild_task_index,
    render_task_file,
    set_field,
    unknown_depends_on_ids,
    utc_now_stamp,
    map_orbit_status,
    validate_kind_priority,
    validate_task_status,
)

FIXED = datetime(2020, 1, 2, 3, 4, tzinfo=UTC)


def test_status_gate_getattr_reexport_and_miss():
    import pytest

    from agentized import status_gates as sg
    from agentized import task_schema as ts

    assert ts.INDEX_ACTIVE_STATUSES is sg.INDEX_ACTIVE_STATUSES
    assert ts.ALL_STATUSES is sg.ALL_STATUSES
    assert ts.CANONICAL_STATUSES is sg.CANONICAL_STATUSES
    assert ts.MSG_UNKNOWN_STATUS is sg.MSG_UNKNOWN_STATUS
    assert ts.is_known_status is sg.is_known_status
    assert ts.normalize_status is sg.normalize_status
    assert ts.ACTIVE_STATUSES is sg.INDEX_ACTIVE_STATUSES
    assert ts.ACTIVE_STATUSES == (
        "open",
        "queue",
        "in-progress",
        "self-review",
        "for-review",
        "blocked",
    )
    with pytest.raises(AttributeError, match="has no attribute 'not_a_status_export'"):
        _ = ts.not_a_status_export


def test_status_vocabulary_and_format_ids():
    from agentized import status_gates as sg
    from agentized.task_schema import (
        ACTIVE_STATUSES,
        ALL_STATUSES,
        CANONICAL_STATUSES,
        FIELD_RE,
        MSG_UNKNOWN_STATUS,
        format_id_list,
        is_known_status,
    )
    from agentized.tasks import ACTIVE_STATUSES as TASKS_ACTIVE

    assert CANONICAL_STATUSES is sg.CANONICAL_STATUSES
    assert ALL_STATUSES is sg.ALL_STATUSES
    assert INDEX_ACTIVE_STATUSES is sg.INDEX_ACTIVE_STATUSES
    assert MSG_UNKNOWN_STATUS is sg.MSG_UNKNOWN_STATUS
    assert "self-review" in ALL_STATUSES and "canceled" in ALL_STATUSES
    assert ACTIVE_STATUSES is INDEX_ACTIVE_STATUSES is TASKS_ACTIVE
    assert r":[ \t]*(.*)$" in FIELD_RE.pattern
    assert r":\s*" not in FIELD_RE.pattern
    assert format_id_list(["T-1", ""]) == "[T-1]"
    assert format_id_list(["T-1", "T-2"]) == "[T-1, T-2]"
    assert format_id_list(["a", "b", "c"]) == "[a, b, c]"
    assert format_id_list([]) == ""
    assert parse_id_list("_(пусто)_") == []
    from agentized.task_schema import KINDS, PRIORITIES, normalize_status

    assert normalize_status is sg.normalize_status
    assert is_known_status is sg.is_known_status
    assert normalize_status("dropped") == "canceled"
    assert normalize_status("queued") == "queue"
    assert normalize_status("") == "" and normalize_status(None) == ""
    assert normalize_status("  Open ") == "open"
    assert is_known_status("open") and is_known_status("dropped")
    assert not is_known_status("wip") and not is_known_status("")
    assert not is_known_status(None)
    assert validate_task_status("open") == []
    assert validate_task_status("dropped") == []
    assert validate_task_status("") == ["status is required"]
    assert validate_task_status(None) == ["status is required"]
    assert validate_task_status("wip") == [MSG_UNKNOWN_STATUS.format(st="wip")]
    assert validate_kind_priority("", "") == []
    assert validate_kind_priority("feature", "p1") == []
    assert validate_kind_priority("nope", "p9") == [
        f"unknown kind 'nope'; expected one of {KINDS}",
        f"unknown priority 'p9'; expected one of {PRIORITIES}",
    ]
    assert validate_kind_priority("nope", "") == [
        f"unknown kind 'nope'; expected one of {KINDS}",
    ]
    assert validate_kind_priority("", "p9") == [
        f"unknown priority 'p9'; expected one of {PRIORITIES}",
    ]


def test_field_re_empty_parent_keeps_claim(tmp_path: Path):
    """AGE-43/45: empty header fields must not swallow the next line."""
    path = tmp_path / "T-261116-fld1.md"
    path.write_text(
        "# T-261116-fld1 — F\n\nстатус: open\nтеги:\nродитель:\nclaim: alice\n",
        encoding="utf-8",
    )
    meta = parse_task(path)
    assert meta is not None
    assert meta.parent == ""
    assert meta.claim == "alice"
    assert meta.tags == ""
    # newline after colon must not be eaten into value
    swallowed = tmp_path / "T-261116-fld2.md"
    swallowed.write_text(
        "# T-261116-fld2 — F\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель:\nclaim: bob\nkind: feature\n",
        encoding="utf-8",
    )
    m2 = parse_task(swallowed)
    assert m2 is not None
    assert m2.parent == ""
    assert m2.claim == "bob"
    assert m2.kind == "feature"


def test_set_field_age43_empty_line_keeps_next_header():
    """AGE-43 (#34 on main): empty field line must not swallow the next header."""
    text = "# T-1 — x\n\nродитель:\nclaim: alice\n"
    assert set_field(text, "родитель", "P") == ("# T-1 — x\n\nродитель: P\nclaim: alice\n")
    src = Path(ts.__file__).read_text(encoding="utf-8")
    assert "re.escape(field_name)}:[ \\t]*.*$" in src
    assert "not \\s*" in src


def test_unknown_depends_on_ids(tmp_path: Path):
    (tmp_path / "T-261116-dep1.md").write_text(
        "# T-261116-dep1 — A\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\ndepends_on: [T-261116-missing]\n",
        encoding="utf-8",
    )
    (tmp_path / "T-261116-dep2.md").write_text(
        "# T-261116-dep2 — B\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\ndepends_on: [T-261116-dep1]\n",
        encoding="utf-8",
    )
    from agentized.task_schema import list_tasks

    tasks = list_tasks(tmp_path)
    missing = unknown_depends_on_ids(tasks)
    assert missing == [("T-261116-dep1", "T-261116-missing")]


def _spy_now(monkeypatch, stamp=FIXED):
    from agentized import tasks as tasks_mod

    seen: list = []

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            seen.append(tz)
            return stamp

    monkeypatch.setattr(tasks_mod, "datetime", FakeDateTime)
    return seen


def test_utc_now_stamp_spy(monkeypatch):
    from datetime import timezone

    seen = _spy_now(monkeypatch)
    assert utc_now_stamp() == "200102"
    assert seen == [timezone.utc]


def test_parse_id_list_cycles_graph(tmp_path: Path):
    assert _strip_outer_brackets("[T-a]") == "T-a"
    assert _strip_outer_brackets("[T-a") == "[T-a"
    assert _strip_outer_brackets("T-a]") == "T-a]"
    assert _strip_one_quote("'x'") == "x"
    assert _strip_one_quote("''") == ""
    assert _strip_one_quote("'ab'") == "ab"
    assert _strip_one_quote('"ab"') == "ab"
    assert _strip_one_quote("x") == "x"
    assert _strip_one_quote("'x") == "'x"
    assert _strip_one_quote('"x') == '"x'
    assert _strip_one_quote('x"') == 'x"'
    assert _strip_one_quote("XhelloX") == "XhelloX"
    assert parse_id_list("  [T-a, T-b]  ") == ["T-a", "T-b"]
    assert parse_id_list("[]") == []
    assert parse_id_list("[T-a]") == ["T-a"]
    assert parse_id_list("'T-1'") == ["T-1"]
    assert parse_id_list('"T-2"') == ["T-2"]
    assert parse_id_list("['T-3', \"T-4\"]") == ["T-3", "T-4"]
    assert find_dependency_cycles({"A": ["B"], "B": ["C"], "C": ["B"]}) == [["B", "C", "B"]]
    two = find_dependency_cycles({"A": ["B"], "B": ["A"], "C": ["D"], "D": ["C"]})
    assert sorted(tuple(c) for c in two) == [("A", "B", "A"), ("C", "D", "C")]

    class T:
        def __init__(self, task_id, depends_on):
            self.task_id = task_id
            self.depends_on = depends_on

    class NoAttrs:
        pass

    assert dependency_graph([T(None, ["A"]), T("B", [])]) == {"B": []}
    assert dependency_graph([T("C", "T-1 T-2")]) == {"C": ["T-1", "T-2"]}
    assert dependency_graph([NoAttrs()]) == {}
    (tmp_path / "T-261116-aaa.md").write_text(
        "# T-261116-aaa — A\n\nстатус: open\nтеги: _(нет)_\nродитель: _(п)_\n"
        "claim: _(п)_\ndepends_on: [T-261116-bbb]\n",
        encoding="utf-8",
    )
    (tmp_path / "T-261116-bbb.md").write_text(
        "# T-261116-bbb — B\n\nстатус: open\nтеги: _(нет)_\nродитель: _(п)_\n"
        "claim: _(п)_\ndepends_on: [T-261116-aaa]\n",
        encoding="utf-8",
    )
    assert dependency_cycles_for_dir(tmp_path) == [["T-261116-aaa", "T-261116-bbb", "T-261116-aaa"]]


def test_allocate_task_id_token_width(tmp_path: Path, monkeypatch):
    from agentized import tasks as tasks_mod

    seen: list = []
    seq = iter(["aaaa", "bbbb"])
    monkeypatch.setattr(tasks_mod.secrets, "token_hex", lambda n: seen.append(n) or next(seq))
    assert allocate_task_id(tmp_path, day="200102") == "T-200102-aaaa"
    assert seen == [2]
    stamps: list = []

    def fake_stamp():
        stamps.append(1)
        return "200102"

    monkeypatch.setattr(tasks_mod, "utc_now_stamp", fake_stamp)
    monkeypatch.setattr(tasks_mod.secrets, "token_hex", lambda n: "cccc")
    assert allocate_task_id(tmp_path) == "T-200102-cccc"
    assert stamps == [1]
    (tmp_path / "T-200102-bbbb.md").write_text("x", encoding="utf-8")
    n = {"c": 0}
    monkeypatch.setattr(
        tasks_mod.secrets, "token_hex", lambda n_: n.__setitem__("c", n["c"] + 1) or "bbbb"
    )
    with pytest.raises(RuntimeError, match=ID_ALLOCATE_ERROR):
        allocate_task_id(tmp_path, day="200102")
    assert n["c"] == 64


def test_parse_task_encoding_defaults_fields(tmp_path: Path, monkeypatch):
    enc: list = []
    real_read = Path.read_text

    def fake_read(self, encoding=None, errors=None):
        enc.append(encoding)
        return real_read(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", fake_read)
    blank = tmp_path / "T-261116-zzz.md"
    blank.write_text("   \n", encoding="utf-8")
    meta = parse_task(blank)
    assert enc == ["utf-8"]
    assert meta is not None
    assert meta.task_id == meta.title == "T-261116-zzz"
    assert meta.status == "idea"
    assert meta.tags == meta.parent == meta.claim == ""
    assert meta.kind == meta.priority == meta.owner == ""
    assert meta.depends_on == []
    assert meta.blocked_by == meta.exit == meta.superseded_by == ""
    empty = tmp_path / "T-261116-eee.md"
    empty.write_text("", encoding="utf-8")
    assert parse_task(empty).task_id == "T-261116-eee"
    assert parse_task(tmp_path / "INDEX.md") is None
    full = tmp_path / "T-261116-abc.md"
    full.write_text(
        "# T-261116-abc — Title\n\nстатус: self-review\nтеги: a\nродитель: T-1\n"
        "claim: me\nkind: feature\npriority: p0\nowner: o\ndepends_on: [T-2]\n"
        "blocked_by: x\nexit: e\nsuperseded_by: T-3\n",
        encoding="utf-8",
    )
    m = parse_task(full)
    assert (m.status, m.kind, m.priority, m.owner, m.tags, m.parent, m.claim) == (
        "self-review",
        "feature",
        "p0",
        "o",
        "a",
        "T-1",
        "me",
    )
    assert m.depends_on == ["T-2"]
    assert (m.blocked_by, m.exit, m.superseded_by) == ("x", "e", "T-3")


def test_render_exact_set_field_append_index(tmp_path: Path, monkeypatch):
    text = render_task_file("T-1", "Hi")
    assert text == (
        f"# T-1 — Hi\n\nстатус: open\nтеги: {PLACEHOLDER_TAGS}\n"
        f"родитель: {PLACEHOLDER_PARENT}\nclaim: {PLACEHOLDER_CLAIM}\n\n"
        f"## Цель\n\n{DEFAULT_GOAL}\n\n## Progress\n\n{PLACEHOLDER_SECTION}\n\n"
        f"## Decision Log\n\n{PLACEHOLDER_SECTION}\n"
    )
    assert "Ценность:" not in text
    rich = render_task_file(
        "T-2",
        "R",
        kind="feature",
        priority="p1",
        owner="o",
        depends_on=["T-1"],
        blocked_by="b",
        exit="e",
        superseded_by="T-3",
        parent="P",
        claim="C",
        tags="t",
    )
    assert "kind: feature\n" in rich and "depends_on: [T-1]\n" in rich
    assert "родитель: P\n" in rich and "claim: C\n" in rich
    out = set_field("статус: open\nстатус: dup\n", "статус", "done")
    assert out.splitlines()[:2] == ["статус: done", "статус: dup"]
    assert set_field("", "статус", "open") == "статус: open\n"
    assert set_field("# T-1 — x\nbody\n", "статус", "open").splitlines() == [
        "# T-1 — x",
        "статус: open",
        "body",
    ]
    assert set_field("# T-1 — x\n\nbody\n", "статус", "open").splitlines() == [
        "# T-1 — x",
        "",
        "статус: open",
        "body",
    ]
    assert set_field("# T-1 — x\n\n\nbody\n", "статус", "open").splitlines() == [
        "# T-1 — x",
        "",
        "",
        "статус: open",
        "body",
    ]
    assert set_field("a\n", "x", "1") == "a\nx: 1\n"
    assert set_field("a", "x", "1") == "a\nx: 1"
    from datetime import timezone

    seen = _spy_now(monkeypatch, FIXED)
    got = append_progress("  # T\n", "hi")
    assert got.startswith("  # T\n") and "## Progress" in got
    assert "2020-01-02 03:04 UTC: hi" in got and seen == [timezone.utc]
    with_prog = "# T\n## Progress\n\n- old\n## Decision Log\n\nx\n## Extra\n\nkeep\n"
    assert append_progress(with_prog, "new") == (
        "# T\n## Progress\n\n- old\n- 2020-01-02 03:04 UTC: new\n"
        "\n## Decision Log\n\nx\n## Extra\n\nkeep\n"
    )
    # first Progress wins (not rsplit / unrestricted split)
    nested = "# T\n## Progress\n\n- first\n## Mid\n\nx\n## Progress\n\n- second\n"
    assert append_progress(nested, "new").startswith(
        "# T\n## Progress\n\n- first\n- 2020-01-02 03:04 UTC: new\n"
    )
    assert append_progress("# T\n## Progress\n\n- old\n", "solo") == (
        "# T\n## Progress\n\n- old\n- 2020-01-02 03:04 UTC: solo\n"
    )
    (tmp_path / "T-261116-aaa.md").write_text(
        "# T-261116-aaa — Done\n\nстатус: done\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\n",
        encoding="utf-8",
    )
    (tmp_path / "T-261116-bbb.md").write_text(
        "# T-261116-bbb — Open\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\n",
        encoding="utf-8",
    )
    (tmp_path / "T-261116-ccc.md").write_text(
        "# T-261116-ccc — Child\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: T-261116-bbb\nclaim: alice\n",
        encoding="utf-8",
    )
    empty = PLACEHOLDER_EMPTY
    assert rebuild_task_index(tmp_path) == (
        f"{INDEX_TITLE}\n\n{INDEX_INTRO}\n\n"
        "Статусы в индексе: `open` · `in-progress` · `blocked`.\n\n"
        f"{INDEX_SEARCH}\n\n## open\n\n"
        "- [T-261116-bbb](T-261116-bbb.md) — Open\n"
        "- [T-261116-ccc](T-261116-ccc.md) — Child "
        "(родитель: T-261116-bbb) · claim: alice\n\n"
        f"## in-progress\n\n{empty}\n\n"
        f"## blocked\n\n{empty}\n\n"
        f"{INDEX_FOOTER}\n"
    )


def test_render_acceptance_and_optional_fields():
    text = render_task_file(
        "T-1",
        "Hi",
        status="done",
        acceptance_note="shipped",
        blocked_reason="r",
        blocked_deadline="2026-11-21",
        review_note="ok",
        pr="#26",
        orbit_id="T-0023",
        value="V",
    )
    assert text == (
        f"# T-1 — Hi\n\nстатус: done\nтеги: {PLACEHOLDER_TAGS}\n"
        f"родитель: {PLACEHOLDER_PARENT}\nclaim: {PLACEHOLDER_CLAIM}\n"
        "blocked_reason: r\nblocked_deadline: 2026-11-21\n"
        "acceptance_note: shipped\nreview_note: ok\npr: #26\norbit_id: T-0023\n\n"
        f"Ценность: V\n\n## Цель\n\n{DEFAULT_GOAL}\n\n## Progress\n\n"
        f"{PLACEHOLDER_SECTION}\n\n## Decision Log\n\n{PLACEHOLDER_SECTION}\n"
    )


def test_parse_task_orbit_id_exact(tmp_path: Path):
    p = tmp_path / "T-261116-oid1.md"
    p.write_text(
        "# T-261116-oid1 — O\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\norbit_id: T-0023\n\n"
        "Ценность: v\n\n## Цель\n\nx\n\n## Progress\n\n_\n\n"
        "## Decision Log\n\n_\n",
        encoding="utf-8",
    )
    meta = parse_task(p)
    assert meta is not None
    assert meta.orbit_id == "T-0023"
    assert meta.task_id == "T-261116-oid1"


def test_rebuild_index_orbit_id_exact(tmp_path: Path):
    (tmp_path / "T-261116-oid2.md").write_text(
        "# T-261116-oid2 — O\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\norbit_id: T-0023\n",
        encoding="utf-8",
    )
    empty = PLACEHOLDER_EMPTY
    assert rebuild_task_index(tmp_path) == (
        f"{INDEX_TITLE}\n\n{INDEX_INTRO}\n\n"
        "Статусы в индексе: `open` · `in-progress` · `blocked`.\n\n"
        f"{INDEX_SEARCH}\n\n## open\n\n"
        "- [T-261116-oid2](T-261116-oid2.md) — O · orbit: T-0023\n\n"
        f"## in-progress\n\n{empty}\n\n"
        f"## blocked\n\n{empty}\n\n"
        f"{INDEX_FOOTER}\n"
    )


def test_rebuild_skips_placeholder_orbit(tmp_path: Path):
    (tmp_path / "T-261116-oid3.md").write_text(
        "# T-261116-oid3 — O\n\nстатус: open\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\norbit_id: _ph\n",
        encoding="utf-8",
    )
    empty = PLACEHOLDER_EMPTY
    assert rebuild_task_index(tmp_path) == (
        f"{INDEX_TITLE}\n\n{INDEX_INTRO}\n\n"
        "Статусы в индексе: `open` · `in-progress` · `blocked`.\n\n"
        f"{INDEX_SEARCH}\n\n## open\n\n"
        "- [T-261116-oid3](T-261116-oid3.md) — O\n\n"
        f"## in-progress\n\n{empty}\n\n"
        f"## blocked\n\n{empty}\n\n"
        f"{INDEX_FOOTER}\n"
    )


def test_map_orbit_status_exact():
    assert map_orbit_status("") == "idea"
    assert map_orbit_status("   ") == "idea"
    assert map_orbit_status("review") == "for-review"
    assert map_orbit_status("dropped") == "canceled"
    assert map_orbit_status("Open") == "open"
    assert map_orbit_status("wip") is None
    assert map_orbit_status("unknown-orbit") is None


def test_parse_task_empty_body_match_empty_string(tmp_path: Path, monkeypatch):
    """Empty/whitespace body: re.match must see "" (not a placeholder)."""
    from agentized import tasks as tasks_mod

    captured: list[str] = []
    real_match = tasks_mod.re.match

    def capture_match(pattern, string, *a, **k):
        captured.append(string)
        return real_match(pattern, string, *a, **k)

    monkeypatch.setattr(tasks_mod.re, "match", capture_match)
    path = tmp_path / "T-261116-ws03.md"
    path.write_text("", encoding="utf-8")
    meta = parse_task(path)
    assert meta is not None
    assert meta.task_id == "T-261116-ws03"
    assert captured == [""]
    captured.clear()
    path.write_text("\n\n  \t", encoding="utf-8")
    assert parse_task(path) is not None
    assert captured == [""]
