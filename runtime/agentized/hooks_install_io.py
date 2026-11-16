"""Harness JSON I/O (AGE-36) — outside mutation include_globs.

Encoding / OSError paths have equivalent mutants under mutmut; keep them here.
"""
from __future__ import annotations

import json
from pathlib import Path


class HooksJsonError(ValueError):
    """Broken or non-object harness JSON; file must stay byte-identical."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"invalid harness JSON at {path}: {reason}")


def read_json_object(path: Path) -> dict:
    """Load a JSON object. Missing file → {}. Broken / non-object → HooksJsonError."""
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes().decode("utf-8")
        data = json.loads(raw)
    except OSError as exc:
        raise HooksJsonError(path, f"unreadable ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise HooksJsonError(path, f"not utf-8 ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise HooksJsonError(path, f"broken JSON ({exc.msg})") from exc
    if type(data) is not dict:
        raise HooksJsonError(path, f"top-level must be object, got {type(data).__name__}")
    return data
