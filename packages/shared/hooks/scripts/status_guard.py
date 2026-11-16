#!/usr/bin/env python3
"""AGE-38 status-gate hook; decide logic in agentized.status_guard (fail-closed)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
try:
    from _bootstrap import ensure_runtime_on_path
except ImportError:
    sys.path.insert(0, str(_HERE.parent))
    try:
        from _bootstrap import ensure_runtime_on_path
    except ImportError:

        def ensure_runtime_on_path(here=None):  # type: ignore[misc]
            return Path.cwd()


def main() -> int:
    workspace = ensure_runtime_on_path(_HERE)
    raw = sys.stdin.read()

    try:
        from agentized.hook_common import context_rel, extract_paths, resolve_root
        from agentized.status_guard import decide_from_stdin, deny_response
    except Exception as exc:  # noqa: BLE001 — fail closed
        print(
            json.dumps(
                deny_response(
                    "PreToolUse",
                    f"[status-guard] REFUSED: import failure: {exc}",
                ),
                ensure_ascii=False,
            )
        )
        return 0

    # Prefer payload cwd when present; fall back after a successful parse inside decide.
    root = workspace
    try:
        import json as _json

        peek = _json.loads(raw) if raw.strip() else {}
        if isinstance(peek, dict):
            root = resolve_root(peek) if peek else workspace
    except Exception:  # noqa: BLE001
        root = workspace

    runtime = root / "runtime"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))

    ctx = context_rel(root)
    out = decide_from_stdin(
        raw,
        root=root,
        context_rel=ctx,
        extract_paths=extract_paths,
    )
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
