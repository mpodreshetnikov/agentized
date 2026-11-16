"""AGE-36: hooks_install_io JSON refuse paths (mutmut selection for hooks_install_io)."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentized.hooks_install import HooksJsonError, read_json_object
from agentized.hooks_install_io import JSON_TEXT_ENCODING


def test_json_text_encoding_is_lowercase_utf8():
    assert JSON_TEXT_ENCODING == "utf-8"


def test_read_json_object_refuse_cases(tmp_path: Path):
    missing = tmp_path / "nope.json"
    assert read_json_object(missing) == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    with pytest.raises(HooksJsonError) as exc:
        read_json_object(broken)
    assert exc.value.reason[:13] == "broken JSON ("
    assert exc.value.path == broken

    arr = tmp_path / "arr.json"
    arr.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(HooksJsonError) as exc2:
        read_json_object(arr)
    assert exc2.value.reason == "top-level must be object, got list"
    assert exc2.value.path == arr

    num = tmp_path / "num.json"
    num.write_text("1\n", encoding="utf-8")
    with pytest.raises(HooksJsonError) as exc_num:
        read_json_object(num)
    assert exc_num.value.reason == "top-level must be object, got int"
    assert exc_num.value.path == num

    ok = tmp_path / "ok.json"
    ok.write_text('{"a": 1}\n', encoding="utf-8")
    assert read_json_object(ok) == {"a": 1}

    bad_utf = tmp_path / "bin.json"
    bad_utf.write_bytes(b"\xff\xfe")
    with pytest.raises(HooksJsonError) as exc3:
        read_json_object(bad_utf)
    assert exc3.value.reason.startswith(f"not {JSON_TEXT_ENCODING} (")
    assert exc3.value.reason[:9] == "not utf-8"
    assert exc3.value.path == bad_utf


def test_read_json_object_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "blocked.json"
    path.write_text("{}\n", encoding="utf-8")

    def boom(_self: Path) -> bytes:
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(HooksJsonError) as exc:
        read_json_object(path)
    assert exc.value.path == path
    assert exc.value.reason.startswith("unreadable (")
    assert "denied" in exc.value.reason
    assert str(exc.value) == f"invalid harness JSON at {path}: {exc.value.reason}"


def test_hooks_json_error_keeps_path(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_bytes(b"\xff")
    with pytest.raises(HooksJsonError) as exc:
        read_json_object(path)
    assert exc.value.path == path
    assert str(exc.value) == f"invalid harness JSON at {path}: {exc.value.reason}"
