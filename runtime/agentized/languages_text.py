"""Human-facing language-coverage messages/results (outside mutation include_globs).

Literal strings and result-dict keys create uninformative mutmut survivors;
logic stays in languages.py.
"""
from __future__ import annotations

from typing import Any


def result(
    *,
    ok: bool,
    message: str,
    detected: dict[str, Any] | None = None,
    unsupported: list[str] | None = None,
    missing_gates: dict[str, list[str]] | None = None,
    skipped: bool = False,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "detected": {} if detected is None else detected,
        "unsupported": [] if unsupported is None else unsupported,
        "missing_gates": {} if missing_gates is None else missing_gates,
        "message": message,
        "skipped": skipped,
    }


def msg_detect_false() -> str:
    return (
        "agentized: REFUSED — languages.detect=false is not allowed "
        "(fail-closed language coverage; AGE-24)."
    )


def msg_supported_missing() -> str:
    return (
        "agentized: REFUSED — languages.supported is missing or empty "
        "(fail-closed; no silent defaults)."
    )


def msg_exclude_missing() -> str:
    return (
        "agentized: REFUSED — languages.exclude_globs is missing or empty "
        "(fail-closed; no silent defaults)."
    )


def msg_illegal_supported(illegal: list[str], allowed: list[str], gates: list[str]) -> str:
    return (
        "agentized: REFUSED — languages.supported contains language(s) "
        f"without a gate suite: {', '.join(illegal)}. "
        f"Allowed: {', '.join(allowed)}. "
        f"Required gates: {', '.join(gates)}."
    )


def msg_coverage_incomplete(
    unsupported: list[str],
    missing_gates: dict[str, list[str]],
    detected: dict[str, list[str]],
    required_gates: tuple[str, ...] | list[str],
) -> str:
    parts: list[str] = []
    for lang in unsupported:
        tip = (detected.get(lang) or ["?"])[0]
        parts.append(f"{lang} unsupported (e.g. {tip})")
    for lang, gates in missing_gates.items():
        tip = (detected.get(lang) or ["?"])[0]
        parts.append(
            f"{lang} missing gates [{', '.join(gates)}] (e.g. {tip}; "
            f"need {', '.join(required_gates)})"
        )
    return (
        "agentized: REFUSED — language coverage incomplete: "
        + "; ".join(parts)
        + ". Configure modules/test_command/coverage, mutation.tools, "
        "architecture.tools+config, test_smells include_globs per language, "
        "and JS/TS AGE-34 runners when those languages are present."
    )


def msg_ok(detected: dict[str, Any]) -> str:
    return "language coverage OK: " + (
        ", ".join(sorted(detected)) if detected else "(none)"
    )
