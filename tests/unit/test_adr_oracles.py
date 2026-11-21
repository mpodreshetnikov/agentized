"""Mutation oracles for adr.py (mutmut selects test_adr_*.py)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentized import adr as adr_mod
from agentized.adr import (
    ADR_STATUS_ERROR,
    ADR_STATUSES,
    ADR_TASK_ID_ERROR,
    ADR_TITLE_CONTROL,
    ADR_TITLE_EMPTY,
    _forbidden_title_char,
    _yaml_quote,
    allocate_adr_id,
    create_adr,
    render_adr,
    slugify,
    utc_day,
    validate_task_ids,
    validate_title,
)

FIXED = datetime(2020, 1, 2, 3, 4, tzinfo=timezone.utc)


def _spy_now(monkeypatch, stamp=FIXED):
    seen: list = []

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            seen.append(tz)
            return stamp

    monkeypatch.setattr(adr_mod, "datetime", FakeDateTime)
    return seen


def test_utc_day_spy_timezone(monkeypatch):
    seen = _spy_now(monkeypatch)
    assert utc_day(None) == "200102"
    assert seen == [timezone.utc]
    assert utc_day(datetime(2019, 5, 6, tzinfo=timezone.utc)) == "190506"


def test_slugify_strip_length_default():
    assert slugify("Hello World!!!") == "hello-world"
    assert slugify("---Hello---") == "hello"
    assert slugify("-keep-") == "keep"
    assert slugify("a" * 80) == "a" * 48
    assert slugify("!!!") == "adr" and slugify("Схема") == "shema"
    assert slugify("") == "adr"
    assert slugify("x" * 48 + "yyy") == "x" * 48
    # 48-char cut lands on a hyphen — drop only the trailing one
    cut = slugify("a " * 40)
    assert cut == ("a-" * 40)[:48][:-1]
    assert len(cut) == 47 and cut.endswith("a") and not cut.endswith("-")
    assert cut == "-".join(["a"] * 40)[:48].removesuffix("-")


def test_title_and_task_validation():
    validate_title("ok")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_EMPTY)):
        validate_title("")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_EMPTY)):
        validate_title("   ")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_CONTROL)):
        validate_title("line\nbreak")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_CONTROL)):
        validate_title("tab\there")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_CONTROL)):
        validate_title("del\x7f")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_CONTROL)):
        validate_title("c1\x80")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_CONTROL)):
        validate_title("c1\x9f")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_CONTROL)):
        validate_title("sep\u2028")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_CONTROL)):
        validate_title("para\u2029")
    assert not _forbidden_title_char(" ") and not _forbidden_title_char("~")
    assert not _forbidden_title_char("\xa0")  # 0xA0 — just above C1
    assert _forbidden_title_char("\x1f") and _forbidden_title_char("\x7f")
    assert _forbidden_title_char("\x80") and _forbidden_title_char("\x9f")
    assert _forbidden_title_char("\u2028") and _forbidden_title_char("\u2029")
    assert not _forbidden_title_char("\u2027") and not _forbidden_title_char("\u202a")
    validate_task_ids(["T-261121-abcd"])
    validate_task_ids([])
    with pytest.raises(ValueError) as ei:
        validate_task_ids(["T-bad"])
    assert str(ei.value) == ADR_TASK_ID_ERROR.format(task_id="T-bad")
    assert _yaml_quote("a: b #c") == '"a: b #c"'
    assert _yaml_quote('say "hi"') == '"say \\"hi\\""'
    assert _yaml_quote("a\\b") == '"a\\\\b"'
    assert _yaml_quote('\\') == '"\\\\"'


def test_render_adr_default_status_and_tasks(monkeypatch):
    seen = _spy_now(monkeypatch)
    text = render_adr("ADR-200102-abc", "Task Schema")
    assert text == (
        '---\nid: ADR-200102-abc\ntitle: "Task Schema"\nstatus: proposed\n'
        "date: 2020-01-02\ntasks: []\n---\n\n# Task Schema\n\n"
        "## Context\n\n_(why this decision is needed)_\n\n"
        "## Decision\n\n_(what we decided)_\n\n"
        "## Consequences\n\n_(what follows)_\n"
    )
    assert seen == [timezone.utc]
    special = render_adr("ADR-1", "a: b #c", now=FIXED)
    assert 'title: "a: b #c"\n' in special
    assert [ln for ln in special.splitlines() if ln.startswith("# ")] == ["# a: b #c"]


def test_render_adr_explicit_now_ignores_clock():
    # no spy — wall clock ≠ 2020; kills `and False` on now is not None
    rich = render_adr("ADR-1", "X", tasks=["T-261116-aaaa", "T-261116-bbbb"], now=FIXED)
    assert "date: 2020-01-02\n" in rich
    assert [ln for ln in rich.splitlines() if ln.startswith("tasks:")] == [
        "tasks: [T-261116-aaaa, T-261116-bbbb]"
    ]
    assert "tasks: []\n" in render_adr("ADR-1", "X", tasks=[], now=FIXED)
    assert "status: proposed\n" in render_adr("ADR-1", "X", now=FIXED)


def test_allocate_token_width_exhaustion_and_create(tmp_path: Path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        adr_mod.secrets, "token_hex", lambda n: calls.append(n) or "abc0"
    )
    assert allocate_adr_id(tmp_path, now=FIXED) == "ADR-200102-abc"
    assert calls == [2]
    (tmp_path / "ADR-200102-abc.md").write_text("x", encoding="utf-8")
    ncalls = {"n": 0}
    monkeypatch.setattr(
        adr_mod.secrets,
        "token_hex",
        lambda n: ncalls.__setitem__("n", ncalls["n"] + 1) or "abc0",
    )
    with pytest.raises(RuntimeError, match="не удалось выделить уникальный ADR id"):
        allocate_adr_id(tmp_path, day="200102")
    assert ncalls["n"] == 64
    monkeypatch.setattr(adr_mod.secrets, "token_hex", lambda n: "zzz0")
    assert allocate_adr_id(tmp_path, day="991231", now=FIXED) == "ADR-991231-zzz"

    writes: list = []
    real_write = Path.write_text

    def fake_write(self, data, encoding=None, errors=None, newline=None):
        writes.append(encoding)
        return real_write(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", fake_write)
    mk: list = []
    real_mkdir = Path.mkdir

    def fake_mkdir(self, parents=False, exist_ok=False):
        mk.append({"parents": parents, "exist_ok": exist_ok})
        return real_mkdir(self, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    alloc_args: list = []

    def fake_alloc(decisions_dir, day=None, *, now=None):
        alloc_args.append({"dir": decisions_dir, "now": now, "day": day})
        return "ADR-200102-def"

    monkeypatch.setattr(adr_mod, "allocate_adr_id", fake_alloc)
    path = create_adr(
        tmp_path / "dec",
        "Default Status",
        status="accepted",
        tasks=["T-261116-aaaa"],
        now=FIXED,
    )
    assert alloc_args == [{"dir": tmp_path / "dec", "now": FIXED, "day": None}]
    assert path.read_text(encoding="utf-8") == render_adr(
        "ADR-200102-def",
        "Default Status",
        status="accepted",
        tasks=["T-261116-aaaa"],
        now=FIXED,
    )
    path_default = create_adr(tmp_path / "dec2", "Uses Default", now=FIXED)
    body = path_default.read_text(encoding="utf-8")
    assert "status: proposed\n" in body and "status: PROPOSED\n" not in body
    assert 'title: "Uses Default"\n' in body
    assert any(c["parents"] is True and c["exist_ok"] is True for c in mk)
    assert writes == ["utf-8", "utf-8"]
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_EMPTY)):
        create_adr(tmp_path / "dec3", "  ")
    with pytest.raises(ValueError, match=re.escape(ADR_TITLE_CONTROL)):
        create_adr(tmp_path / "dec3", "bad\ntitle")
    with pytest.raises(ValueError) as bad_task:
        create_adr(tmp_path / "dec3", "Ok", tasks=["not-an-id"])
    assert str(bad_task.value) == ADR_TASK_ID_ERROR.format(task_id="not-an-id")
    special = create_adr(tmp_path / "dec4", "a: b #c", now=FIXED)
    assert 'title: "a: b #c"\n' in special.read_text(encoding="utf-8")


def test_create_adr_rejects_unknown_status(tmp_path: Path):
    with pytest.raises(ValueError) as ei:
        create_adr(tmp_path, "X", status="nope")
    assert str(ei.value) == ADR_STATUS_ERROR.format(status="nope", allowed=ADR_STATUSES)
    assert "proposed" in ADR_STATUSES and "accepted" in ADR_STATUSES
    path = create_adr(tmp_path, "Заголовок", status="proposed")
    assert path.name.endswith("-zagolovok.md")
