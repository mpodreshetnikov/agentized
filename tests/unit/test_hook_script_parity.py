"""Eight harness copies of lease_warn / session_start must stay byte-identical."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HOOK_COPIES = (
    "context/hooks/scripts",
    "packages/shared/hooks/scripts",
    ".cursor/hooks",
    ".claude/hooks",
    ".codex/hooks",
    "packages/agentized-cursor/scripts",
    "packages/agentized-claude/scripts",
    "packages/agentized-codex/scripts",
)


def _paths(name: str) -> list[Path]:
    return [ROOT / rel / name for rel in HOOK_COPIES]


def test_lease_warn_eight_copies_byte_identical() -> None:
    paths = _paths("lease_warn.py")
    assert len(paths) == 8
    payloads = [p.read_bytes() for p in paths]
    assert len({p for p in payloads}) == 1
    text = payloads[0].decode("utf-8")
    assert "session_lease_warn" in text
    assert "lease_warn_for_paths" in text  # fallback when context_layout absent


def test_session_start_eight_copies_byte_identical() -> None:
    paths = _paths("session_start.py")
    assert len(paths) == 8
    payloads = [p.read_bytes() for p in paths]
    assert len({p for p in payloads}) == 1
    text = payloads[0].decode("utf-8")
    assert "session_nav_reminder" in text
    assert "apply_external_env_check" in text
    assert "nav_reminder" in text  # fallback when context_layout absent


def test_guard_and_bootstrap_eight_copies_byte_identical_without_disables() -> None:
    names = ("_bootstrap.py", "ensure_agent_hooks.py", "process_guard.py", "lease_warn.py")
    distinct = {name: len({p.read_bytes() for p in _paths(name)}) for name in names}
    assert distinct == dict.fromkeys(names, 1)
    banned = [
        f"{name}:{line}"
        for name in names + ("session_start.py",)
        for line in _paths(name)[0].read_text(encoding="utf-8").splitlines()
        if "# noqa" in line or "# type: ignore" in line
    ]
    assert banned == []
