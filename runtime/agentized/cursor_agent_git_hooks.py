"""Wire Cursor Cloud agent-hooks dispatcher to this repo's `.githooks`.

Mechanism adapted from Orbit (T-261106-kp8 intent) — Agentized paths only.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

HOOK_NAMES = ("pre-commit", "pre-push", "commit-msg")


def agent_hooks_id(repo_root: Path) -> str:
    # Cursor Cloud strips base64 padding from the directory name.
    return base64.b64encode(str(repo_root.resolve()).encode("utf-8")).decode("ascii").rstrip("=")


def agent_hooks_dir(repo_root: Path, home: Path | None = None) -> Path:
    home = home or Path(os.path.expanduser("~"))
    return home / ".cursor" / "agent-hooks" / agent_hooks_id(repo_root)


def install(
    repo_root: Path,
    *,
    home: Path | None = None,
    hooks_dir: Path | None = None,
    githooks_dir: Path | None = None,
) -> dict:
    home = home or Path(os.path.expanduser("~"))
    hooks_dir = hooks_dir or agent_hooks_dir(repo_root, home)
    githooks_dir = githooks_dir or (repo_root / ".githooks")
    changed: list[str] = []
    if not hooks_dir.exists():
        return {
            "ok": False,
            "changed": changed,
            "message": (
                f"cursor-agent-git-hooks: {hooks_dir} does not exist yet "
                "(Cursor creates it). Nothing installed."
            ),
        }
    dispatcher = hooks_dir / ".dispatcher"
    if not dispatcher.exists():
        return {
            "ok": False,
            "changed": changed,
            "message": f"cursor-agent-git-hooks: {dispatcher} is missing; refusing to invent it.",
        }
    for name in HOOK_NAMES:
        tracked = githooks_dir / name
        if not tracked.exists():
            continue
        link = hooks_dir / name
        if not link.exists():
            link.symlink_to(".dispatcher")
            changed.append(f"symlink {name}")
    original_path_file = hooks_dir / ".cursor-original-hooks-path"
    wanted = str(githooks_dir.resolve())
    previous = ""
    if original_path_file.exists():
        previous = original_path_file.read_text(encoding="utf-8").strip()
    if previous != wanted:
        original_path_file.write_text(wanted + "\n", encoding="utf-8")
        changed.append(".cursor-original-hooks-path")
    return {
        "ok": True,
        "changed": changed,
        "message": (
            f"cursor-agent-git-hooks: {hooks_dir} already points at {wanted}."
            if not changed
            else f"cursor-agent-git-hooks: updated {hooks_dir} ({', '.join(changed)})."
        ),
    }


def git_hooks_problem(
    repo_root: Path,
    *,
    home: Path | None = None,
    hooks_dir: Path | None = None,
    githooks_dir: Path | None = None,
) -> str | None:
    home = home or Path(os.path.expanduser("~"))
    hooks_dir = hooks_dir or agent_hooks_dir(repo_root, home)
    githooks_dir = githooks_dir or (repo_root / ".githooks")
    if not (githooks_dir / "pre-push").exists():
        return None
    if not hooks_dir.exists():
        return f"{hooks_dir} is missing (Cursor agent-hooks not installed for this checkout)."
    for name in HOOK_NAMES:
        if not (githooks_dir / name).exists():
            continue
        if not (hooks_dir / name).exists():
            return f"{hooks_dir / name} is missing, so git never runs .githooks/{name}."
    original_file = hooks_dir / ".cursor-original-hooks-path"
    if not original_file.exists():
        return f"{hooks_dir}/.cursor-original-hooks-path is missing."
    original = original_file.read_text(encoding="utf-8").strip()
    wanted = str(githooks_dir.resolve())
    if Path(original).resolve() != Path(wanted).resolve():
        return (
            f"{hooks_dir}/.cursor-original-hooks-path is '{original}', not '{wanted}', "
            "so the tracked push gate does not run."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    import sys

    roots = [Path(p).resolve() for p in (argv or sys.argv[1:])] or [Path.cwd().resolve()]
    failed = False
    for root in roots:
        result = install(root)
        stream = sys.stdout if result["ok"] else sys.stderr
        stream.write(result["message"] + "\n")
        if not result["ok"]:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
