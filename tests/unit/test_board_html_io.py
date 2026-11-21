"""Focused mutmut selection for board_html_io (stem map from #29)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentized.board_html_io import ENCODING, read_task_text, write_html


def test_board_html_io_encoding_roundtrip(tmp_path: Path):
    assert ENCODING == "utf-8"
    deep = tmp_path / "a" / "b" / "out.html"
    payload = "<!DOCTYPE html>\n<html>Ценность: café</html>\n"
    write_html(deep, payload)
    assert deep.read_bytes() == payload.encode("utf-8")
    assert read_task_text(deep) == payload
    write_html(deep, payload + "<!--2-->\n")
    assert read_task_text(deep).endswith("<!--2-->\n")
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe")
    with pytest.raises(UnicodeDecodeError):
        read_task_text(bad)
