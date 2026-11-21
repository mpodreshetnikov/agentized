"""AGE-23 command-path boundary checks for harness hook ownership."""

from __future__ import annotations

import re
from typing import Any

AGENTIZED_SCRIPTS = frozenset(
    {
        "session_start.py",
        "process_guard.py",
        "lease_warn.py",
        "ensure_agent_hooks.py",
    }
)
HARNESS_MARKERS = {
    "cursor": ".cursor/hooks/",
    "claude": ".claude/hooks/",
    "codex": ".codex/hooks/",
}
_LEFT = frozenset("/\"' $}")
_ALLOWED_PREFIX_SEGS = frozenset({"", ".", ".."})
_SLASH = "/"
_DOLLAR = "$"
_SCRIPTS_RE = "|".join(sorted(re.escape(s) for s in AGENTIZED_SCRIPTS))
_AGENTIZED_RE = {
    name: re.compile(re.escape(marker) + "(?:" + _SCRIPTS_RE + ")" + r"(?:$|[\"\' \t;&|)])")
    for name, marker in HARNESS_MARKERS.items()
}


def _path_prefix_allowed(normalized: str, marker_at: int) -> bool:
    if marker_at == 0:
        return True
    if normalized[marker_at - 1] != _SLASH:
        return True
    left = normalized[: marker_at - 1]
    if _SLASH not in left:
        if _DOLLAR in left:
            return True
        return left in _ALLOWED_PREFIX_SEGS
    seg = left[left.rfind(_SLASH) + 1 :]
    if _DOLLAR in seg:
        return True
    return seg in _ALLOWED_PREFIX_SEGS


def is_agentized_command(command: Any, harness: str) -> bool:
    """True when command invokes an exact Agentized hook script for this harness."""
    if not isinstance(command, str) or not command.strip():
        return False
    pat = _AGENTIZED_RE.get(harness)
    if not pat:
        return False
    normalized = command.replace("\\", "/")
    for match in pat.finditer(normalized):
        i = match.start()
        if i > 0 and normalized[i - 1] not in _LEFT:
            continue
        if _path_prefix_allowed(normalized, i):
            return True
    return False
