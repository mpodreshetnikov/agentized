"""JSON file I/O for quality.json.

Thin helpers for load/save. Prefer covering merge/normalize behavior in
`quality.py` tests; editing this module still enters the mutation gate when changed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_JSON_ENCODING = "utf-8"
_JSON_INDENT = 2


def read_json_object(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding=_JSON_ENCODING)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_json_object(path: Path, data: dict[str, Any]) -> None:
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True)
    payload = json.dumps(data, ensure_ascii=False, indent=_JSON_INDENT) + "\n"
    path.write_text(payload, encoding=_JSON_ENCODING)
