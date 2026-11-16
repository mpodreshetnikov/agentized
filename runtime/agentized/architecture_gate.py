"""Module-boundary architecture gate (hard by default).

Python: prefer import-linter when installed; otherwise enforce simple
forbidden-import edges from quality.json. JS/TS: dependency-cruiser or
eslint-boundaries (error severity), dispatched per detected language.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .gate_dispatch import architecture_tool_for_language, detect_languages
from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality


def _module_name(root: Path, path: Path, source_roots: list[str]) -> str | None:
    rel = path.relative_to(root).as_posix()
    for src in source_roots:
        src = src.rstrip("/")
        if rel == src or rel.startswith(src + "/"):
            body = rel[len(src) + 1 :] if rel != src else ""
            if not body.endswith(".py"):
                return None
            parts = body[: -len(".py")].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            # Map runtime/agentized → agentized.*
            prefix = "agentized" if src.endswith("agentized") else src.replace("/", ".")
            return ".".join([prefix, *parts]) if parts else prefix
    return None


def _imports_of(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _check_forbidden_edges(
    root: Path, source_roots: list[str], forbidden: list[dict]
) -> list[dict]:
    findings: list[dict] = []
    for src in source_roots:
        base = root / src
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            mod = _module_name(root, path, source_roots)
            if not mod:
                continue
            for imp in _imports_of(path):
                for edge in forbidden:
                    frm = str(edge.get("from") or "")
                    to = str(edge.get("to") or "")
                    if mod == frm or mod.startswith(frm + "."):
                        if imp == to or imp.startswith(to + "."):
                            findings.append(
                                {
                                    "file": path.relative_to(root).as_posix(),
                                    "kind": "forbidden_import",
                                    "detail": f"{mod} must not import {imp} ({frm} ↛ {to})",
                                }
                            )
    return findings


def _run_import_linter(root: Path, config_path: Path) -> tuple[int, str]:
    if not config_path.exists():
        return 0, "no config"
    import os
    import shutil

    # Prefer lint-imports console script; `python -m importlinter` is not supported.
    exe = shutil.which("lint-imports")
    if exe:
        cmd = [exe, "--config", str(config_path), "--no-logo"]
    else:
        cmd = [
            sys.executable,
            "-c",
            (
                "import sys; from importlinter.cli import lint_imports_command; "
                f"sys.argv=['lint-imports','--config',r'{config_path}','--no-logo']; "
                "raise SystemExit(lint_imports_command())"
            ),
        ]
    env = os.environ.copy()
    runtime = str(root / "runtime")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = runtime if not existing else f"{runtime}:{existing}"
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _run_dependency_cruiser(root: Path, section: dict) -> tuple[int, str]:
    config = root / str(section.get("js_config") or section.get("config") or ".dependency-cruiser.cjs")
    source = str(section.get("js_source") or "src")
    if not config.exists():
        return 1, f"missing dependency-cruiser config: {config.name}"
    npx = shutil.which("npx")
    if not npx:
        return 1, "npx not found — install Node to run dependency-cruiser"
    cmd = [npx, "--yes", "dependency-cruiser", "--config", str(config), source]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return proc.returncode or 0, ((proc.stdout or "") + (proc.stderr or "")).strip()[:2000]


def _run_eslint_boundaries(root: Path, section: dict) -> tuple[int, str]:
    config = section.get("eslint_config")
    cmd = list(section.get("eslint_boundaries_command") or [])
    if not cmd:
        npx = shutil.which("npx")
        if not npx:
            return 1, "npx not found — install Node to run eslint-boundaries"
        cmd = [npx, "--yes", "eslint", "."]
        if config:
            cmd.extend(["--config", str(config)])
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return proc.returncode or 0, ((proc.stdout or "") + (proc.stderr or "")).strip()[:2000]


def _run_python_architecture(root: Path, section: dict) -> tuple[list[dict], str, str]:
    tool = str(
        architecture_tool_for_language(section, "python")
        or section.get("tool")
        or "builtin"
    )
    findings: list[dict] = []
    tool_note = ""
    if tool == "import-linter":
        config = root / str(section.get("config") or ".importlinter")
        try:
            rc, out = _run_import_linter(root, config)
            tool_note = out.strip()[:2000]
            if rc != 0:
                findings.append(
                    {
                        "file": str(config.relative_to(root))
                        if config.exists()
                        else ".importlinter",
                        "kind": "import_linter",
                        "detail": tool_note or f"import-linter exit {rc}",
                    }
                )
        except FileNotFoundError:
            tool_note = "import-linter not installed — falling back to builtin edges"
            tool = "builtin"

    if tool == "builtin" or (tool == "import-linter" and "not installed" in tool_note):
        source_roots = list(section.get("source_roots") or ["runtime/agentized"])
        forbidden = list(section.get("forbidden_edges") or [])
        findings.extend(_check_forbidden_edges(root, source_roots, forbidden))
        tool = "builtin" if "not installed" in tool_note else tool
    return findings, tool, tool_note


def run_architecture_gate(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg.get("architecture") or {}
    if not section.get("enabled", False):
        print("[architecture] disabled — skip")
        return 0

    mode = str(section.get("mode") or "hard").lower()
    lang_section = cfg.get("languages") if isinstance(cfg.get("languages"), dict) else {}
    exclude = list(lang_section.get("exclude_globs") or [])
    detected = detect_languages(root, exclude_globs=exclude or None)

    findings: list[dict] = []
    tools_run: list[str] = []
    tool_notes: list[str] = []

    # Python paths (or empty repo / python-only defaults): always allow python tool
    # when python detected OR no JS/TS (dogfood / legacy).
    need_python = "python" in detected or not any(
        lang in detected for lang in ("javascript", "typescript")
    )
    if need_python:
        py_findings, py_tool, py_note = _run_python_architecture(root, section)
        findings.extend(py_findings)
        tools_run.append(py_tool)
        if py_note:
            tool_notes.append(py_note)

    for lang in ("javascript", "typescript"):
        if lang not in detected:
            continue
        tool = architecture_tool_for_language(section, lang)
        if not tool:
            findings.append(
                {
                    "file": "(architecture)",
                    "kind": "no_architecture_runner",
                    "detail": (
                        f"No architecture tool for {lang}. Set architecture.tools.{lang} "
                        "to dependency-cruiser or eslint-boundaries."
                    ),
                }
            )
            continue
        if tool in tools_run:
            continue  # already ran for sibling JS/TS
        if tool == "dependency-cruiser":
            rc, out = _run_dependency_cruiser(root, section)
            tools_run.append(tool)
            if out:
                tool_notes.append(out)
            if rc != 0:
                findings.append(
                    {
                        "file": str(section.get("js_config") or ".dependency-cruiser.cjs"),
                        "kind": "dependency_cruiser",
                        "detail": out or f"dependency-cruiser exit {rc}",
                    }
                )
        elif tool == "eslint-boundaries":
            rc, out = _run_eslint_boundaries(root, section)
            tools_run.append(tool)
            if out:
                tool_notes.append(out)
            if rc != 0:
                findings.append(
                    {
                        "file": str(section.get("eslint_config") or "eslint"),
                        "kind": "eslint_boundaries",
                        "detail": out or f"eslint-boundaries exit {rc}",
                    }
                )
        else:
            findings.append(
                {
                    "file": "(architecture)",
                    "kind": "unknown_architecture_tool",
                    "detail": f"Unsupported architecture tool {tool!r} for {lang}",
                }
            )

    tool = "+".join(tools_run) if tools_run else str(section.get("tool") or "builtin")
    tool_note = "\n".join(tool_notes)[:2000]

    out_dir = root / "reports" / "architecture"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "mode": mode,
        "tool": tool,
        "toolsRun": tools_run,
        "detectedLanguages": sorted(detected),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
        "passed": True if mode == "warn" else not findings,
        "toolNote": tool_note,
    }
    (out_dir / "architecture-summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    if findings:
        print(f"[architecture] {len(findings)} finding(s) (mode={mode})")
        for item in findings[:30]:
            print(f"  {item['file']}: {item['kind']}: {item['detail'][:200]}")
    else:
        print(f"[architecture] PASS (0 findings, tool={tool})")

    if mode == "warn":
        print("[architecture] warn mode — not failing the gate")
        return 0
    return 0 if not findings else 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    return run_architecture_gate(find_repo_root(), context=context)


if __name__ == "__main__":
    raise SystemExit(main())
