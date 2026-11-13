from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import __version__
from .paths import (
    CONNECT_MARKER_BEGIN,
    CONNECT_MARKER_END,
    DEFAULT_CONTEXT,
    save_state,
)

AGENTS_BLOCK_TEMPLATE = """{begin}
## Project Context (Agentized)

- Путь к Project Context: [`{context}/`]({context}/).
- В начале сессии прочитай [`{context}/NAV.md`]({context}/NAV.md).
- Дальше иди **только** по ссылкам из `NAV.md` (не обходи каталоги Context наугад).
- Живой индекс задач: [`{context}/tasks/INDEX.md`]({context}/tasks/INDEX.md).
- Path leases (warn-only): [`{context}/leases/INDEX.md`]({context}/leases/INDEX.md).
- Runtime: `python3 runtime/agentized_cli.py` (см. `docs/morning-runbook.ru.md`).
{end}
"""

CLAUDE_BLOCK_TEMPLATE = """{begin}
## Agentized Project Context

- Context path: `{context}/`
- Session start: read `{context}/NAV.md`, then follow only its links.
- Live task board: `{context}/tasks/INDEX.md`
- Leases (warn-only): `{context}/leases/INDEX.md`
{end}
"""


def _upsert_marked_block(path: Path, begin: str, end: str, body: str, *, create: bool) -> bool:
    """Return True if file changed."""
    if not path.exists():
        if not create:
            return False
        path.write_text(body.rstrip() + "\n", encoding="utf-8")
        return True
    text = path.read_text(encoding="utf-8")
    if begin in text and end in text:
        pre = text.split(begin, 1)[0]
        post = text.split(end, 1)[1]
        new_text = pre.rstrip() + "\n\n" + body.rstrip() + "\n" + post.lstrip("\n")
        if not new_text.endswith("\n"):
            new_text += "\n"
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            return True
        return False
    # append
    new_text = text.rstrip() + "\n\n" + body.rstrip() + "\n"
    path.write_text(new_text, encoding="utf-8")
    return True


def _copy_tree(src: Path, dst: Path) -> list[str]:
    copied: list[str] = []
    if not src.exists():
        return copied
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied.append(str(target))
    return copied


def _repo_packages(root: Path) -> Path:
    return root / "packages"


def _shared_skills(root: Path) -> Path:
    return _repo_packages(root) / "shared" / "skills"


def _shared_hook_scripts(root: Path) -> Path:
    return _repo_packages(root) / "shared" / "hooks" / "scripts"


def pin_context_skills_hooks(root: Path, context_rel: str) -> dict:
    ctx = root / context_rel
    skills_dst = ctx / "skills"
    hooks_dst = ctx / "hooks"
    hooks_scripts = hooks_dst / "scripts"
    skills_dst.mkdir(parents=True, exist_ok=True)
    hooks_scripts.mkdir(parents=True, exist_ok=True)
    # remove stale .gitkeep once real content arrives
    for keep in (skills_dst / ".gitkeep", hooks_dst / ".gitkeep"):
        if keep.exists() and any(skills_dst.glob("*/SKILL.md") if keep.parent == skills_dst else hooks_scripts.glob("*")):
            keep.unlink()
    copied_skills = _copy_tree(_shared_skills(root), skills_dst)
    copied_hooks = _copy_tree(_shared_hook_scripts(root), hooks_scripts)
    # drop .gitkeep if content present
    for d in (skills_dst, hooks_dst):
        gk = d / ".gitkeep"
        if gk.exists() and any(p for p in d.rglob("*") if p != gk and p.is_file()):
            gk.unlink(missing_ok=True)
    return {"skills": copied_skills, "hooks": copied_hooks}


def install_cursor(root: Path, context_rel: str) -> dict:
    """Official project surfaces: .cursor/skills + .cursor/hooks.json (+ scripts)."""
    skills_src = root / context_rel / "skills"
    hooks_dir = root / ".cursor" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    cursor_skills = root / ".cursor" / "skills"
    copied = _copy_tree(skills_src, cursor_skills)
    # also keep plugin-shaped copy for --plugin-dir / local plugins
    plugin_src = _repo_packages(root) / "agentized-cursor"
    local_note = []
    if plugin_src.exists():
        # refresh plugin package skills/hooks from shared pinned
        _copy_tree(skills_src, plugin_src / "skills")
        _copy_tree(_shared_hook_scripts(root), plugin_src / "scripts")
        local_note.append(str(plugin_src))

    for name in ("session_start.py", "lease_warn.py"):
        src = root / context_rel / "hooks" / "scripts" / name
        if src.exists():
            shutil.copy2(src, hooks_dir / name)

    hooks_json = {
        "version": 1,
        "hooks": {
            "sessionStart": [
                {"command": ".cursor/hooks/session_start.py"}
            ],
            "preToolUse": [
                {
                    "command": ".cursor/hooks/lease_warn.py",
                    "matcher": "Write|Edit|Shell|Bash",
                }
            ],
            "afterFileEdit": [
                {"command": ".cursor/hooks/lease_warn.py"}
            ],
        },
    }
    hooks_path = root / ".cursor" / "hooks.json"
    hooks_path.write_text(json.dumps(hooks_json, indent=2) + "\n", encoding="utf-8")
    for script in hooks_dir.glob("*.py"):
        script.chmod(script.stat().st_mode | 0o111)
    return {
        "skills_copied": copied,
        "hooks_json": str(hooks_path),
        "plugin_path": local_note[0] if local_note else None,
        "local_plugin_hint": (
            "cp -R packages/agentized-cursor ~/.cursor/plugins/local/agentized "
            "или cursor-agent --plugin-dir packages/agentized-cursor"
        ),
    }


def install_claude(root: Path, context_rel: str) -> dict:
    """Official project surfaces: .claude/skills + .claude/settings.json hooks."""
    skills_src = root / context_rel / "skills"
    claude_dir = root / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    copied = _copy_tree(skills_src, claude_dir / "skills")
    for name in ("session_start.py", "lease_warn.py"):
        src = root / context_rel / "hooks" / "scripts" / name
        if src.exists():
            shutil.copy2(src, hooks_dir / name)
            (hooks_dir / name).chmod((hooks_dir / name).stat().st_mode | 0o111)

    plugin_src = _repo_packages(root) / "agentized-claude"
    if plugin_src.exists():
        _copy_tree(skills_src, plugin_src / "skills")
        _copy_tree(_shared_hook_scripts(root), plugin_src / "scripts")

    settings_path = claude_dir / "settings.json"
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            settings = {}
    hooks = settings.get("hooks") or {}
    hooks["SessionStart"] = [
        {
            "matcher": "startup|resume|clear|compact|fork",
            "hooks": [
                {
                    "type": "command",
                    "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_start.py\"",
                }
            ],
        }
    ]
    hooks["PreToolUse"] = [
        {
            "matcher": "Edit|Write|Bash",
            "hooks": [
                {
                    "type": "command",
                    "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/lease_warn.py\"",
                }
            ],
        }
    ]
    settings["hooks"] = hooks
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return {
        "skills_copied": copied,
        "settings": str(settings_path),
        "plugin_hint": "claude --plugin-dir packages/agentized-claude",
    }


def install_codex(root: Path, context_rel: str) -> dict:
    """Official project surfaces: .agents/skills + .codex/hooks.json.

    Codex has no stable --plugin-dir yet; local marketplace under .agents/plugins
    is the documented install path, plus project hooks.json.
    """
    skills_src = root / context_rel / "skills"
    agents_skills = root / ".agents" / "skills"
    copied = _copy_tree(skills_src, agents_skills)
    codex_hooks = root / ".codex" / "hooks"
    codex_hooks.mkdir(parents=True, exist_ok=True)
    for name in ("session_start.py", "lease_warn.py"):
        src = root / context_rel / "hooks" / "scripts" / name
        if src.exists():
            shutil.copy2(src, codex_hooks / name)
            (codex_hooks / name).chmod((codex_hooks / name).stat().st_mode | 0o111)

    plugin_src = _repo_packages(root) / "agentized-codex"
    if plugin_src.exists():
        _copy_tree(skills_src, plugin_src / "skills")
        _copy_tree(_shared_hook_scripts(root), plugin_src / "scripts")

    hooks_json = {
        "description": "Agentized project hooks (warn-only leases + NAV reminder).",
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact|fork",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/session_start.py"'
                            ),
                            "statusMessage": "Agentized NAV check",
                            "additionalContextLimit": 5000,
                        }
                    ],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Bash|apply_patch|Edit|Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/lease_warn.py"'
                            ),
                            "statusMessage": "Agentized lease warn",
                            "additionalContextLimit": 5000,
                        }
                    ],
                }
            ],
        },
    }
    hooks_path = root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(hooks_json, indent=2) + "\n", encoding="utf-8")

    # Official layout: $REPO/.agents/plugins/marketplace.json.
    # Marketplace root is the repository root; plugin path stays inside that root.
    marketplace = {
        "name": "agentized-local",
        "plugins": [
            {
                "name": "agentized",
                "source": {"source": "local", "path": "./packages/agentized-codex"},
                "category": "Productivity",
            }
        ],
    }
    market_path = root / ".agents" / "plugins" / "marketplace.json"
    market_path.parent.mkdir(parents=True, exist_ok=True)
    market_path.write_text(json.dumps(marketplace, indent=2) + "\n", encoding="utf-8")

    return {
        "skills_copied": copied,
        "hooks_json": str(hooks_path),
        "marketplace": str(market_path),
        "plugin_hint": (
            "codex plugin marketplace add . && "
            "codex plugin install agentized@agentized-local  "
            "(или пользуйтесь project .codex/hooks.json + .agents/skills после connect)"
        ),
        "gap": (
            "У Codex нет стабильного --plugin-dir; hooks плагина могут требовать trust. "
            "Connect пишет официальные project hooks в .codex/hooks.json."
        ),
    }


QUALITY_MARKER = "AGENTIZED:QUALITY"


def _safe_install_template(src: Path, dst: Path) -> str:
    """Install template when missing or still an Agentized quality-marked file. Never clobber others."""
    if not src.exists():
        return "missing-src"
    dst.parent.mkdir(parents=True, exist_ok=True)
    body = src.read_text(encoding="utf-8")
    if not dst.exists():
        dst.write_text(body, encoding="utf-8")
        if src.name == "pre-push":
            dst.chmod(dst.stat().st_mode | 0o111)
        return "created"
    existing = dst.read_text(encoding="utf-8")
    if QUALITY_MARKER in existing:
        if existing != body:
            dst.write_text(body, encoding="utf-8")
            if src.name == "pre-push":
                dst.chmod(dst.stat().st_mode | 0o111)
            return "updated"
        return "unchanged"
    return "skipped-user-file"


def pin_quality_templates(root: Path) -> dict:
    """Pin pre-push / CI from templates/quality (no clobber of unmarked user files)."""
    templates = root / "templates" / "quality"
    return {
        "pre_push": _safe_install_template(templates / "pre-push", root / ".githooks" / "pre-push"),
        "ci_workflow": _safe_install_template(
            templates / "ci.yml", root / ".github" / "workflows" / "ci.yml"
        ),
        "js_guidance": (templates / "stryker.config.mjs.example").exists(),
    }


def ensure_quality_config(root: Path, context_rel: str, coverage_pct: float | int | None = None) -> dict:
    from .quality import load_quality, save_quality, set_coverage_threshold, quality_path

    path = quality_path(root, context_rel)
    created = not path.exists()
    if created:
        save_quality(root, load_quality(root, context_rel), context_rel)
    if coverage_pct is not None:
        set_coverage_threshold(root, coverage_pct, context_rel=context_rel)
    return {"path": str(path.relative_to(root)), "created": created, "coverage_pct": coverage_pct}


def connect(
    root: Path,
    *,
    context_rel: str = DEFAULT_CONTEXT,
    harnesses: list[str] | None = None,
    coverage_pct: float | int | None = None,
) -> dict:
    harnesses = harnesses or ["cursor", "claude", "codex"]
    ctx = root / context_rel
    if not (ctx / "NAV.md").exists():
        raise FileNotFoundError(f"нет {context_rel}/NAV.md — сначала нужен skeleton Context")

    agents_body = AGENTS_BLOCK_TEMPLATE.format(
        begin=CONNECT_MARKER_BEGIN,
        end=CONNECT_MARKER_END,
        context=context_rel,
    )
    changed_agents = _upsert_marked_block(
        root / "AGENTS.md", CONNECT_MARKER_BEGIN, CONNECT_MARKER_END, agents_body, create=True
    )

    claude_md = root / "CLAUDE.md"
    changed_claude = False
    if claude_md.exists():
        claude_body = CLAUDE_BLOCK_TEMPLATE.format(
            begin=CONNECT_MARKER_BEGIN,
            end=CONNECT_MARKER_END,
            context=context_rel,
        )
        changed_claude = _upsert_marked_block(
            claude_md, CONNECT_MARKER_BEGIN, CONNECT_MARKER_END, claude_body, create=False
        )

    pinned = pin_context_skills_hooks(root, context_rel)
    quality = ensure_quality_config(root, context_rel, coverage_pct=coverage_pct)
    quality_templates = pin_quality_templates(root)
    results = {
        "pinned": pinned,
        "quality": quality,
        "quality_templates": quality_templates,
        "harnesses": {},
    }
    if "cursor" in harnesses:
        results["harnesses"]["cursor"] = install_cursor(root, context_rel)
    if "claude" in harnesses:
        results["harnesses"]["claude"] = install_claude(root, context_rel)
    if "codex" in harnesses:
        results["harnesses"]["codex"] = install_codex(root, context_rel)

    state = {
        "version": __version__,
        "context": context_rel,
        "harnesses": harnesses,
        "agents_md_updated": changed_agents,
        "claude_md_updated": changed_claude,
        "coverage_pct": coverage_pct,
    }
    save_state(root, state)
    results["state"] = state
    results["idempotent"] = not changed_agents and not changed_claude
    return results
