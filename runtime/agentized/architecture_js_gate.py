"""Architecture entry (AGE-34): Python gate + JS/TS dependency-cruiser/eslint."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .architecture_gate import run_architecture_gate as run_python_architecture
from .architecture_js import run_dependency_cruiser, run_eslint_boundaries
from .gate_dispatch import architecture_tool_for_language, detect_languages
from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality


def run_js_architecture(
    root: Path,
    section: dict,
    detected: dict[str, list[str]],
) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    tools_run: list[str] = []
    for lang in ("javascript", "typescript"):
        if lang not in detected:
            continue
        tool = architecture_tool_for_language(section, lang)
        if not tool:
            findings.append(
                {
                    "file": "(architecture)",
                    "kind": "no_architecture_runner",
                    "detail": f"missing architecture.tools.{lang}",
                }
            )
            continue
        if tool in tools_run:
            continue
        if tool == "dependency-cruiser":
            rc, out = run_dependency_cruiser(root, section)
            tools_run.append(tool)
            if rc != 0:
                findings.append(
                    {
                        "file": str(section.get("js_config") or ".dependency-cruiser.cjs"),
                        "kind": "dependency_cruiser",
                        "detail": out or f"exit {rc}",
                    }
                )
        elif tool == "eslint-boundaries":
            rc, out = run_eslint_boundaries(root, section)
            tools_run.append(tool)
            if rc != 0:
                findings.append(
                    {
                        "file": str(section.get("eslint_config") or "eslint"),
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
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg.get("architecture") or {}
    if not section.get("enabled", False):
        return run_python_architecture(root, context=context)

    py_rc = run_python_architecture(root, context=context)
    lang_section = cfg.get("languages") if isinstance(cfg.get("languages"), dict) else {}
    detected = detect_languages(root, exclude_globs=list(lang_section.get("exclude_globs") or []) or None)
    findings, tools_run = run_js_architecture(root, section, detected)
    mode = str(section.get("mode") or "hard").lower()
    stamp = (now or datetime.now)(timezone.utc).isoformat()
    out_dir = root / "reports" / "architecture"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "mode": mode,
        "toolsRun": tools_run,
        "detectedLanguages": sorted(detected),
        "generatedAt": stamp,
        "findings": findings,
        "passed": True if mode == "warn" else not findings,
    }
    (out_dir / "architecture-js-summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    if mode == "warn":
        return 0 if py_rc == 0 else py_rc
    if findings:
        return 1
    return 0 if py_rc == 0 else py_rc
