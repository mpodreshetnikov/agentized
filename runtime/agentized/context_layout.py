"""Nested or external Project Context (registry vs code-repo config). Fail-closed."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import DEFAULT_CONTEXT

LAYOUT_FILENAME = "context.json"
PLACEMENT_NESTED = "nested"
PLACEMENT_EXTERNAL = "external"
VALID_PLACEMENTS = (PLACEMENT_NESTED, PLACEMENT_EXTERNAL)

CODE_REPO_CONFIG_NAMES = (
    "quality.json",
    "process-control.json",
    "env-check.json",
    "reporting.json",
    LAYOUT_FILENAME,
)
CODE_REPO_PIN_DIRS = ("skills", "hooks", "agents")
REGISTRY_DIRS = ("tasks", "decisions", "goals", "leases", "digests")

ERR_INVALID_JSON = "context.json is not valid JSON"
ERR_INVALID_OBJECT = "context.json must be a JSON object"
ERR_UNREADABLE = "context.json is unreadable"
ERR_INVALID_EXTERNAL = "context.json external must be an object"
ERR_INVALID_EXTERNAL_FIELD = "context.json external.path/remote must be strings"
ERR_INVALID_PLACEMENT = "context.json placement must be nested|external"
ERR_EMPTY_PATH = "external.path is empty — set context/context.json external.path"
ERR_PATH_INSIDE = "external.path inside code repo must be gitignored"
ERR_BRIDGE_FOREIGN = "context bridge symlink points elsewhere — refuse replace"
ERR_BRIDGE_CONFLICT = (
    "local context path blocks external bridge — migrate into external Context, "
    "remove the local path, then re-run connect"
)


@dataclass(frozen=True)
class ContextLayout:
    placement: str
    code_context: Path
    registry_root: Path
    remote: str
    path_config: str

    @property
    def is_external(self) -> bool:
        return self.placement == PLACEMENT_EXTERNAL

    def tasks_dir(self) -> Path:
        return self.registry_root / "tasks"

    def decisions_dir(self) -> Path:
        return self.registry_root / "decisions"

    def goals_dir(self) -> Path:
        return self.registry_root / "goals"

    def leases_dir(self) -> Path:
        return self.registry_root / "leases"

    def digests_dir(self) -> Path:
        return self.registry_root / "digests"

    def nav_path(self) -> Path:
        return self.registry_root / "NAV.md"

    def config_path(self, name: str) -> Path:
        return self.code_context / name


def default_layout_config() -> dict[str, Any]:
    return {
        "version": 1,
        "placement": PLACEMENT_NESTED,
        "external": {"path": "", "remote": ""},
    }


def layout_config_path(root: Path, context_rel: str = DEFAULT_CONTEXT) -> Path:
    return root / context_rel / LAYOUT_FILENAME


def load_layout_config(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    cfg = default_layout_config()
    path = layout_config_path(root, context_rel)
    if not path.exists():
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{ERR_UNREADABLE}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{ERR_INVALID_JSON}: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{ERR_INVALID_OBJECT}: {path}")
    cfg = {**cfg, **{k: data[k] for k in data}}
    external = cfg.get("external")
    if not isinstance(external, dict):
        raise ValueError(f"{ERR_INVALID_EXTERNAL}: {path}")
    if "path" not in external:
        path_v = ""
    else:
        path_v = external["path"]
        if path_v is None:
            path_v = ""
    if "remote" not in external:
        remote_v = ""
    else:
        remote_v = external["remote"]
        if remote_v is None:
            remote_v = ""
    if not isinstance(path_v, str) or not isinstance(remote_v, str):
        raise ValueError(f"{ERR_INVALID_EXTERNAL_FIELD}: {path}")
    cfg["external"] = {"path": path_v, "remote": remote_v}
    raw_placement = cfg.get("placement")
    if raw_placement is None:
        raise ValueError(f"{ERR_INVALID_PLACEMENT} (got None): {path}")
    placement = str(raw_placement).strip().lower()
    if placement not in VALID_PLACEMENTS:
        raise ValueError(f"{ERR_INVALID_PLACEMENT} (got {cfg.get('placement')!r}): {path}")
    cfg["placement"] = placement
    return cfg


def resolve_external_path(root: Path, path_value: str) -> Path:
    raw = (path_value or "").strip()
    if raw == "":
        raise ValueError(ERR_EMPTY_PATH)
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def is_path_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def is_gitignored(root: Path, candidate: Path) -> bool:
    try:
        rel = str(candidate.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(candidate)
    proc = subprocess.run(
        ["git", "check-ignore", "-q", "--", rel],
        cwd=root,
        capture_output=True,
    )
    return proc.returncode == 0


def assert_external_path_allowed(root: Path, external_path: Path) -> None:
    if is_path_inside(root, external_path) and not is_gitignored(root, external_path):
        raise ValueError(f"{ERR_PATH_INSIDE}: {external_path}")


def is_git_checkout(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()


def resolve_layout(root: Path, context_rel: str = DEFAULT_CONTEXT) -> ContextLayout:
    root = root.resolve()
    cfg = load_layout_config(root, context_rel)
    code_context = (root / context_rel).resolve()
    placement = str(cfg.get("placement") or PLACEMENT_NESTED)
    external = cfg.get("external") or {}
    path_cfg = str(external.get("path") or "")
    remote = str(external.get("remote") or "")
    if placement == PLACEMENT_EXTERNAL:
        registry = resolve_external_path(root, path_cfg)
        assert_external_path_allowed(root, registry)
    else:
        registry = code_context
    return ContextLayout(
        placement=placement,
        code_context=code_context,
        registry_root=registry,
        remote=remote,
        path_config=path_cfg,
    )


def external_clone_problems(layout: ContextLayout) -> list[str]:
    if not layout.is_external:
        return []
    problems: list[str] = []
    root = layout.registry_root
    if not layout.path_config.strip():
        problems.append("context.json external.path is empty")
        return problems
    if not root.exists():
        hint = f" remote={layout.remote}" if layout.remote else ""
        problems.append(f"external Context path missing: {root}{hint}")
        return problems
    if not root.is_dir():
        problems.append(f"external Context path is not a directory: {root}")
        return problems
    if not is_git_checkout(root):
        problems.append(f"external Context is not a git checkout (no .git): {root}")
    if not (root / "NAV.md").exists():
        problems.append(f"external Context missing NAV.md: {root / 'NAV.md'}")
    if not (root / "tasks").is_dir():
        problems.append(f"external Context missing tasks/: {root / 'tasks'}")
    return problems


def require_registry_ready(layout: ContextLayout) -> None:
    if not layout.is_external:
        return
    problems = external_clone_problems(layout)
    if problems:
        raise ValueError("external Context not ready: " + "; ".join(problems))


# Minimal external-registry seed (empty git clone → connectable). Keep short for mut.
_EXT_NAV_MD = "# NAV — external Project Context\n\nSee tasks/INDEX.md and leases/INDEX.md.\n"
_EXT_TASKS_INDEX_MD = (
    "# Tasks\n\n## open\n\n_(empty)_\n\n## in-progress\n\n_(empty)_\n\n## blocked\n\n_(empty)_\n"
)
_EXT_LEASES_INDEX_MD = (
    "# Path leases\n\n| path | task | owner | expires |\n|------|------|-------|--------|\n"
)
_EXT_SEED_DIRS = ("tasks", "leases", "decisions", "goals", "digests")
_EXT_SEED_REL_PATHS = (
    ("NAV.md", _EXT_NAV_MD),
    ("tasks/INDEX.md", _EXT_TASKS_INDEX_MD),
    ("leases/INDEX.md", _EXT_LEASES_INDEX_MD),
)


def _atomic_write_text(path: Path, body: str) -> None:
    """Write ``body`` as UTF-8 via temp+replace (no 0-byte truncate on crash)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def ensure_external_registry_skeleton(layout: ContextLayout) -> list[str]:
    """Create NAV.md + indexes + bridge dirs in an empty external clone.

    No-op when not external. Requires ``registry_root`` to exist as a git checkout.
    Does not overwrite existing files. Callers must ``preflight_bridge_conflicts``
    first so a conflict never leaves a partial seed.
    """
    if not layout.is_external:
        return []
    root = layout.registry_root
    if not root.is_dir():
        raise ValueError(f"external Context path missing or not a directory: {root}")
    if not is_git_checkout(root):
        raise ValueError(f"external Context is not a git checkout (no .git): {root}")
    for sub in _EXT_SEED_DIRS:
        (root / sub).mkdir(exist_ok=True)
    created: list[str] = []
    for rel, body in _EXT_SEED_REL_PATHS:
        path = root / rel
        if path.exists():
            continue
        _atomic_write_text(path, body)
        created.append(str(path))
    return created


def preflight_bridge_conflicts(layout: ContextLayout) -> None:
    """Raise if any bridge path would conflict — no filesystem writes."""
    if not layout.is_external:
        return
    code = layout.code_context
    for name in BRIDGE_NAMES:
        src = layout.registry_root / name
        dest = code / name
        _bridge_preflight(src, dest)


def rollback_code_context_bridges(layout: ContextLayout, names: list[str]) -> None:
    """Remove bridge symlinks created for ``names`` (connect-failure cleanup)."""
    if not layout.is_external or not names:
        return
    code = layout.code_context
    for name in names:
        dest = code / name
        if dest.is_symlink():
            dest.unlink()


def ensure_layout_config(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict[str, Any]:
    path = layout_config_path(root, context_rel)
    created = not path.exists()
    if created:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(default_layout_config(), indent=2) + "\n",
            encoding="utf-8",
        )
    return {"path": str(path.relative_to(root)), "created": created}


ENV_CHECK_DOC = "docs/AGENT_ENVIRONMENT.md"
BRIDGE_NAMES = ("tasks", "leases", "decisions", "goals", "digests", "NAV.md")
BRIDGE_GITIGNORE_MARKER = "# Agentized: external Context bridges (local symlinks; do not commit)"


def _path_is_empty_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    entries = list(path.iterdir())
    return not entries or (
        len(entries) == 1 and entries[0].name == ".gitkeep" and entries[0].is_file()
    )


def _clear_empty_bridge_dir(path: Path) -> None:
    for child in list(path.iterdir()):
        if child.name == ".gitkeep" and child.is_file():
            child.unlink()
    path.rmdir()


def _bridge_link_target(src: Path, dest: Path) -> str:
    return os.path.relpath(str(src.resolve()), start=str(dest.parent.resolve()))


def _bridge_preflight(src: Path, dest: Path) -> str:
    if dest.is_symlink():
        try:
            if dest.resolve() == src.resolve():
                return "skip"
        except OSError:
            pass
        raise ValueError(f"{ERR_BRIDGE_FOREIGN}: {dest} → {dest.readlink()}; expected {src}")
    if dest.exists():
        # Non-empty local path blocks even when registry src is missing (preflight
        # runs before seed — never migrate/seed into a conflicted tree).
        if _path_is_empty_dir(dest):
            return "clear_link"
        raise ValueError(f"{ERR_BRIDGE_CONFLICT}: {dest} vs {src}")
    if src.exists():
        return "link"
    return "skip"


def ensure_bridge_gitignore(root: Path, context_rel: str = DEFAULT_CONTEXT) -> bool:
    root = root.resolve()
    gi = root / ".gitignore"
    patterns = [f"{context_rel}/{name}" for name in BRIDGE_NAMES]
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    existing = set(text.splitlines())
    missing = [p for p in patterns if p not in existing]
    if not missing:
        return False
    addition = BRIDGE_GITIGNORE_MARKER + "\n" + "\n".join(missing) + "\n"
    if text and not text.endswith("\n"):
        text = text + "\n"
    if text:
        text = text + "\n"
    gi.write_text(text + addition, encoding="utf-8")
    return True


def ensure_code_context_bridges(layout: ContextLayout) -> list[str]:
    if not layout.is_external:
        return []
    code = layout.code_context
    code.mkdir(parents=True, exist_ok=True)
    plan: list[tuple[str, Path, Path, str]] = []
    for name in BRIDGE_NAMES:
        src = layout.registry_root / name
        dest = code / name
        plan.append((name, src, dest, _bridge_preflight(src, dest)))
    created: list[str] = []
    for name, src, dest, action in plan:
        if action == "skip":
            continue
        if action == "clear_link":
            _clear_empty_bridge_dir(dest)
        dest.symlink_to(_bridge_link_target(src, dest))
        created.append(name)
    return list(created)


def prepare_connect_layout(
    root: Path,
    context_rel: str = DEFAULT_CONTEXT,
    *,
    bridges: bool = True,
) -> ContextLayout:
    ensure_layout_config(root, context_rel=context_rel)
    layout = resolve_layout(root, context_rel=context_rel)
    if layout.is_external:
        # Conflict check before seed — never leave a partial registry on conflict.
        preflight_bridge_conflicts(layout)
        ensure_external_registry_skeleton(layout)
        require_registry_ready(layout)
        if bridges:
            ensure_code_context_bridges(layout)
            ensure_bridge_gitignore(root, context_rel=context_rel)
    return layout


def external_context_gate(repo_root: Path, context_rel: str) -> dict[str, Any] | None:
    try:
        layout = resolve_layout(repo_root, context_rel)
    except ValueError as exc:
        msg = (
            "agent-env-check: REFUSED. External Project Context config is invalid "
            f"({exc}). Fix context/context.json. See {ENV_CHECK_DOC}."
        )
        return {
            "ok": False,
            "refused": True,
            "message": msg,
            "audience": "external-context",
        }
    if not layout.is_external:
        return None
    problems = external_clone_problems(layout)
    if not problems:
        return {
            "ok": True,
            "refused": False,
            "message": (
                f"agent-env-check: external Context OK at {layout.registry_root}"
                + (f" (remote={layout.remote})" if layout.remote else "")
            ),
            "audience": "external-context",
        }
    detail = "; ".join(problems)
    msg = (
        "agent-env-check: REFUSED. External Project Context clone is missing or incomplete "
        f"({detail}). Code repo and Context repo must both be present. "
        f"Clone `external.remote` to `external.path` from context/context.json. "
        f"See {ENV_CHECK_DOC}."
    )
    return {
        "ok": False,
        "refused": True,
        "message": msg,
        "audience": "external-context",
    }


def merge_external_result(result: dict[str, Any], ext: dict[str, Any] | None) -> dict[str, Any]:
    if not ext:
        return result
    if not ext.get("ok"):
        return ext
    result = dict(result)
    result["external_context"] = ext
    extra = ext.get("message")
    base_msg = result.get("message")
    if base_msg is None:
        base_msg = ""
    if extra and extra not in base_msg:
        result["message"] = base_msg + "\n" + extra
    return result


def apply_external_env_check(
    result: dict[str, Any],
    repo_root: Path,
    context_rel: str = DEFAULT_CONTEXT,
) -> dict[str, Any]:
    if not result.get("ok"):
        return result
    return merge_external_result(result, external_context_gate(repo_root, context_rel))


def _registry_label(root: Path, registry: Path) -> str:
    try:
        return registry.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(registry.resolve())


def session_nav_reminder(root: Path, context_rel: str = DEFAULT_CONTEXT) -> str:
    try:
        layout = resolve_layout(root, context_rel)
    except ValueError as exc:
        return (
            "Agentized session check:\n"
            f"- Project Context config error: {exc}\n"
            f"- Fix {context_rel}/context.json then re-run session."
        )
    label = _registry_label(root, layout.registry_root)
    nav = layout.nav_path()
    agents = root / "AGENTS.md"
    place = f"external → {label}" if layout.is_external else f"{context_rel}/"
    lines = [
        "Agentized session check:",
        f"- Project Context: {place}",
        f"- Read {label}/NAV.md first; follow only its links.",
        f"- Live board: {label}/tasks/INDEX.md (no full tasks/ listing).",
        f"- Leases warn-only: {label}/leases/INDEX.md",
    ]
    if not agents.exists():
        lines.append("WARN: AGENTS.md missing.")
    elif "NAV.md" not in agents.read_text(encoding="utf-8"):
        lines.append("WARN: AGENTS.md has no NAV.md pointer — run agentized connect.")
    if not nav.exists():
        lines.append(f"WARN: {label}/NAV.md missing.")
    else:
        lines.append(f"OK: {label}/NAV.md present.")
    return "\n".join(lines)


def session_lease_warn(
    root: Path,
    paths: list[str],
    *,
    ignore_task: str | None = None,
    context_rel: str = DEFAULT_CONTEXT,
) -> str:
    if not paths:
        return ""
    from .leases import find_overlaps, list_leases, warn_message

    try:
        layout = resolve_layout(root, context_rel)
    except ValueError as exc:
        return f"Project Context config error: {exc}"
    leases_dir = layout.leases_dir()
    if not leases_dir.exists():
        return ""
    overlaps = find_overlaps(list_leases(leases_dir), paths, ignore_task=ignore_task)
    return warn_message(overlaps)
