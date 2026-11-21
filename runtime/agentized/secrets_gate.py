"""Hard gitleaks secret scan (AGE-29).

Default mode hard on pre-push/CI. Missing binary fails closed when mode=hard.
`enabled: false` fails closed unless disable_decision (reason + approved_by +
expires ≤14d) is recorded. CLI calls `apply_secrets_connect` after `connect()`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality, quality_path
from .quality_io import read_json_object, write_json_object

DOC = "docs/QUALITY.md"
DEFAULT_CONFIG = ".gitleaks.toml"
REPORT_DIR = "reports/secrets"
MAX_DISABLE_DAYS = 14
_FALSEY = frozenset({"false", "0", "no"})


def _mode(section: dict[str, Any]) -> str:
    raw = section.get("mode")
    if not isinstance(raw, str):
        return "hard"
    mode = raw.lower()
    if mode == "warn":
        return "warn"
    return "hard"


def _is_disabled_flag(enabled: Any) -> bool:
    return str(enabled).strip().lower() in _FALSEY


def _decision_field(decision: dict[str, Any], *keys: str) -> str:
    for key in keys:
        raw = decision.get(key)
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if text:
            return text
    return ""


def disable_decision_valid(section: dict[str, Any], *, now: datetime | None = None) -> bool:
    """True only with reason + approved_by + unexpired ISO expiry within ≤14d."""
    decision = section.get("disable_decision")
    if not isinstance(decision, dict):
        return False
    reason = _decision_field(decision, "reason")
    approved_by = _decision_field(decision, "approved_by")
    expires_raw = _decision_field(decision, "expires", "expiry", "expires_at")
    if not reason or not approved_by or not expires_raw:
        return False
    try:
        expires = datetime.fromisoformat(expires_raw)
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now is None:
        clock = datetime.now(timezone.utc)
    else:
        clock = now
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    if expires <= clock:
        return False
    if expires - clock > timedelta(days=MAX_DISABLE_DAYS):
        return False
    return True


def secrets_section(root: Path, context: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    """Defaults from load_quality, overlaid with on-disk `secrets` (quality.py untouched)."""
    cfg = load_quality(root, context)
    base = dict(cfg.get("secrets") or {})
    path = quality_path(root, context)
    if not path.is_file():
        return base
    raw = read_json_object(path)
    overlay = raw.get("secrets")
    if isinstance(overlay, dict):
        base.update(overlay)
    return base


def _quality_templates_dir(root: Path) -> Path:
    local = root / "templates" / "quality"
    if local.is_dir():
        try:
            next(local.iterdir())
        except StopIteration:
            pass
        else:
            return local
    return Path(__file__).resolve().parents[2] / "templates" / "quality"


def pin_gitleaks_config(
    root: Path,
    context_rel: str = DEFAULT_CONTEXT,
    *,
    manifest: dict[str, Any] | None = None,
) -> str:
    """Pin `.gitleaks.toml` from templates via managed.json (AGE-29)."""
    from .managed import load_managed, managed_copy_file, save_managed

    src = _quality_templates_dir(root) / "gitleaks.toml.example"
    dst = root / DEFAULT_CONFIG
    if not src.is_file():
        return "missing-src"
    man = manifest if manifest is not None else load_managed(root, context_rel)
    status = managed_copy_file(root, context_rel, src, dst, manifest=man)
    if manifest is None:
        save_managed(root, context_rel, man)
    return status


def persist_secrets_policy(
    root: Path,
    context_rel: str = DEFAULT_CONTEXT,
) -> dict[str, Any]:
    """Reconnect policy: inject secrets, warn→hard, force-enable without decision."""
    from .quality_defaults import default_quality_config

    path = quality_path(root, context_rel)
    upgraded: list[str] = []
    if not path.is_file():
        return {"upgraded_modes": upgraded, "created": False}

    raw = read_json_object(path)
    # quality._normalize omits secrets → write via write_json_object.
    out = dict(raw)

    if "secrets" not in raw:
        out["secrets"] = dict(default_quality_config()["secrets"])
        upgraded.append("secrets")
        gates = out.get("gates")
        if isinstance(gates, dict):
            gates = dict(gates)
            out["gates"] = gates
            for gate_key in ("pre_push", "ci"):
                names = list(gates.get(gate_key) or [])
                if "secrets" not in names:
                    if "mechanical" in names:
                        names.insert(names.index("mechanical") + 1, "secrets")
                    else:
                        names.insert(0, "secrets")
                    gates[gate_key] = names

    secrets_raw = out.get("secrets")
    if isinstance(secrets_raw, dict):
        secrets = dict(secrets_raw)
        out["secrets"] = secrets
        if _mode(secrets) == "warn":
            secrets["mode"] = "hard"
            upgraded.append("secrets")
        if "enabled" in secrets and _is_disabled_flag(secrets["enabled"]):
            if not disable_decision_valid(secrets):
                secrets["enabled"] = True
                upgraded.append("secrets_enabled")

    if upgraded:
        write_json_object(path, out)
    unique: list[str] = []
    for tag in upgraded:
        if tag not in unique:
            unique.append(tag)
    return {"upgraded_modes": unique, "created": False}


def apply_secrets_connect(
    root: Path,
    context_rel: str = DEFAULT_CONTEXT,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """CLI post-connect: persist secrets policy + pin gitleaks.toml."""
    policy = persist_secrets_policy(root, context_rel)
    gitleaks = pin_gitleaks_config(root, context_rel, manifest=manifest)
    return {
        "upgraded_modes": list(policy.get("upgraded_modes") or []),
        "gitleaks_config": gitleaks,
    }


def _resolve_gitleaks(section: dict[str, Any]) -> str | None:
    custom = str(section.get("binary") or "").strip()
    if custom == "":
        return shutil.which("gitleaks")
    path = Path(custom)
    if path.is_file():
        return str(path)
    return shutil.which(custom)


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


def _write_summary(
    summary_path: Path,
    *,
    mode: str,
    binary: str | None,
    config_rel: str | None,
    findings: list[dict[str, Any]],
    tool_rc: int | None,
    tool_note: str,
) -> dict[str, Any]:
    if mode == "warn":
        passed = True
    else:
        passed = len(findings) == 0
    payload = {
        "schemaVersion": 1,
        "mode": mode,
        "tool": "gitleaks",
        "binary": binary,
        "config": config_rel,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
        "passed": passed,
        "toolRc": tool_rc,
        "toolNote": tool_note,
    }
    text = json.dumps(payload, indent=2) + "\n"
    summary_path.write_bytes(text.encode())
    return payload


def _finding_detail(item: dict[str, Any]) -> str:
    for key in ("Description", "Secret", "Match"):
        raw = item.get(key)
        if raw is None:
            continue
        text = str(raw)
        if text:
            return text[:240]
    return "secret detected"


def _finding_file(item: dict[str, Any]) -> str:
    for key in ("File", "file"):
        raw = item.get(key)
        if type(raw) is str and raw:
            return raw
    return ""


def _finding_kind(item: dict[str, Any]) -> str:
    for key in ("RuleID", "Rule"):
        raw = item.get(key)
        if type(raw) is str and raw:
            return raw
    return "leak"


def _findings_from_report(report_path: Path, tool_note: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    leaks: list[Any] = []
    if report_path.is_file():
        try:
            loaded = json.loads(report_path.read_bytes().decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        else:
            if isinstance(loaded, list):
                leaks = loaded
    for item in leaks:
        if not isinstance(item, dict):
            continue
        findings.append(
            {
                "file": _finding_file(item),
                "kind": _finding_kind(item),
                "detail": _finding_detail(item),
            }
        )
    if findings:
        return findings
    note = tool_note if tool_note else "gitleaks exit 1 (secrets detected)"
    return [{"file": "", "kind": "leak", "detail": note}]


_PRINT_DETAIL = 200
_TOOL_NOTE_MAX = 4000


def _gate_result(mode: str, findings: list[dict[str, Any]]) -> int:
    if findings:
        print(f"[secrets] {len(findings)} finding(s) (mode={mode})")
        first = findings[0]
        loc = first["file"] or "(repo)"
        print(f"  {loc}: {first['kind']}: {first['detail'][:_PRINT_DETAIL]}")
    else:
        print("[secrets] PASS (0 findings, tool=gitleaks)")
    if mode == "warn":
        print("[secrets] warn mode — not failing the gate")
        return 0
    return 1 if findings else 0


def run_secrets_gate(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
) -> int:
    root = root or find_repo_root()
    section = secrets_section(root, context)
    mode = _mode(section)
    out_dir = root / str(section.get("report_dir") or REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "gitleaks-report.json"
    summary_path = out_dir / "secrets-summary.json"
    config_rel = DEFAULT_CONFIG
    raw_config = section.get("config")
    if isinstance(raw_config, str):
        stripped = raw_config.strip()
        if stripped:
            config_rel = stripped
    config_path = root / config_rel
    if config_path.is_file():
        config_for_summary = config_rel
    else:
        config_for_summary = None

    if "enabled" in section and _is_disabled_flag(section["enabled"]):
        if disable_decision_valid(section):
            print("[secrets] disabled by recorded decision — skip")
            _write_summary(
                summary_path,
                mode=mode,
                binary=None,
                config_rel=config_for_summary,
                findings=[],
                tool_rc=None,
                tool_note="disabled_by_decision",
            )
            return 0
        detail = (
            "secrets.enabled=false without a valid disable_decision "
            "(reason + approved_by + unexpired expires ≤14d, human-only). "
            f"Hard-by-default — record a decision or set enabled=true. See {DOC}."
        )
        findings = [{"file": "", "kind": "disabled_without_decision", "detail": detail}]
        _write_summary(
            summary_path,
            mode=mode,
            binary=None,
            config_rel=config_for_summary,
            findings=findings,
            tool_rc=None,
            tool_note=detail,
        )
        return _gate_result(mode, findings)

    findings: list[dict[str, Any]] = []
    tool_rc = None
    binary = _resolve_gitleaks(section)

    if binary is None:
        tool_note = (
            "gitleaks binary not found on PATH. Install gitleaks "
            "(https://github.com/gitleaks/gitleaks) or set secrets.binary. "
            f"See {DOC}."
        )
        findings.append({"file": "", "kind": "missing_binary", "detail": tool_note})
    else:
        cmd = _build_cmd(binary, root, config_path=config_path, report_path=report_path)
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
        tool_rc = proc.returncode
        tool_note = f"{proc.stdout}{proc.stderr}".strip()[:_TOOL_NOTE_MAX]
        if tool_rc == 1:
            findings = _findings_from_report(report_path, tool_note)
        elif tool_rc != 0:
            findings.append(
                {
                    "file": "",
                    "kind": "tool_error",
                    "detail": tool_note or f"gitleaks exit {tool_rc}",
                }
            )

    _write_summary(
        summary_path,
        mode=mode,
        binary=binary,
        config_rel=config_for_summary,
        findings=findings,
        tool_rc=tool_rc,
        tool_note=tool_note,
    )
    return _gate_result(mode, findings)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        args = list(sys.argv[1:])
    else:
        args = list(argv)
    context = DEFAULT_CONTEXT
    if "--context" in args:
        idx = args.index("--context")
        context = args[idx + 1]
    return run_secrets_gate(find_repo_root(), context=context)


if __name__ == "__main__":
    raise SystemExit(main())
