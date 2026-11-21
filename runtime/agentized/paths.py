from __future__ import annotations

import json
from pathlib import Path

CONNECT_MARKER_BEGIN = "<!-- AGENTIZED:BEGIN -->"
CONNECT_MARKER_END = "<!-- AGENTIZED:END -->"
STATE_DIRNAME = ".agentized"
STATE_FILENAME = "connect.json"
DEFAULT_CONTEXT = "context"


def find_repo_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists() or (candidate / "AGENTS.md").exists():
            return candidate
    return cur


def context_dir(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    return (root / context_rel).resolve()


def state_path(root: Path) -> Path:
    return root / STATE_DIRNAME / STATE_FILENAME


def load_state(root: Path) -> dict:
    path = state_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(root: Path, data: dict) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
