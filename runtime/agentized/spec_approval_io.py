"""File/CLI I/O for spec-approval ."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT
from .process_control import load_process_config
from .spec_approval import evaluate_task_spec, spec_approval_from_config
from .spec_approval_defaults import (
    CFG_APPROVAL_HEADING,
    CFG_ENABLED,
    DEFAULT_APPROVAL_HEADING,
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
from .spec_approval_text import APPROVED_BY_RE, HEADING_PREFIX, is_claim_owner_identity
from .tasks import list_tasks

AUTHOR_MAIL_RE = re.compile(r"^author-mail <([^>]+)>\s*$")
FAILURE_JOIN = "; "


def _resolve_approval_heading(raw: Any) -> str:
    if raw is None:
        return DEFAULT_APPROVAL_HEADING
    text = str(raw).strip()
    if not text:
        return DEFAULT_APPROVAL_HEADING
    return text


def load_spec_approval(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    cfg = load_process_config(root, context_rel)
    return spec_approval_from_config(cfg)


def _human_participants(root: Path, context_rel: str) -> list[str]:
    cfg = load_process_config(root, context_rel)
    if not isinstance(cfg, dict):
        return []
    mp = cfg.get("merge_policy")
    if not isinstance(mp, dict):
        return []
    raw = mp.get("human_participants")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for p in raw:
        s = str(p).strip()
        if s:
            out.append(s)
    return out


def _blame_line_args(path: Path, line_no: int) -> list[str]:
    return ["git", "blame", "-L", f"{line_no},{line_no}", "--porcelain", str(path)]


def _git_blame_emails(root: Path, path: Path, line_no: int) -> set[str]:
    args = _blame_line_args(path, line_no)
    proc = subprocess.run(args, cwd=str(root), capture_output=True, text=True)
    if proc.returncode != 0:
        return set()
    emails: set[str] = set()
    for line in proc.stdout.splitlines():
        m = AUTHOR_MAIL_RE.match(line)
        if not m:
            continue
        mail = m.group(1).strip().lower()
        # porcelain uses not.committed.yet (no @) for dirty lines — require @.
        if "@" in mail:
            emails.add(mail)
    return emails


def approval_committed_by_non_owner(
    root: Path,
    task_path: Path,
    claim: str,
    approval_heading: str = DEFAULT_APPROVAL_HEADING,
) -> bool:
    """True when an Approval-section approved-by line was committed by a non-owner."""
    try:
        text = task_path.read_text()
    except OSError:
        return False
    heading = _resolve_approval_heading(approval_heading)
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return False
    end = len(lines)
    for i in range(start, len(lines)):
        line = lines[i]
        if line.startswith(HEADING_PREFIX) and line.strip() != heading:
            end = i
            break
    for i in range(start, end):
        line = lines[i]
        if not APPROVED_BY_RE.match(line):
            continue
        emails = _git_blame_emails(root, task_path, i + 1)
        for email in emails:
            if not is_claim_owner_identity(email, claim):
                return True
    return False


def spec_approval_check(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if policy is None:
        policy = load_spec_approval(root, context_rel)
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
        text = task.path.read_text()
        heading = _resolve_approval_heading(policy.get(CFG_APPROVAL_HEADING))
        non_owner = approval_committed_by_non_owner(
            root,
            task.path,
            task.claim,
            approval_heading=heading,
        )
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
    if failures:
        msg = FAILURE_JOIN.join(str(f[KEY_MESSAGE]) for f in failures)
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
