"""Independent strong-reviewer budget + watermark (Orbit review-delta mechanism)."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# git diff --numstat --find-renames: `.github/{disabled => workflows}/deploy.yml`
_RENAME_BRACE = re.compile(r"\{([^{}]*) => ([^{}]*)\}")

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

STATE_DIR = ".agentized"
STATE_FILE = "review-state.json"
DOC = "docs/QUALITY.md"
ENV_SCOPE = "AGENTIZED_REVIEW_SCOPE"


def default_reviewer_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "helper_model": "composer-2",
        "budget_max": 3,
        "delta_lines": 200,
        "harnesses": {
            "cursor": {
                "model": "grok-4.7[reasoning_effort=medium]",
                "effort": "medium",
            },
            "claude": {"model": "claude-fable-5-2", "effort": "medium"},
            "codex": {"model": "gpt-6-astra", "effort": "medium"},
        },
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


def resolve_scope(scope: str | None = None) -> str:
    """Task/PR identity for budget + watermark (env AGENTIZED_REVIEW_SCOPE or 'default')."""
    raw = (scope if scope is not None else os.environ.get(ENV_SCOPE) or "default").strip()
    return raw or "default"


def _empty_scope() -> dict[str, Any]:
    return {
        "used": 0,
        "budget_max": None,
        "watermark": None,
        "open_findings": 0,
        "history": [],
    }


def _migrate_store(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize on-disk state to scoped form; migrate legacy flat files."""
    if isinstance(data.get("scopes"), dict):
        scopes = {str(k): dict(v) if isinstance(v, dict) else _empty_scope() for k, v in data["scopes"].items()}
        active = data.get("active_scope") or "default"
        return {"scopes": scopes, "active_scope": str(active)}
    # Legacy flat {used, watermark, ...} → scopes.default
    if any(k in data for k in ("used", "watermark", "open_findings", "history")):
        flat = {**_empty_scope(), **{k: data[k] for k in _empty_scope() if k in data}}
        return {"scopes": {"default": flat}, "active_scope": "default"}
    return {"scopes": {}, "active_scope": "default"}


def load_store(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists():
        return {"scopes": {}, "active_scope": "default"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"scopes": {}, "active_scope": "default"}
    if not isinstance(data, dict):
        return {"scopes": {}, "active_scope": "default"}
    return _migrate_store(data)


def save_store(root: Path, store: dict[str, Any]) -> Path:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return path


def load_state(root: Path, *, scope: str | None = None) -> dict[str, Any]:
    """Load budget/watermark for one task/PR scope (legacy-compatible keys)."""
    sid = resolve_scope(scope)
    store = load_store(root)
    scopes = store.setdefault("scopes", {})
    if sid not in scopes or not isinstance(scopes[sid], dict):
        scopes[sid] = _empty_scope()
    return dict(scopes[sid])


def save_state(root: Path, data: dict[str, Any], *, scope: str | None = None) -> Path:
    sid = resolve_scope(scope)
    store = load_store(root)
    store.setdefault("scopes", {})[sid] = data
    store["active_scope"] = sid
    return save_store(root, store)


def reset_scope(root: Path, *, scope: str | None = None) -> dict[str, Any]:
    """Explicit lifecycle reset for a task/PR so unrelated work gets a fresh budget."""
    sid = resolve_scope(scope)
    empty = _empty_scope()
    save_state(root, empty, scope=sid)
    return {
        "ok": True,
        "scope": sid,
        "message": f"review scope '{sid}' reset (used=0, watermark cleared). See {DOC}.",
        **empty,
    }


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


def _commit_exists(root: Path, sha: str) -> bool:
    if not sha or not sha.strip():
        return False
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{sha.strip()}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _resolve_commit(root: Path, sha: str) -> str | None:
    sha = (sha or "").strip()
    if not sha:
        return None
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _match(path: str, patterns: list[str]) -> bool:
    path = path.replace("\\", "/")
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def decode_git_path(path: str) -> str:
    """Decode a Git pathname (quoted C-style or plain).

    Default ``core.quotePath`` emits forms like
    ``\".github/workflows/d\\303\\251ploy.yml\"``; naive ``\\\\`` → ``/`` rewriting
    breaks sensitive-glob matching. Octal escapes are UTF-8 bytes.
    """
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        raw = path[1:-1]
        out = bytearray()
        i = 0
        while i < len(raw):
            ch = raw[i]
            if ch != "\\" or i + 1 >= len(raw):
                out.extend(ch.encode("utf-8"))
                i += 1
                continue
            nxt = raw[i + 1]
            simple = {
                "a": 7,
                "b": 8,
                "t": 9,
                "n": 10,
                "v": 11,
                "f": 12,
                "r": 13,
                '"': 34,
                "\\": 92,
            }
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            if nxt in "01234567":
                j = i + 1
                digits = ""
                while j < len(raw) and len(digits) < 3 and raw[j] in "01234567":
                    digits += raw[j]
                    j += 1
                out.append(int(digits, 8))
                i = j
                continue
            out.append(ord(nxt))
            i += 2
        return out.decode("utf-8")
    # Unquoted: only normalize Windows separators; do not touch escape sequences.
    return path.replace("\\", "/")


def expand_numstat_paths(path: str) -> list[str]:
    """Expand git --numstat rename display paths into concrete endpoints.

    Examples:
      ``.github/{disabled => workflows}/deploy.yml``
        → ``.github/disabled/deploy.yml``, ``.github/workflows/deploy.yml``
      ``old.py => new.py`` → ``old.py``, ``new.py``
    """
    path = decode_git_path(path)
    m = _RENAME_BRACE.search(path)
    if m:
        prefix = path[: m.start()]
        suffix = path[m.end() :]
        return [
            decode_git_path(f"{prefix}{m.group(1)}{suffix}"),
            decode_git_path(f"{prefix}{m.group(2)}{suffix}"),
        ]
    if " => " in path:
        left, right = path.split(" => ", 1)
        return [decode_git_path(left), decode_git_path(right)]
    return [path]


def _parse_numstat_z(data: bytes) -> list[tuple[str, int]]:
    """Parse ``git diff --numstat -z`` into ``(path, added_lines)`` rows.

    Renames emit ``added\\tdeleted\\t\\0old\\0new\\0``; normal/binary rows emit
    ``added\\tdeleted\\tpath\\0``. Binary counts (``-``) are kept with ``added=0``
    so sensitive globs still see the path.
    """
    out: list[tuple[str, int]] = []
    i = 0
    n = len(data)
    while i < n:
        tab1 = data.find(b"\t", i)
        if tab1 < 0:
            break
        added_s = data[i:tab1].decode("ascii", errors="replace")
        tab2 = data.find(b"\t", tab1 + 1)
        if tab2 < 0:
            break
        rest = tab2 + 1
        paths: list[str]
        if rest < n and data[rest : rest + 1] == b"\0":
            # Rename: empty path field, then old\0new\0
            rest += 1
            z1 = data.find(b"\0", rest)
            if z1 < 0:
                break
            old = data[rest:z1].decode("utf-8")
            z2 = data.find(b"\0", z1 + 1)
            if z2 < 0:
                break
            new = data[z1 + 1 : z2].decode("utf-8")
            paths = [old, new]
            i = z2 + 1
        else:
            z = data.find(b"\0", rest)
            if z < 0:
                break
            paths = [data[rest:z].decode("utf-8")]
            i = z + 1
        if added_s == "-":
            added = 0
        else:
            try:
                added = int(added_s)
            except ValueError:
                continue
        if len(paths) == 2:
            # Source for sensitive match; destination carries line delta.
            out.append((paths[0].replace("\\", "/"), 0))
            out.append((paths[1].replace("\\", "/"), added))
        else:
            out.append((paths[0].replace("\\", "/"), added))
    return out


def _numstat_since(root: Path, since: str) -> tuple[list[tuple[str, int]] | None, str | None]:
    """Return (files, error). error set when watermark/compare cannot be resolved.

    Uses the two-commit form ``git diff <watermark> HEAD`` so a dirty worktree
    cannot hide (or invent) changes relative to the commit under review.
    ``-z`` avoids core.quotePath mangling; binary ``-\\t-`` rows are retained
    with zero added lines for sensitive-glob evaluation.
    """
    if not _commit_exists(root, since):
        return None, f"watermark commit unavailable: {since}"
    head = _head_sha(root)
    if not head:
        return None, "HEAD unavailable for watermark comparison"
    proc = subprocess.run(
        ["git", "diff", "--numstat", "-z", "--find-renames", since, "HEAD"],
        cwd=root,
        capture_output=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip() or (
            "git diff failed"
        )
        return None, f"cannot compare to watermark {since[:12]}: {err}"
    return _parse_numstat_z(proc.stdout or b""), None


def evaluate_delta(root: Path, since: str, cfg: dict[str, Any]) -> dict[str, Any]:
    files, err = _numstat_since(root, since)
    if err is not None:
        return {
            "ok": False,
            "error": err,
            "reviewable_lines": 0,
            "threshold": int(cfg.get("delta_lines") or 200),
            "sensitive": [],
            "reasons": [],
            "request": False,
            "files": 0,
        }
    assert files is not None
    sensitive_globs = list(cfg.get("sensitive_globs") or [])
    sensitive: list[str] = []
    seen_sens: set[str] = set()
    for raw, _ in files:
        for path in expand_numstat_paths(raw):
            if path in seen_sens:
                continue
            if _match(path, sensitive_globs):
                sensitive.append(path)
                seen_sens.add(path)
    trivial = list(cfg.get("trivial_globs") or [])
    excepts = list(cfg.get("trivial_except_globs") or [])
    reviewable = 0
    for raw, added in files:
        # Line accounting uses the destination endpoint of a rename.
        path = expand_numstat_paths(raw)[-1]
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
        "ok": True,
        "error": None,
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
    scope: str | None = None,
) -> dict[str, Any]:
    cfg = reviewer_config(root, context_rel)
    sid = resolve_scope(scope)
    if not cfg.get("enabled", True):
        return {
            "ok": False,
            "action": "disabled",
            "scope": sid,
            "message": "reviewer disabled in quality.json",
        }
    state = load_state(root, scope=sid)
    budget = int(cfg.get("budget_max") or 3)
    used = int(state.get("used") or 0)
    head = _head_sha(root)
    watermark = (state.get("watermark") or "") or None
    open_findings = int(state.get("open_findings") or 0)

    base = {
        "scope": sid,
        "used": used,
        "budget_max": budget,
        "watermark": watermark,
        "head": head,
        "open_findings": open_findings,
    }

    if watermark and head and watermark == head and not force:
        return {
            "ok": False,
            "action": "skip",
            "message": (
                f"review skip: head {head[:12]} already reviewed (watermark) "
                f"[scope={sid}]. See {DOC}."
            ),
            **base,
        }

    if used >= budget and not force:
        return {
            "ok": False,
            "action": "escalate",
            "message": (
                f"REFUSED. review budget exhausted ({used}/{budget}) [scope={sid}]. "
                f"Escalate to human with open_findings={open_findings}; "
                f"or `agentized review reset --scope {sid}` for a new task/PR. "
                f"See {DOC}."
            ),
            **base,
        }

    if not watermark:
        return {
            "ok": True,
            "action": "request",
            "message": (
                f"review allow: first pass for scope '{sid}' "
                f"(budget {used}/{budget}). Call readonly reviewer, then "
                f"`agentized review record --sha <Reviewed-commit> --scope {sid}`."
            ),
            **base,
        }

    # Always resolve the watermark before any allow path (including fix-pack).
    delta = evaluate_delta(root, watermark, cfg)
    if not delta.get("ok", True):
        return {
            "ok": False,
            "action": "blocked",
            "message": (
                f"review blocked: {delta.get('error')}. "
                f"Recover: `agentized review reset --scope {sid}` or record a valid "
                f"watermark. See {DOC}."
            ),
            "delta": delta,
            **base,
        }

    # Fix-pack re-review: open findings after a valid watermark, new head, budget left.
    # Small non-sensitive deltas still request when findings remain open.
    if open_findings > 0 and head and watermark != head and not force:
        return {
            "ok": True,
            "action": "request",
            "message": (
                f"review allow: open_findings={open_findings} since watermark "
                f"{watermark[:12]} — re-review fix pack "
                f"(budget {used}/{budget}) [scope={sid}]."
            ),
            "delta": delta,
            **base,
        }

    if not delta["request"] and not force:
        return {
            "ok": False,
            "action": "skip",
            "message": (
                f"review skip: {delta['reviewable_lines']} reviewable lines since "
                f"watermark {watermark[:12]} (under {delta['threshold']}), "
                f"no sensitive paths [scope={sid}]. See {DOC}."
            ),
            "delta": delta,
            **base,
        }

    return {
        "ok": True,
        "action": "request",
        "message": (
            "review allow: "
            + ("; ".join(delta["reasons"]) if delta["reasons"] else "forced")
            + f" (budget {used}/{budget}) [scope={sid}]."
        ),
        "delta": delta,
        **base,
    }


def record_review(
    root: Path,
    sha: str,
    *,
    findings: int = 0,
    context_rel: str = DEFAULT_CONTEXT,
    scope: str | None = None,
) -> dict[str, Any]:
    cfg = reviewer_config(root, context_rel)
    sid = resolve_scope(scope)
    state = load_state(root, scope=sid)
    budget = int(cfg.get("budget_max") or 3)
    resolved = _resolve_commit(root, sha)
    if resolved is None:
        raise ValueError(
            f"invalid commit for review record: {sha!r} "
            f"(must resolve to an existing git commit object)"
        )
    sha = resolved
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
    save_state(root, state, scope=sid)
    return {
        "ok": True,
        "scope": sid,
        "used": used,
        "budget_max": budget,
        "watermark": sha,
        "open_findings": int(findings),
        "message": (
            f"review recorded [scope={sid}]: watermark={sha[:12]} "
            f"used={used}/{budget} findings={findings}"
        ),
    }


def status(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    scope: str | None = None,
) -> dict[str, Any]:
    cfg = reviewer_config(root, context_rel)
    sid = resolve_scope(scope)
    state = load_state(root, scope=sid)
    store = load_store(root)
    budget = int(cfg.get("budget_max") or state.get("budget_max") or 3)
    harnesses = cfg.get("harnesses") if isinstance(cfg.get("harnesses"), dict) else {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "scope": sid,
        "scopes": sorted(store.get("scopes") or {}),
        "model": cfg.get("model"),
        "effort": cfg.get("effort"),
        "harnesses": harnesses,
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
    scope = args[args.index("--scope") + 1] if "--scope" in args else None
    if args and args[0] == "status":
        print(json.dumps(status(root, context_rel=context, scope=scope), indent=2))
        return 0
    if args and args[0] == "reset":
        result = reset_scope(root, scope=scope)
        print(result["message"])
        if "--json" in args:
            print(json.dumps(result, indent=2))
        return 0
    if args and args[0] == "allow":
        force = "--force" in args
        result = allow_review(root, context_rel=context, force=force, scope=scope)
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
        try:
            result = record_review(
                root, sha, findings=findings, context_rel=context, scope=scope
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(result["message"])
        if "--json" in args:
            print(json.dumps(result, indent=2))
        return 0
    print(
        "usage: review_budget.py status|allow|record|reset "
        "[--sha SHA] [--findings N] [--scope ID]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
