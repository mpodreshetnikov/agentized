"""Hard gitleaks secret scan (AGE-29).

Runs `gitleaks detect` against the repo. Default mode is hard/blocking on
pre-push and CI (via `quality check` gates). Missing binary fails closed when
mode=hard.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

DOC = "docs/QUALITY.md"
DEFAULT_CONFIG = ".gitleaks.toml"
REPORT_DIR = "reports/secrets"


def _mode(section: dict[str, Any]) -> str:
    mode = str(section.get("mode") or "hard").lower()
    return mode if mode in {"hard", "warn"} else "hard"


def _resolve_gitleaks(section: dict[str, Any]) -> str | None:
    custom = str(section.get("binary") or "").strip()
    if custom:
        path = Path(custom)
        if path.is_file():
            return str(path)
        which = shutil.which(custom)
        return which
    return shutil.which("gitleaks")


def _build_cmd(
    binary: str,
    root: Path,
    *,
    config_path: Path | None,
    report_path: Path,
) -> list[str]:
    cmd = [
        binary,
        "detect",
        "--source",
        str(root),
        "--no-banner",
        "--redact",
        "--report-path",
        str(report_path),
        "--report-format",
        "json",
        "--exit-code",
        "1",
    ]
    if config_path is not None and config_path.is_file():
        cmd.extend(["--config", str(config_path)])
    return cmd


def run_secrets_gate(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg.get("secrets") or {}
    if not section.get("enabled", True):
        print("[secrets] disabled — skip")
        return 0

    mode = _mode(section)
    out_dir = root / str(section.get("report_dir") or REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "gitleaks-report.json"
    summary_path = out_dir / "secrets-summary.json"

    binary = _resolve_gitleaks(section)
    config_rel = str(section.get("config") or DEFAULT_CONFIG)
    config_path = root / config_rel

    findings: list[dict[str, Any]] = []
    tool_note = ""
    tool_rc: int | None = None

    if binary is None:
        tool_note = (
            "gitleaks binary not found on PATH. Install gitleaks "
            "(https://github.com/gitleaks/gitleaks) or set secrets.binary. "
            f"See {DOC}."
        )
        findings.append(
            {
                "file": "",
                "kind": "missing_binary",
                "detail": tool_note,
            }
        )
    else:
        cmd = _build_cmd(binary, root, config_path=config_path, report_path=report_path)
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        tool_rc = proc.returncode
        tool_note = ((proc.stdout or "") + (proc.stderr or "")).strip()[:4000]
        if tool_rc == 1:
            # Leaks found — prefer structured report when present.
            leaks: list[Any] = []
            if report_path.is_file():
                try:
                    loaded = json.loads(report_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        leaks = loaded
                except json.JSONDecodeError:
                    leaks = []
            if leaks:
                for item in leaks[:50]:
                    if not isinstance(item, dict):
                        continue
                    findings.append(
                        {
                            "file": str(item.get("File") or item.get("file") or ""),
                            "kind": str(item.get("RuleID") or item.get("Rule") or "leak"),
                            "detail": str(
                                item.get("Description")
                                or item.get("Secret")
                                or item.get("Match")
                                or "secret detected"
                            )[:240],
                        }
                    )
            else:
                findings.append(
                    {
                        "file": "",
                        "kind": "leak",
                        "detail": tool_note or "gitleaks exit 1 (secrets detected)",
                    }
                )
        elif tool_rc not in (0, None) and tool_rc != 1:
            findings.append(
                {
                    "file": "",
                    "kind": "tool_error",
                    "detail": tool_note or f"gitleaks exit {tool_rc}",
                }
            )

    passed = True if mode == "warn" else not findings
    payload = {
        "schemaVersion": 1,
        "mode": mode,
        "tool": "gitleaks",
        "binary": binary,
        "config": config_rel if config_path.is_file() else None,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
        "passed": passed,
        "toolRc": tool_rc,
        "toolNote": tool_note,
    }
    summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if findings:
        print(f"[secrets] {len(findings)} finding(s) (mode={mode})")
        for item in findings[:30]:
            loc = item["file"] or "(repo)"
            print(f"  {loc}: {item['kind']}: {item['detail'][:200]}")
        if len(findings) > 30:
            print(f"  … +{len(findings) - 30} more")
    else:
        print(f"[secrets] PASS (0 findings, tool=gitleaks)")

    if mode == "warn":
        print("[secrets] warn mode — not failing the gate")
        return 0
    return 0 if not findings else 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    return run_secrets_gate(find_repo_root(), context=context)


if __name__ == "__main__":
    raise SystemExit(main())
