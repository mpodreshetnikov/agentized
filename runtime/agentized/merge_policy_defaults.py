"""Defaults + constant lexemes for merge/authorship."""

from __future__ import annotations

from typing import Any

DOC = "docs/process-control.md"

AGENT_MERGE_ALLOWED = "allowed"
AGENT_MERGE_FORBIDDEN = "forbidden"

MODE_DISABLED = "disabled"
MODE_REFUSE = "refuse"
MODE_OK = "ok"
MODE_HUMAN = "human"
MODE_ALLOWED = "allowed"

KEY_OK = "ok"
KEY_MODE = "mode"
KEY_MESSAGE = "message"
KEY_MERGES = "merges"
KEY_CLEANED = "cleaned_message"
KEY_STRIPPED = "stripped"

CFG_MERGE_POLICY = "merge_policy"
CFG_AGENT_MERGE = "agent_merge"
CFG_HUMAN_PARTICIPANTS = "human_participants"
CFG_HUMAN_AUTHORSHIP = "human_authorship"
CFG_ENABLED = "enabled"
CFG_STRIP_AGENT_TRAILERS = "strip_agent_trailers"
CFG_AGENT_TRAILER_PREFIXES = "agent_trailer_prefixes"

DEFAULT_AGENT_TRAILER_PREFIXES: tuple[str, ...] = (
    "Co-authored-by: Cursor",
    "Co-authored-by: cursor",
    "Co-authored-by: Claude",
    "Co-authored-by: claude",
    "Co-authored-by: Codex",
    "Co-authored-by: codex",
    "Co-authored-by: Copilot",
    "Co-authored-by: GitHub Copilot",
    "Generated-by:",
    "Generated-By:",
    "Signed-off-by: Cursor",
    "Signed-off-by: Claude",
)


def default_merge_policy() -> dict[str, Any]:
    return {
        "agent_merge": AGENT_MERGE_ALLOWED,
        "human_participants": [],
        "human_authorship": {
            "enabled": True,
            "strip_agent_trailers": True,
            "agent_trailer_prefixes": list(DEFAULT_AGENT_TRAILER_PREFIXES),
        },
    }


def empty_allowlist_message() -> str:
    return (
        "REFUSED. merge-policy: human_authorship.enabled but "
        f"human_participants is empty. See {DOC}."
    )


def author_not_allowlisted_message(author: str) -> str:
    return (
        f"REFUSED. merge-policy: author {author!r} is not on "
        f"human_participants allowlist. See {DOC}."
    )


def authorship_ok_message(author: str, stripped_n: int) -> str:
    note = f"merge-policy: authorship OK for {author!r}"
    if stripped_n:
        note += f" (stripped {stripped_n} agent trailer line(s))"
    return note


def agent_merge_refuse_message(short: str) -> str:
    return (
        "REFUSED. merge-policy: agent_merge=forbidden — agent sessions must not "
        f"push merge commits ({short}). See {DOC}."
    )


def invalid_agent_merge_message(value: object) -> str:
    return (
        "REFUSED. merge-policy: agent_merge must be "
        f"'allowed' or 'forbidden', got {value!r}. See {DOC}."
    )
