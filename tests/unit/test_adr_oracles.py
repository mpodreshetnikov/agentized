"""Mutation oracles for adr.py (mutmut selects test_adr_*.py)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentized import adr as adr_mod
from agentized.adr import ADR_STATUS_ERROR, ADR_STATUSES, allocate_adr_id, create_adr, render_adr, slugify, utc_day

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

def test_render_adr_default_status_and_tasks(monkeypatch):
    seen = _spy_now(monkeypatch)
    text = render_adr("ADR-200102-abc", "Task Schema")
    assert text == (
        "---\nid: ADR-200102-abc\ntitle: Task Schema\nstatus: accepted\n"
        "date: 2020-01-02\ntasks: []\n---\n\n# Task Schema\n\n"
        "## Context\n\n_(why this decision is needed)_\n\n"
        "## Decision\n\n_(what we decided)_\n\n"
        "## Consequences\n\n_(what follows)_\n"
    )
    assert seen == [timezone.utc]

def test_render_adr_explicit_now_ignores_clock():
    # no spy — wall clock ≠ 2020; kills `and False` on now is not None
    rich = render_adr("ADR-1", "X", tasks=["T-a", "T-b"], now=FIXED)
    assert "date: 2020-01-02\n" in rich
    assert [ln for ln in rich.splitlines() if ln.startswith("tasks:")] == [
        "tasks: [T-a, T-b]"
    ]
    assert "tasks: []\n" in render_adr("ADR-1", "X", tasks=[], now=FIXED)

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
        adr_mod.secrets, "token_hex", lambda n: ncalls.__setitem__("n", ncalls["n"] + 1) or "abc0"
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
        tmp_path / "dec", "Default Status", status="proposed", tasks=["T-1"], now=FIXED
    )
    assert alloc_args == [{"dir": tmp_path / "dec", "now": FIXED, "day": None}]
    assert path.read_text(encoding="utf-8") == render_adr(
        "ADR-200102-def", "Default Status", status="proposed", tasks=["T-1"], now=FIXED
    )
    path_default = create_adr(tmp_path / "dec2", "Uses Default", now=FIXED)
    body = path_default.read_text(encoding="utf-8")
    assert "status: accepted\n" in body and "status: ACCEPTED\n" not in body
    assert any(c["parents"] is True and c["exist_ok"] is True for c in mk)
    assert writes == ["utf-8", "utf-8"]

def test_create_adr_rejects_unknown_status(tmp_path: Path):
    with pytest.raises(ValueError) as ei:
        create_adr(tmp_path, "X", status="nope")
    assert str(ei.value) == ADR_STATUS_ERROR.format(status="nope", allowed=ADR_STATUSES)
    assert "accepted" in ADR_STATUSES
    path = create_adr(tmp_path, "Заголовок", status="proposed")
    assert path.name.endswith("-zagolovok.md")
