"""Hard gitleaks secret scan (AGE-29).

Runs `gitleaks detect` against the repo. Default mode is hard/blocking on
pre-push and CI (via `quality check` gates). Missing binary fails closed when
mode=hard. `enabled: false` also fails closed in hard mode unless an explicit
human-only disable_decision (reason + approved_by + expires ≤14d, unexpired)
is recorded.

Connect wiring lives here (not in connect.py) so AGE-29 stays out of the
full-cover mutation diff for connect/mutation: CLI calls
`persist_secrets_policy` + `pin_gitleaks_config` after `connect()`.
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
from .quality import load_quality

DOC = "docs/QUALITY.md"
DEFAULT_CONFIG = ".gitleaks.toml"
REPORT_DIR = "reports/secrets"
MAX_DISABLE_DAYS = 14


def _mode(section: dict[str, Any]) -> str:
    mode = str(section.get("mode") or "hard").lower()
    return mode if mode in {"hard", "warn"} else "hard"


def _is_disabled_flag(enabled: Any) -> bool:
    if enabled is False or enabled == 0:
        return True
    return str(enabled).lower() in {"false", "0", "no"}


def disable_decision_valid(section: dict[str, Any], *, now: datetime | None = None) -> bool:
    """True only with reason + approved_by + unexpired ISO expiry within ≤14d.

    Human-only escape hatch (Maxim hard-default). Missing any field, bad
    date, already expired, or expiry further than MAX_DISABLE_DAYS ahead →
    False (gate stays hard).
    """
    decision = section.get("disable_decision")
    if not isinstance(decision, dict):
        return False
    reason = str(decision.get("reason") or "").strip()
    approved_by = str(decision.get("approved_by") or "").strip()
    expires_raw = str(
        decision.get("expires") or decision.get("expiry") or decision.get("expires_at") or ""
    ).strip()
    if not reason or not approved_by or not expires_raw:
        return False
    try:
        expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    if expires <= clock:
        return False
    if expires - clock > timedelta(days=MAX_DISABLE_DAYS):
        return False
    return True


def _quality_templates_dir(root: Path) -> Path:
    local = root / "templates" / "quality"
    if local.is_dir() and any(local.iterdir()):
        return local
    # Installed Agentized root: runtime/agentized/secrets_gate.py → repo root.
    return Path(__file__).resolve().parents[2] / "templates" / "quality"


def pin_gitleaks_config(
    root: Path,
    context_rel: str = DEFAULT_CONTEXT,
    *,
    manifest: dict[str, Any] | None = None,
) -> str:
    """Pin `.gitleaks.toml` from templates via managed.json (AGE-29).

    Returns managed_copy status: created / unchanged / skipped_user / missing-src.
    """
    from .managed import load_managed, managed_copy_file, save_managed

    templates = _quality_templates_dir(root)
    src = templates / "gitleaks.toml.example"
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
    """Reconnect policy for secrets (AGE-29).

    - Inject default secrets section + gate entry when on-disk quality.json
      lacks `secrets`.
    - Flip secrets.mode warn→hard.
    - Force secrets.enabled=true unless a valid human disable_decision exists.
    """
    from .quality import quality_path, save_quality
    from .quality_defaults import default_quality_config
    from .quality_io import read_json_object

    path = quality_path(root, context_rel)
    upgraded: list[str] = []
    if not path.is_file():
        return {"upgraded_modes": upgraded, "created": False}

    raw = read_json_object(path)
    data = load_quality(root, context_rel)
    dirty = False

    if "secrets" not in raw:
        data["secrets"] = default_quality_config()["secrets"]
        upgraded.append("secrets")
        dirty = True
        gates = data.get("gates")
        if isinstance(gates, dict):
            for gate_key in ("pre_push", "ci"):
                names = list(gates.get(gate_key) or [])
                if "secrets" not in names:
                    if "mechanical" in names:
                        idx = names.index("mechanical") + 1
                        names.insert(idx, "secrets")
                    else:
                        names.insert(0, "secrets")
                    gates[gate_key] = names

    secrets = data.get("secrets")
    if isinstance(secrets, dict):
        if str(secrets.get("mode") or "").lower() == "warn":
            secrets["mode"] = "hard"
            if "secrets" not in upgraded:
                upgraded.append("secrets")
            dirty = True
        if _is_disabled_flag(secrets.get("enabled", True)) and not disable_decision_valid(
            secrets
        ):
            secrets["enabled"] = True
            if "secrets_enabled" not in upgraded:
                upgraded.append("secrets_enabled")
            dirty = True

    if dirty:
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
    passed = True if mode == "warn" else not findings
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
    summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def run_secrets_gate(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg.get("secrets") or {}
    mode = _mode(section)
    out_dir = root / str(section.get("report_dir") or REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "gitleaks-report.json"
    summary_path = out_dir / "secrets-summary.json"
    config_rel = str(section.get("config") or DEFAULT_CONFIG)
    config_path = root / config_rel

    enabled = section.get("enabled", True)
    if _is_disabled_flag(enabled):
        if disable_decision_valid(section):
            print("[secrets] disabled by recorded decision — skip")
            _write_summary(
                summary_path,
                mode=mode,
                binary=None,
                config_rel=config_rel if config_path.is_file() else None,
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
            config_rel=config_rel if config_path.is_file() else None,
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

    _write_summary(
        summary_path,
        mode=mode,
        binary=binary,
        config_rel=config_rel if config_path.is_file() else None,
        findings=findings,
        tool_rc=tool_rc,
        tool_note=tool_note,
    )

    if findings:
        print(f"[secrets] {len(findings)} finding(s) (mode={mode})")
        for item in findings[:30]:
            loc = item["file"] or "(repo)"
            print(f"  {loc}: {item['kind']}: {item['detail'][:200]}")
        if len(findings) > 30:
            print(f"  … +{len(findings) - 30} more")
    else:
        print("[secrets] PASS (0 findings, tool=gitleaks)")

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
