"""File/CLI I/O for spec-approval ."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT
from .process_control import load_process_config
from .spec_approval import evaluate_task_spec, spec_approval_from_config
from .spec_approval_defaults import (
    CFG_ENABLED,
    KEY_CHECKED,
    KEY_FAILURES,
    KEY_MESSAGE,
    KEY_MODE,
    KEY_OK,
    MODE_DISABLED,
    MODE_OK,
    MODE_REFUSE,
    MODE_SKIP,
    SPEC_GATE_STATUSES,
    checked_message,
    default_spec_approval,
)
from .spec_approval_text import APPROVED_BY_RE, identity_emails
from .tasks import list_tasks


def load_spec_approval(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    return spec_approval_from_config(load_process_config(root, context_rel))


def _human_participants(root: Path, context_rel: str) -> list[str]:
    cfg = load_process_config(root, context_rel)
    mp = cfg.get("merge_policy") if isinstance(cfg, dict) else None
    if not isinstance(mp, dict):
        return []
    raw = mp.get("human_participants")
    if not isinstance(raw, list):
        return []
    return [str(p).strip() for p in raw if str(p).strip()]


def _git_blame_emails(root: Path, path: Path, line_no: int) -> set[str]:
    proc = subprocess.run(
        ["git", "blame", "-L", f"{line_no},{line_no}", "--porcelain", str(path)],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return set()
    emails: set[str] = set()
    for line in proc.stdout.splitlines():
        if line.startswith("author-mail "):
            mail = line[len("author-mail ") :].strip().strip("<>").lower()
            if "@" in mail and mail != "not.committed.yet":
                emails.add(mail)
    return emails


def approval_committed_by_non_owner(root: Path, task_path: Path, claim: str) -> bool:
    """True when an approved-by line was last committed by someone other than claim."""
    try:
        text = task_path.read_text(encoding="utf-8")
    except OSError:
        return False
    claim_emails = identity_emails(claim)
    claim_l = (claim or "").strip().lower()
    for i, line in enumerate(text.splitlines(), start=1):
        if not APPROVED_BY_RE.match(line):
            continue
        emails = _git_blame_emails(root, task_path, i)
        if not emails:
            continue
        for email in emails:
            if claim_emails and email in claim_emails:
                continue
            if claim_l and (email == claim_l or email.startswith(claim_l + "@")):
                continue
            return True
    return False


def spec_approval_check(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or load_spec_approval(root, context_rel)
    if not bool(policy.get(CFG_ENABLED)):
        return {
            KEY_OK: True,
            KEY_MODE: MODE_DISABLED,
            KEY_MESSAGE: "",
            KEY_FAILURES: [],
            KEY_CHECKED: 0,
        }
    tasks_dir = root / context_rel / "tasks"
    allow = _human_participants(root, context_rel)
    failures: list[dict[str, Any]] = []
    checked = 0
    for task in list_tasks(tasks_dir):
        if task.status not in SPEC_GATE_STATUSES:
            continue
        text = task.path.read_text(encoding="utf-8")
        non_owner = approval_committed_by_non_owner(root, task.path, task.claim)
        result = evaluate_task_spec(
            task_id=task.task_id,
            claim=task.claim,
            tags=task.tags,
            text=text,
            policy=policy,
            human_participants=allow,
            approval_by_non_owner=non_owner,
        )
        if result[KEY_MODE] == MODE_SKIP:
            continue
        checked += 1
        if not result[KEY_OK]:
            failures.append(result)
    if len(failures) > 0:
        msg = "; ".join(str(f[KEY_MESSAGE]) for f in failures)
        return {
            KEY_OK: False,
            KEY_MODE: MODE_REFUSE,
            KEY_MESSAGE: msg,
            KEY_FAILURES: failures,
            KEY_CHECKED: checked,
        }
    return {
        KEY_OK: True,
        KEY_MODE: MODE_OK,
        KEY_MESSAGE: checked_message(checked),
        KEY_FAILURES: [],
        KEY_CHECKED: checked,
    }


def ensure_default_in_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge default block when missing (connect / defaults)."""
    out = dict(cfg)
    if "spec_approval" not in out:
        out["spec_approval"] = default_spec_approval()
    return out
