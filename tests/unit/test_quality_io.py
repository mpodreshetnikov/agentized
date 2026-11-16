"""Unit tests for agentized.quality_io — selected by mutmut for quality_io.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentized import quality_io
from agentized.quality_io import read_json_object, write_json_object


def test_read_json_object_round_trip_dict(tmp_path: Path):
    path = tmp_path / "q.json"
    path.write_text('{"version": 1, "name": "тест"}\n', encoding="utf-8")
    assert read_json_object(path) == {"version": 1, "name": "тест"}


def test_read_json_object_rejects_non_object(tmp_path: Path):
    path = tmp_path / "arr.json"
    path.write_text("[1, 2]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected JSON object"):
        read_json_object(path)
    path.write_text('"string"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="expected JSON object"):
        read_json_object(path)


def test_read_json_object_passes_utf8_encoding(tmp_path: Path, monkeypatch):
    path = tmp_path / "enc.json"
    path.write_text('{"ok": true}\n', encoding="utf-8")
    seen: dict[str, object] = {}

    real = Path.read_text

    def wrapped(self, *args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", wrapped)
    assert read_json_object(path) == {"ok": True}
    assert seen["kwargs"].get("encoding") == "utf-8"


def test_write_json_object_creates_parents_and_formats(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "out.json"
    data = {"а": "б", "n": 2}
    write_json_object(path, data)
    raw = path.read_text(encoding="utf-8")
    # ensure_ascii=False keeps Cyrillic; indent=2; trailing newline.
    assert '"а": "б"' in raw
    assert "\\u" not in raw
    assert raw.endswith("\n")
    assert raw == json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    assert read_json_object(path) == data


def test_write_json_object_existing_parent(tmp_path: Path):
    path = tmp_path / "already.json"
    write_json_object(path, {"ok": True})
    assert path.read_text(encoding="utf-8") == '{\n  "ok": true\n}\n'


def test_write_json_object_dumps_and_write_kwargs(tmp_path: Path, monkeypatch):
    path = tmp_path / "kw.json"
    dump_kw: dict[str, object] = {}
    write_kw: dict[str, object] = {}

    real_dumps = json.dumps

    def dumps_wrapped(obj, **kwargs):
        dump_kw.update(kwargs)
        return real_dumps(obj, **kwargs)

    real_write = Path.write_text

    def write_wrapped(self, data, **kwargs):
        write_kw.update(kwargs)
        return real_write(self, data, **kwargs)

    monkeypatch.setattr(quality_io.json, "dumps", dumps_wrapped)
    monkeypatch.setattr(Path, "write_text", write_wrapped)
    write_json_object(path, {"а": 1})
    assert dump_kw.get("ensure_ascii") is False
    assert dump_kw.get("indent") == 2
    assert write_kw.get("encoding") == "utf-8"
