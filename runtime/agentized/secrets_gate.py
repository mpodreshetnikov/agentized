"""Hard gitleaks secret scan (AGE-29).

Runs `gitleaks detect` against the repo. Default mode is hard/blocking on
pre-push and CI (via `quality check` gates). Missing binary fails closed when
mode=hard. `enabled: false` also fails closed unless a human-only
disable_decision (reason + approved_by + expires ≤14d, unexpired) is recorded.

Connect wiring lives here (not in connect.py) so AGE-29 stays out of the
full-cover mutation diff for connect: CLI calls `apply_secrets_connect`
after `connect()`.
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
from .quality_io import read_json_object

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
    if enabled is False or enabled == 0:
        return True
    if enabled is True:
        return False
    text = str(enabled).strip().lower()
    return text in _FALSEY


def _decision_field(decision: dict[str, Any], *keys: str) -> str:
    for key in keys:
        raw = decision.get(key)
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if len(text) > 0:
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
    if len(reason) == 0 or len(approved_by) == 0 or len(expires_raw) == 0:
        return False
    try:
        expires = datetime.fromisoformat(expires_raw)
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    clock = now if now is not None else datetime.now(timezone.utc)
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
    from .quality import save_quality
    from .quality_defaults import default_quality_config

    path = quality_path(root, context_rel)
    upgraded: list[str] = []
    if not path.is_file():
        return {"upgraded_modes": upgraded, "created": False}

    raw = read_json_object(path)
    data = load_quality(root, context_rel)
    dirty = False

    if "secrets" not in raw:
        injected = default_quality_config()["secrets"]
        if not isinstance(injected, dict):
            raise TypeError("default secrets must be a dict")
        data["secrets"] = injected
        upgraded.append("secrets")
        dirty = True
        gates = data.get("gates")
        if isinstance(gates, dict):
            for gate_key in ("pre_push", "ci"):
                names = list(gates.get(gate_key) or [])
                if "secrets" not in names:
                    if "mechanical" in names:
                        names.insert(names.index("mechanical") + 1, "secrets")
                    else:
                        names.insert(0, "secrets")
                    gates[gate_key] = names

    secrets = data.get("secrets")
    if isinstance(secrets, dict):
        disk = raw.get("secrets")
        if isinstance(disk, dict):
            secrets.update(disk)
        if _mode(secrets) == "warn":
            secrets["mode"] = "hard"
            if "secrets" not in upgraded:
                upgraded.append("secrets")
            dirty = True
        enabled = True if "enabled" not in secrets else secrets["enabled"]
        if _is_disabled_flag(enabled):
            if not disable_decision_valid(secrets):
                secrets["enabled"] = True
                if "secrets_enabled" not in upgraded:
                    upgraded.append("secrets_enabled")
                dirty = True

    if dirty is True:
        save_quality(root, data, context_rel)
    return {"upgraded_modes": upgraded, "created": False}


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
        if len(text) > 0:
            return text[:240]
    return "secret detected"


def _finding_file(item: dict[str, Any]) -> str:
    for key in ("File", "file"):
        raw = item.get(key)
        if isinstance(raw, str) and len(raw) > 0:
            return raw
    return ""


def _finding_kind(item: dict[str, Any]) -> str:
    for key in ("RuleID", "Rule"):
        raw = item.get(key)
        if isinstance(raw, str) and len(raw) > 0:
            return raw
    return "leak"


def _findings_from_report(report_path: Path, tool_note: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    leaks: list[Any] = []
    if report_path.is_file():
        try:
            loaded = json.loads(report_path.read_bytes().decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            loaded = []
        if isinstance(loaded, list):
            leaks = loaded
    for item in leaks[:50]:
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
    note = tool_note if tool_note != "" else "gitleaks exit 1 (secrets detected)"
    return [{"file": "", "kind": "leak", "detail": note}]


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
    raw_config = section.get("config")
    if isinstance(raw_config, str) and raw_config.strip() != "":
        config_rel = raw_config.strip()
    else:
        config_rel = DEFAULT_CONFIG
    config_path = root / config_rel
    if config_path.is_file():
        config_for_summary = config_rel
    else:
        config_for_summary = None

    enabled = True if "enabled" not in section else section["enabled"]
    if _is_disabled_flag(enabled):
        if disable_decision_valid(section):
            skip_msg = "[secrets] disabled by recorded decision — skip"
            print(skip_msg)
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
        print(f"[secrets] 1 finding(s) (mode={mode})")
        print(f"  (repo): disabled_without_decision: {detail[:200]}")
        if mode == "warn":
            print("[secrets] warn mode — not failing the gate")
            return 0
        return 1

    findings: list[dict[str, Any]] = []
    tool_note = ""
    tool_rc: int | None = None
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
        stdout = proc.stdout if isinstance(proc.stdout, str) else ""
        stderr = proc.stderr if isinstance(proc.stderr, str) else ""
        tool_note = (stdout + stderr).strip()[:4000]
        if tool_rc == 1:
            findings = _findings_from_report(report_path, tool_note)
        elif tool_rc != 0:
            findings.append(
                {
                    "file": "",
                    "kind": "tool_error",
                    "detail": tool_note if tool_note != "" else f"gitleaks exit {tool_rc}",
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

    if findings:
        print(f"[secrets] {len(findings)} finding(s) (mode={mode})")
        for item in findings[:30]:
            loc = item["file"] if item["file"] != "" else "(repo)"
            print(f"  {loc}: {item['kind']}: {item['detail'][:200]}")
        extra = len(findings) - 30
        if extra > 0:
            print(f"  … +{extra} more")
    else:
        print("[secrets] PASS (0 findings, tool=gitleaks)")

    if mode == "warn":
        print("[secrets] warn mode — not failing the gate")
        return 0
    if findings:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        args = list(sys.argv[1:])
    else:
        args = list(argv)
    context = DEFAULT_CONTEXT
    if "--context" in args:
        context = args[args.index("--context") + 1]
    return run_secrets_gate(find_repo_root(), context=context)


if __name__ == "__main__":
    raise SystemExit(main())
