"""AGE-68 A-PR (b1): mutation oracles for skills/hooks pinning in ``connect``.

Tests-only; no runtime change. Targets survivors in ``pin_context_skills_hooks``.
Every oracle is the exact full value.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agentized.connect import pin_context_skills_hooks
from agentized.managed import load_managed, save_managed


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _shared(root: Path, skills: dict[str, str], hooks: dict[str, str]) -> None:
    shared = root / "packages" / "shared"
    (shared / "skills").mkdir(parents=True)
    (shared / "hooks" / "scripts").mkdir(parents=True)
    for rel, text in skills.items():
        path = shared / "skills" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel, text in hooks.items():
        (shared / "hooks" / "scripts" / rel).write_text(text, encoding="utf-8")


EMPTY_MANAGED: dict[str, list[str]] = {
    "created": [],
    "updated": [],
    "unchanged": [],
    "skipped_user": [],
    "bootstrapped": [],
}


def test_pin_skills_fresh_exact_result_and_files(tmp_path: Path):
    _shared(tmp_path, {"alpha/SKILL.md": "# alpha\n"}, {"hook_a.py": "print('a')\n"})
    result = pin_context_skills_hooks(tmp_path, "context")
    skill = tmp_path / "context" / "skills" / "alpha" / "SKILL.md"
    hook = tmp_path / "context" / "hooks" / "scripts" / "hook_a.py"
    assert result == {
        "skills": [str(skill)],
        "skills_managed": {**EMPTY_MANAGED, "created": [str(skill)]},
        "hooks": [str(hook)],
        "skipped_user": [],
    }
    assert skill.read_text(encoding="utf-8") == "# alpha\n"
    assert hook.read_text(encoding="utf-8") == "print('a')\n"


def test_pin_skills_saves_manifest_when_not_passed(tmp_path: Path):
    _shared(tmp_path, {"alpha/SKILL.md": "# alpha\n"}, {"hook_a.py": "x\n"})
    pin_context_skills_hooks(tmp_path, "context")
    saved = json.loads(
        (tmp_path / "context" / ".agentized" / "managed.json").read_text(encoding="utf-8")
    )
    assert saved == {
        "version": 1,
        "files": {"context/skills/alpha/SKILL.md": _sha("# alpha\n")},
    }


def test_pin_skills_passed_manifest_filled_not_saved(tmp_path: Path):
    _shared(tmp_path, {"alpha/SKILL.md": "# alpha\n"}, {"hook_a.py": "x\n"})
    man: dict[str, Any] = {"version": 1, "files": {}}
    pin_context_skills_hooks(tmp_path, "context", manifest=man)
    assert man == {
        "version": 1,
        "files": {"context/skills/alpha/SKILL.md": _sha("# alpha\n")},
    }
    assert (tmp_path / "context" / ".agentized" / "managed.json").exists() is False


def test_pin_skills_loads_existing_manifest(tmp_path: Path):
    _shared(tmp_path, {"alpha/SKILL.md": "# alpha\n"}, {})
    save_managed(tmp_path, "context", {"version": 1, "files": {"other": "h"}})
    pin_context_skills_hooks(tmp_path, "context")
    assert load_managed(tmp_path, "context")["files"] == {
        "context/skills/alpha/SKILL.md": _sha("# alpha\n"),
        "other": "h",
    }


def test_pin_skills_every_managed_status_and_ordering(tmp_path: Path):
    _shared(
        tmp_path,
        {
            "a/SKILL.md": "a-new\n",
            "b/SKILL.md": "b-new\n",
            "c/SKILL.md": "c\n",
            "d/SKILL.md": "d-src\n",
            "e/SKILL.md": "e-src\n",
        },
        {},
    )
    skills = tmp_path / "context" / "skills"
    for name, text in (("b", "b-old\n"), ("c", "c\n"), ("d", "d-user\n"), ("e", "e-user\n")):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(text, encoding="utf-8")
    save_managed(
        tmp_path,
        "context",
        {
            "version": 1,
            "files": {
                "context/skills/b/SKILL.md": _sha("b-old\n"),
                "context/skills/c/SKILL.md": _sha("c\n"),
                "context/skills/e/SKILL.md": _sha("e-orig\n"),
            },
        },
    )
    result = pin_context_skills_hooks(tmp_path, "context")
    a, b, c, d, e = (str(skills / n / "SKILL.md") for n in "abcde")
    assert result == {
        "skills": [a, b, c, d],
        "skills_managed": {
            "created": [a],
            "updated": [b],
            "unchanged": [c],
            "skipped_user": [e],
            "bootstrapped": [d],
        },
        "hooks": [],
        "skipped_user": [e],
    }
    assert (skills / "b" / "SKILL.md").read_text(encoding="utf-8") == "b-new\n"
    assert (skills / "d" / "SKILL.md").read_text(encoding="utf-8") == "d-user\n"
    assert (skills / "e" / "SKILL.md").read_text(encoding="utf-8") == "e-user\n"


def test_pin_skills_force_overwrites_user_edit(tmp_path: Path):
    _shared(tmp_path, {"e/SKILL.md": "e-src\n"}, {})
    skill = tmp_path / "context" / "skills" / "e" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("e-user\n", encoding="utf-8")
    save_managed(
        tmp_path, "context", {"version": 1, "files": {"context/skills/e/SKILL.md": _sha("orig\n")}}
    )
    result = pin_context_skills_hooks(tmp_path, "context", force=True)
    assert result["skills_managed"] == {**EMPTY_MANAGED, "updated": [str(skill)]}
    assert result["skipped_user"] == []
    assert skill.read_text(encoding="utf-8") == "e-src\n"


def test_pin_skills_hooks_always_overwritten_and_listed_sorted(tmp_path: Path):
    _shared(tmp_path, {}, {"b_hook.py": "b\n", "a_hook.py": "a-new\n"})
    scripts = tmp_path / "context" / "hooks" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "a_hook.py").write_text("a-user\n", encoding="utf-8")
    result = pin_context_skills_hooks(tmp_path, "context")
    assert sorted(result["hooks"]) == [str(scripts / "a_hook.py"), str(scripts / "b_hook.py")]
    assert (scripts / "a_hook.py").read_text(encoding="utf-8") == "a-new\n"
    assert (scripts / "b_hook.py").read_text(encoding="utf-8") == "b\n"
    assert result["skills"] == []
    assert result["skills_managed"] == EMPTY_MANAGED


def test_pin_skills_second_run_is_idempotent_and_dirs_exist(tmp_path: Path):
    _shared(tmp_path, {"alpha/SKILL.md": "# alpha\n"}, {"hook_a.py": "a\n"})
    pin_context_skills_hooks(tmp_path, "context")
    second = pin_context_skills_hooks(tmp_path, "context")
    skill = tmp_path / "context" / "skills" / "alpha" / "SKILL.md"
    assert second == {
        "skills": [str(skill)],
        "skills_managed": {**EMPTY_MANAGED, "unchanged": [str(skill)]},
        "hooks": [str(tmp_path / "context" / "hooks" / "scripts" / "hook_a.py")],
        "skipped_user": [],
    }


def test_pin_skills_nested_context_creates_parents(tmp_path: Path):
    _shared(tmp_path, {"alpha/SKILL.md": "# alpha\n"}, {"hook_a.py": "a\n"})
    result = pin_context_skills_hooks(tmp_path, "ctx/deep")
    skill = tmp_path / "ctx" / "deep" / "skills" / "alpha" / "SKILL.md"
    assert result["skills"] == [str(skill)]
    assert skill.read_text(encoding="utf-8") == "# alpha\n"
    assert (tmp_path / "ctx" / "deep" / "hooks" / "scripts" / "hook_a.py").is_file()
    assert (tmp_path / "ctx" / "deep" / ".agentized" / "managed.json").is_file()


def test_pin_skills_creates_empty_dirs_with_no_sources(tmp_path: Path):
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    result = pin_context_skills_hooks(tmp_path, "context")
    assert result == {
        "skills": [],
        "skills_managed": EMPTY_MANAGED,
        "hooks": [],
        "skipped_user": [],
    }
    assert (tmp_path / "context" / "skills").is_dir()
    assert (tmp_path / "context" / "hooks" / "scripts").is_dir()


def _names(path: Path) -> list[str]:
    return sorted(p.name for p in path.iterdir())


def test_pin_skills_gitkeep_removed_when_content_arrives(tmp_path: Path):
    _shared(tmp_path, {"alpha/SKILL.md": "# alpha\n"}, {"hook_a.py": "a\n"})
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True)
    (ctx / "hooks").mkdir(parents=True)
    (ctx / "skills" / ".gitkeep").write_text("", encoding="utf-8")
    (ctx / "hooks" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "skills") == ["alpha"]
    assert _names(ctx / "hooks") == ["scripts"]


def test_pin_skills_gitkeep_kept_without_content(tmp_path: Path):
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True)
    (ctx / "hooks").mkdir(parents=True)
    (ctx / "skills" / ".gitkeep").write_text("", encoding="utf-8")
    (ctx / "hooks" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "skills") == [".gitkeep"]
    assert _names(ctx / "hooks") == [".gitkeep", "scripts"]


def test_pin_skills_gitkeep_skills_removed_hooks_kept_when_only_skills(tmp_path: Path):
    _shared(tmp_path, {"alpha/SKILL.md": "# alpha\n"}, {})
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True)
    (ctx / "hooks").mkdir(parents=True)
    (ctx / "skills" / ".gitkeep").write_text("", encoding="utf-8")
    (ctx / "hooks" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "skills") == ["alpha"]
    assert _names(ctx / "hooks") == [".gitkeep", "scripts"]


def test_pin_skills_gitkeep_hooks_removed_skills_kept_when_only_hooks(tmp_path: Path):
    _shared(tmp_path, {}, {"hook_a.py": "a\n"})
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True)
    (ctx / "hooks").mkdir(parents=True)
    (ctx / "skills" / ".gitkeep").write_text("", encoding="utf-8")
    (ctx / "hooks" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "skills") == [".gitkeep"]
    assert _names(ctx / "hooks") == ["scripts"]


def test_pin_skills_gitkeep_preexisting_skill_entry_drops_skills_keep_only(tmp_path: Path):
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    ctx = tmp_path / "context"
    (ctx / "skills" / "odd" / "SKILL.md").mkdir(parents=True)
    (ctx / "hooks").mkdir(parents=True)
    (ctx / "skills" / ".gitkeep").write_text("", encoding="utf-8")
    (ctx / "hooks" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "skills") == ["odd"]
    assert _names(ctx / "hooks") == [".gitkeep", "scripts"]


def test_pin_skills_gitkeep_preexisting_script_entry_drops_hooks_keep_only(tmp_path: Path):
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True)
    (ctx / "hooks" / "scripts" / "pre").mkdir(parents=True)
    (ctx / "skills" / ".gitkeep").write_text("", encoding="utf-8")
    (ctx / "hooks" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "skills") == [".gitkeep"]
    assert _names(ctx / "hooks") == ["scripts"]


def test_pin_skills_skills_keep_untouched_by_hook_scripts_glob(tmp_path: Path):
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True)
    (ctx / "hooks" / "scripts" / "pre").mkdir(parents=True)
    (ctx / "skills" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "skills") == [".gitkeep"]


def test_pin_skills_hooks_keep_untouched_by_skill_glob(tmp_path: Path):
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    ctx = tmp_path / "context"
    (ctx / "skills" / "odd" / "SKILL.md").mkdir(parents=True)
    (ctx / "hooks").mkdir(parents=True)
    (ctx / "hooks" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "hooks") == [".gitkeep", "scripts"]


def test_pin_skills_gitkeep_with_only_nested_dir_in_hooks_is_kept(tmp_path: Path):
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True)
    (ctx / "hooks").mkdir(parents=True)
    (ctx / "hooks" / "extra").mkdir()
    (ctx / "hooks" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "hooks") == [".gitkeep", "extra", "scripts"]


def test_pin_skills_gitkeep_removed_when_other_file_beside_it(tmp_path: Path):
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True)
    (ctx / "hooks").mkdir(parents=True)
    (ctx / "skills" / "loose.txt").write_text("x", encoding="utf-8")
    (ctx / "hooks" / "loose.txt").write_text("x", encoding="utf-8")
    (ctx / "skills" / ".gitkeep").write_text("", encoding="utf-8")
    (ctx / "hooks" / ".gitkeep").write_text("", encoding="utf-8")
    pin_context_skills_hooks(tmp_path, "context")
    assert _names(ctx / "skills") == ["loose.txt"]
    assert _names(ctx / "hooks") == ["loose.txt", "scripts"]
