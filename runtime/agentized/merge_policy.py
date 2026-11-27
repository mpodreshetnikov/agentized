"""Policy decisions for merge/authorship (AGE-27)."""

from __future__ import annotations

from typing import Any

from .merge_policy_defaults import (
    AGENT_MERGE_ALLOWED,
    AGENT_MERGE_FORBIDDEN,
    CFG_AGENT_MERGE,
    CFG_AGENT_TRAILER_PREFIXES,
    CFG_ENABLED,
    CFG_HUMAN_AUTHORSHIP,
    CFG_HUMAN_PARTICIPANTS,
    CFG_MERGE_POLICY,
    CFG_STRIP_AGENT_TRAILERS,
    KEY_CLEANED,
    KEY_MERGES,
    KEY_MESSAGE,
    KEY_MODE,
    KEY_OK,
    KEY_STRIPPED,
    MODE_ALLOWED,
    MODE_DISABLED,
    MODE_HUMAN,
    MODE_OK,
    MODE_REFUSE,
    agent_merge_refuse_message,
    author_not_allowlisted_message,
    authorship_ok_message,
    default_merge_policy,
    empty_allowlist_message,
    invalid_agent_merge_message,
)
from .merge_policy_text import (
    count_stripped_lines,
    participant_matches,
    strip_agent_trailers,
    trailer_prefixes,
)


def normalize_agent_merge(value: object) -> str:
    """Only allowed|forbidden; anything else raises (fail-closed)."""
    text = str(value).strip().lower()
    if text == AGENT_MERGE_FORBIDDEN:
        return AGENT_MERGE_FORBIDDEN
    if text == AGENT_MERGE_ALLOWED:
        return AGENT_MERGE_ALLOWED
    raise ValueError(invalid_agent_merge_message(value))


def merge_policy_from_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = default_merge_policy()
    raw = (cfg or {}).get(CFG_MERGE_POLICY)
    if not isinstance(raw, dict):
        return base
    out = dict(base)
    if CFG_AGENT_MERGE in raw:
        out[CFG_AGENT_MERGE] = normalize_agent_merge(raw.get(CFG_AGENT_MERGE))
    participants = raw.get(CFG_HUMAN_PARTICIPANTS)
    if isinstance(participants, list):
        out[CFG_HUMAN_PARTICIPANTS] = [str(p).strip() for p in participants if str(p).strip()]
    authorship = raw.get(CFG_HUMAN_AUTHORSHIP)
    if isinstance(authorship, dict):
        ha = dict(base[CFG_HUMAN_AUTHORSHIP])
        if CFG_ENABLED in authorship:
            ha[CFG_ENABLED] = bool(authorship[CFG_ENABLED])
        if CFG_STRIP_AGENT_TRAILERS in authorship:
            ha[CFG_STRIP_AGENT_TRAILERS] = bool(authorship[CFG_STRIP_AGENT_TRAILERS])
        prefixes = authorship.get(CFG_AGENT_TRAILER_PREFIXES)
        if isinstance(prefixes, list):
            cleaned = [str(p).strip() for p in prefixes if str(p).strip()]
            if len(cleaned) > 0:
                ha[CFG_AGENT_TRAILER_PREFIXES] = cleaned
        out[CFG_HUMAN_AUTHORSHIP] = ha
    return out


def authorship_check(
    *,
    author: str,
    message: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    ha = policy.get(CFG_HUMAN_AUTHORSHIP) or {}
    enabled = bool(ha.get(CFG_ENABLED))
    strip = bool(ha.get(CFG_STRIP_AGENT_TRAILERS, True))
    prefixes = trailer_prefixes(ha)
    cleaned = strip_agent_trailers(message, prefixes) if enabled and strip else message
    stripped_n = count_stripped_lines(message, cleaned)
    if not enabled:
        return {
            KEY_OK: True,
            KEY_MODE: MODE_DISABLED,
            KEY_CLEANED: cleaned,
            KEY_STRIPPED: stripped_n,
            KEY_MESSAGE: "",
        }
    allowlist = list(policy.get(CFG_HUMAN_PARTICIPANTS) or [])
    if len(allowlist) == 0:
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_CLEANED: cleaned,
            KEY_STRIPPED: stripped_n,
            KEY_MESSAGE: empty_allowlist_message(),
        }
    # Author must be allowlisted. Co-authored-by never launders a stranger author.
    if not author or not participant_matches(author, allowlist):
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_CLEANED: cleaned,
            KEY_STRIPPED: stripped_n,
            KEY_MESSAGE: author_not_allowlisted_message(author),
        }
    return {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_CLEANED: cleaned,
        KEY_STRIPPED: stripped_n,
        KEY_MESSAGE: authorship_ok_message(author, stripped_n),
    }


def agent_merge_decision(
    *,
    agent_merge: str,
    is_agent: bool,
    merge_shas: list[str],
) -> dict[str, Any]:
    try:
        mode = normalize_agent_merge(agent_merge)
    except ValueError as exc:
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_MERGES: list(merge_shas),
            KEY_MESSAGE: str(exc),
        }
    if mode != AGENT_MERGE_FORBIDDEN:
        return {KEY_OK: True, KEY_MODE: MODE_ALLOWED, KEY_MESSAGE: "", KEY_MERGES: []}
    if not is_agent:
        return {KEY_OK: True, KEY_MODE: MODE_HUMAN, KEY_MESSAGE: "", KEY_MERGES: []}
    if len(merge_shas) == 0:
        return {KEY_OK: True, KEY_MODE: MODE_OK, KEY_MESSAGE: "", KEY_MERGES: []}
    short = ", ".join(sha[:12] for sha in merge_shas)
    return {
        KEY_OK: False,
        KEY_MODE: MODE_REFUSE,
        KEY_MERGES: list(merge_shas),
        KEY_MESSAGE: agent_merge_refuse_message(short),
    }
