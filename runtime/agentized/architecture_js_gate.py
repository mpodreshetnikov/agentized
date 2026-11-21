"""Architecture entry (AGE-34): Python + JS/TS runners."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .architecture_gate import run_architecture_gate as run_python_architecture
from .architecture_js import run_dependency_cruiser, run_eslint_boundaries
from .gate_dispatch import (
    architecture_tool_for_language,
    combine_gate_rc,
    detect_languages,
)
from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

_JS_LANGS = ("javascript", "typescript")
_DC = "dependency-cruiser"
_ESLINT = "eslint-boundaries"
_DEFAULT_DC_FILE = ".dependency-cruiser.cjs"


def _tool_plan(section: dict, detected: dict[str, list[str]]) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    ordered: list[str] = []
    for lang in _JS_LANGS:
        if lang not in detected:
            continue
        tool = architecture_tool_for_language(section, lang)
        if tool is None:
            findings.append(
                {
                    "file": "(architecture)",
                    "kind": "no_architecture_runner",
                    "detail": f"missing architecture.tools.{lang}",
                }
            )
            continue
        if tool not in ordered:
            ordered.append(tool)
    return findings, ordered


def run_js_architecture(
    root: Path,
    section: dict,
    detected: dict[str, list[str]],
) -> tuple[list[dict], list[str]]:
    findings, tools_run = _tool_plan(section, detected)
    for tool in tools_run:
        if tool == _DC:
            rc, out = run_dependency_cruiser(root, section)
            if rc != 0:
                findings.append(
                    {
                        "file": str(section["js_config"]) if "js_config" in section else _DEFAULT_DC_FILE,
                        "kind": "dependency_cruiser",
                        "detail": out or f"exit {rc}",
                    }
                )
        elif tool == _ESLINT:
            rc, out = run_eslint_boundaries(root, section)
            if rc != 0:
                findings.append(
                    {
                        "file": str(section["eslint_config"]) if "eslint_config" in section else "eslint",
                        "kind": "eslint_boundaries",
                        "detail": out or f"exit {rc}",
                    }
                )
        else:
            findings.append(
                {
                    "file": "(architecture)",
                    "kind": "unknown_architecture_tool",
                    "detail": str(tool),
                }
            )
    return findings, tools_run


def run_architecture_gate(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
    now=None,
) -> int:
    resolved = find_repo_root() if root is None else root
    cfg = load_quality(resolved, context)
    section = cfg.get("architecture") or {}
    if section.get("enabled") is not True:
        return run_python_architecture(resolved, context=context)

    py_rc = run_python_architecture(resolved, context=context)
    detected = detect_languages(resolved)
    findings, tools_run = run_js_architecture(resolved, section, detected)
    mode = str(section.get("mode", "hard"))
    stamp = (now or datetime.now)().isoformat()
    out_dir = resolved / "reports" / "architecture"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "mode": mode,
        "toolsRun": tools_run,
        "detectedLanguages": sorted(detected),
        "generatedAt": stamp,
        "findings": findings,
        "passed": mode == "warn" or not findings,
    }
    (out_dir / "architecture-js-summary.json").write_text(json.dumps(payload) + "\n")
    return combine_gate_rc(mode, bool(findings), py_rc)
