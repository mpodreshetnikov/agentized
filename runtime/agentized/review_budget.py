"""Independent strong-reviewer budget + watermark (Orbit review-delta mechanism)."""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

STATE_DIR = ".agentized"
STATE_FILE = "review-state.json"
DOC = "docs/QUALITY.md"


def default_reviewer_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "model": "claude-opus-4.5",
        "effort": "high",
        "helper_model": "composer-2",
        "budget_max": 3,
        "delta_lines": 200,
        "sensitive_globs": [
            "runtime/**",
            "packages/shared/**",
            ".github/workflows/**",
            ".githooks/**",
            "context/quality.json",
            "context/process-control.json",
            "context/env-check.json",
            "AGENTS.md",
            "docs/QUALITY.md",
            "docs/process-control.md",
        ],
        "trivial_globs": [
            "**/*.md",
            "**/LICENSE*",
            "**/.gitkeep",
        ],
        "trivial_except_globs": [
            "docs/QUALITY.md",
            "docs/process-control.md",
            "docs/connect-contract.md",
            "AGENTS.md",
            "context/quality.json",
            "context/process-control.json",
            "context/env-check.json",
            "packages/shared/agents/**",
            "packages/shared/skills/**",
        ],
    }


def reviewer_config(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    cfg = default_reviewer_config()
    data = load_quality(root, context_rel).get("reviewer") or {}
    if isinstance(data, dict):
        # Preserve default sensitive/trivial lists unless quality.json overrides them.
        for key, value in data.items():
            if value is None:
                continue
            cfg[key] = value
    return cfg


def state_path(root: Path) -> Path:
    return root / STATE_DIR / STATE_FILE


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists():
        return {
            "used": 0,
            "budget_max": None,
            "watermark": None,
            "open_findings": 0,
            "history": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "used": 0,
            "budget_max": None,
            "watermark": None,
            "open_findings": 0,
            "history": [],
        }
    if not isinstance(data, dict):
        return {
            "used": 0,
            "budget_max": None,
            "watermark": None,
            "open_findings": 0,
            "history": [],
        }
    return data


def save_state(root: Path, data: dict[str, Any]) -> Path:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _head_sha(root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _match(path: str, patterns: list[str]) -> bool:
    path = path.replace("\\", "/")
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def _numstat_since(root: Path, since: str) -> list[tuple[str, int]]:
    proc = subprocess.run(
        ["git", "diff", "--numstat", "--find-renames", since],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    out: list[tuple[str, int]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or parts[0] == "-":
            continue
        try:
            added = int(parts[0])
        except ValueError:
            continue
        out.append((parts[2].replace("\\", "/"), added))
    return out


def evaluate_delta(root: Path, since: str, cfg: dict[str, Any]) -> dict[str, Any]:
    files = _numstat_since(root, since)
    sensitive = [
        p for p, _ in files if _match(p, list(cfg.get("sensitive_globs") or []))
    ]
    trivial = list(cfg.get("trivial_globs") or [])
    excepts = list(cfg.get("trivial_except_globs") or [])
    reviewable = 0
    for path, added in files:
        if _match(path, excepts):
            reviewable += added
            continue
        if trivial and _match(path, trivial):
            continue
        reviewable += added
    threshold = int(cfg.get("delta_lines") or 200)
    reasons: list[str] = []
    if reviewable > threshold:
        reasons.append(
            f"{reviewable} reviewable lines since {since[:12]} (over {threshold})"
        )
    for path in sensitive:
        reasons.append(f"{path} — sensitive surface")
    return {
        "reviewable_lines": reviewable,
        "threshold": threshold,
        "sensitive": sensitive,
        "reasons": reasons,
        "request": bool(reasons),
        "files": len(files),
    }


def allow_review(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    force: bool = False,
) -> dict[str, Any]:
    cfg = reviewer_config(root, context_rel)
    if not cfg.get("enabled", True):
        return {
            "ok": False,
            "action": "disabled",
            "message": "reviewer disabled in quality.json",
        }
    state = load_state(root)
    budget = int(cfg.get("budget_max") or 3)
    used = int(state.get("used") or 0)
    head = _head_sha(root)
    watermark = (state.get("watermark") or "") or None
    open_findings = int(state.get("open_findings") or 0)

    if watermark and head and watermark == head and not force:
        return {
            "ok": False,
            "action": "skip",
            "message": (
                f"review skip: head {head[:12]} already reviewed (watermark). "
                f"See {DOC}."
            ),
            "used": used,
            "budget_max": budget,
            "watermark": watermark,
            "head": head,
        }

    if used >= budget and not force:
        return {
            "ok": False,
            "action": "escalate",
            "message": (
                f"REFUSED. review budget exhausted ({used}/{budget}). "
                f"Escalate to human with open_findings={open_findings}; "
                f"do not spend more strong-reviewer rounds. See {DOC}."
            ),
            "used": used,
            "budget_max": budget,
            "watermark": watermark,
            "head": head,
            "open_findings": open_findings,
        }

    if not watermark:
        return {
            "ok": True,
            "action": "request",
            "message": (
                f"review allow: first pass for this task/PR "
                f"(budget {used}/{budget}). Call readonly reviewer, then "
                f"`agentized review record --sha <Reviewed-commit>`."
            ),
            "used": used,
            "budget_max": budget,
            "watermark": watermark,
            "head": head,
        }

    delta = evaluate_delta(root, watermark, cfg)
    if not delta["request"] and not force:
        return {
            "ok": False,
            "action": "skip",
            "message": (
                f"review skip: {delta['reviewable_lines']} reviewable lines since "
                f"watermark {watermark[:12]} (under {delta['threshold']}), "
                f"no sensitive paths. See {DOC}."
            ),
            "used": used,
            "budget_max": budget,
            "watermark": watermark,
            "head": head,
            "delta": delta,
        }

    return {
        "ok": True,
        "action": "request",
        "message": (
            "review allow: "
            + ("; ".join(delta["reasons"]) if delta["reasons"] else "forced")
            + f" (budget {used}/{budget})."
        ),
        "used": used,
        "budget_max": budget,
        "watermark": watermark,
        "head": head,
        "delta": delta,
    }


def record_review(
    root: Path,
    sha: str,
    *,
    findings: int = 0,
    context_rel: str = DEFAULT_CONTEXT,
) -> dict[str, Any]:
    cfg = reviewer_config(root, context_rel)
    state = load_state(root)
    budget = int(cfg.get("budget_max") or 3)
    sha = sha.strip()
    if not sha:
        raise ValueError("sha required")
    # resolve short sha if possible
    proc = subprocess.run(
        ["git", "rev-parse", sha],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        sha = (proc.stdout or "").strip()
    used = int(state.get("used") or 0) + 1
    history = list(state.get("history") or [])
    history.append({"sha": sha, "findings": int(findings)})
    state.update(
        {
            "used": used,
            "budget_max": budget,
            "watermark": sha,
            "open_findings": int(findings),
            "history": history[-20:],
        }
    )
    save_state(root, state)
    return {
        "ok": True,
        "used": used,
        "budget_max": budget,
        "watermark": sha,
        "open_findings": int(findings),
        "message": f"review recorded: watermark={sha[:12]} used={used}/{budget} findings={findings}",
    }


def status(root: Path, *, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    cfg = reviewer_config(root, context_rel)
    state = load_state(root)
    budget = int(cfg.get("budget_max") or state.get("budget_max") or 3)
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "model": cfg.get("model"),
        "effort": cfg.get("effort"),
        "helper_model": cfg.get("helper_model"),
        "used": int(state.get("used") or 0),
        "budget_max": budget,
        "watermark": state.get("watermark"),
        "open_findings": int(state.get("open_findings") or 0),
        "head": _head_sha(root),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    root = find_repo_root()
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    if args and args[0] == "status":
        print(json.dumps(status(root, context_rel=context), indent=2))
        return 0
    if args and args[0] == "allow":
        force = "--force" in args
        result = allow_review(root, context_rel=context, force=force)
        stream = sys.stdout if result.get("ok") else sys.stderr
        stream.write(result["message"] + "\n")
        if "--json" in args:
            print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args and args[0] == "record":
        sha = ""
        findings = 0
        if "--sha" in args:
            sha = args[args.index("--sha") + 1]
        else:
            sha = os.environ.get("REVIEW_SHA") or _head_sha(root)
        if "--findings" in args:
            findings = int(args[args.index("--findings") + 1])
        result = record_review(root, sha, findings=findings, context_rel=context)
        print(result["message"])
        if "--json" in args:
            print(json.dumps(result, indent=2))
        return 0
    print("usage: review_budget.py status|allow|record [--sha SHA] [--findings N]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
