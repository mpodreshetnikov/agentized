"""File/CLI I/O for spec-approval ."""
from __future__ import annotations

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
    checked_message,
    default_spec_approval,
)
from .tasks import list_tasks


def load_spec_approval(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    return spec_approval_from_config(load_process_config(root, context_rel))


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
    failures: list[dict[str, Any]] = []
    checked = 0
    for task in list_tasks(tasks_dir):
        if task.status != "in-progress":
            continue
        text = task.path.read_text(encoding="utf-8")
        result = evaluate_task_spec(
            task_id=task.task_id,
            claim=task.claim,
            tags=task.tags,
            text=text,
            policy=policy,
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
