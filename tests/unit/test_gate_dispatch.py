from __future__ import annotations

from pathlib import Path

from agentized import gate_dispatch as gd


def test_dispatch_helpers(tmp_path: Path, monkeypatch):
    real_git = gd.git_changed_names
    assert len(gd._EXT_LANG) == 8
    assert gd._EXT_LANG[".py"] == "python" and gd._EXT_LANG[".tsx"] == "typescript"
    assert gd.MUTATION_TOOLS["python"] == frozenset({"mutmut"})
    assert gd.MUTATION_TOOLS["typescript"] == frozenset({"stryker"})
    assert "dependency-cruiser" in gd.ARCHITECTURE_TOOLS["javascript"]
    assert len(gd.DEFAULT_EXCLUDE_GLOBS) == 12
    assert gd.DEFAULT_EXCLUDE_GLOBS[0] == "**/node_modules/**"
    assert gd.DEFAULT_EXCLUDE_GLOBS[-1] == "**/*.example*"
    assert (
        "packages/**" not in gd.DEFAULT_EXCLUDE_GLOBS
        and "templates/**" not in gd.DEFAULT_EXCLUDE_GLOBS
    )
    assert gd.match_starstar("foo.test.ts", "**/*.test.ts")
    assert gd.match_starstar(r"src\a.test.ts", "**/*.test.ts")
    assert gd.match_starstar("src/a.ts", r"src\**\*.ts")
    assert gd.match_starstar("src/a.ts", "src/**/*.ts")
    assert not gd.match_starstar("", "x")
    assert not gd.match_starstar("", "*")
    assert not gd.match_starstar("foo", "*/**/foo")
    assert gd.match_starstar(r"src\nested\a.ts", "src/**/*.ts")
    assert gd.match_starstar(r"src\nested\a.ts", r"src\**\*.ts")
    assert not gd.match_starstar(r"other\a.ts", "src/**/*.ts")
    assert gd.match_starstar("src/__tests__/foo.ts", "**/__tests__/**/*.ts")
    assert gd.match_starstar("__tests__/foo.ts", "**/__tests__/**/*.ts")
    assert not gd.match_starstar("src/util.ts", "**/*.test.ts")
    vector = [
        ("src/a.py", "python"),
        ("src/A.PYI", "python"),
        ("src/a.tsx", "typescript"),
        ("src/a.mjs", "javascript"),
        ("pkg/types.d.ts", None),
        ("README.md", None),
        ("src/a.TsX", "typescript"),
    ]
    assert [(p, gd.language_for_path(p)) for p, _ in vector] == vector
    assert gd.mutation_tool_for_language({"tools": {"python": "MutMut"}}, "python") == "mutmut"
    assert gd.mutation_tool_for_language({"tool": "mutmut"}, "python") == "mutmut"
    assert gd.mutation_tool_for_language({"tool": "mutmut"}, "typescript") is None
    assert gd.mutation_tool_for_language({}, "python") is None
    assert (
        gd.architecture_tool_for_language(
            {"tools": {"javascript": "dependency-cruiser"}}, "javascript"
        )
        == "dependency-cruiser"
    )
    assert gd.architecture_tool_for_language({"tool": "builtin"}, "python") == "builtin"
    assert gd.architecture_tool_for_language({"tool": "mutmut"}, "python") is None
    assert gd.architecture_tool_for_language({}, "python") is None
    assert gd._glob_excluded("node_modules/x.js", ["**/node_modules/**"])
    assert gd._glob_excluded("tools/node_modules/x.js", ["**/node_modules/**"])
    assert gd._glob_excluded(r"node_modules\x.js", ["**/node_modules/**"])
    assert gd._glob_excluded("dist/a.js", ["**/dist/**"])
    assert gd._glob_excluded("foo/bar", ["**/bar"])
    assert gd._glob_excluded("node_modules", ["node_modules/**"])
    assert gd._glob_excluded(r"dist\a.js", ["**/dist/**"])
    assert not gd._glob_excluded("packages/x/y.ts", list(gd.DEFAULT_EXCLUDE_GLOBS))
    assert not gd._glob_excluded("src/a.ts", list(gd.DEFAULT_EXCLUDE_GLOBS))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "packages" / "app").mkdir(parents=True)
    (tmp_path / "packages" / "app" / "c.ts").write_text("export {}\n", encoding="utf-8")
    (tmp_path / "tools" / "node_modules").mkdir(parents=True)
    (tmp_path / "tools" / "node_modules" / "leftpad.js").write_text("1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("1\n", encoding="utf-8")
    found = gd.detect_languages(tmp_path, exclude_globs=list(gd.DEFAULT_EXCLUDE_GLOBS))
    assert sorted(found.keys()) == ["python", "typescript"]
    assert found["typescript"] == ["src/a.ts", "packages/app/c.ts"]
    assert found["python"] == ["src/b.py"]
    assert "tools/node_modules/leftpad.js" not in (found.get("javascript") or [])
    open_found = gd.detect_languages(tmp_path, exclude_globs=[])
    assert "javascript" in open_found and "node_modules/x.js" in open_found["javascript"]
    for i in range(10):
        (tmp_path / "src" / f"f{i}.py").write_text("x=1\n", encoding="utf-8")
    assert len(gd.detect_languages(tmp_path)["python"]) == 8
    assert gd.detect_languages(tmp_path / "missing") == {}
    expect = {
        "runtime/agentized/test_smells.py": False,
        "runtime/agentized/js_smells.py": False,
        "tests/unit/test_foo.py": True,
        "src/foo.test.ts": True,
        "src/__tests__/x.ts": True,
        "src/util.ts": False,
        "pkg/foo_test.py": True,
        "pkg/foo-test.js": True,
        "pkg/foo.spec.js": True,
        "lib/tests/helper.py": True,
        r"win\tests\a.py": True,
        "lib/test_only.py": True,
        "not_a_test.py": True,
        "prod.py": False,
    }
    assert {p: gd.is_test_path(p) for p in expect} == expect
    seen = []
    monkeypatch.setattr(
        gd,
        "git_changed_names",
        lambda root, base: (
            seen.append((root, base))
            or [
                "src/a.ts",
                "src/a.test.ts",
                "runtime/agentized/x.py",
                "tests/unit/t.py",
                "README.md",
                "src/nested/deep.ts",
                "other/x.ts",
            ]
        ),
    )
    assert gd.changed_source_files(tmp_path, "origin/main", ["src/", "runtime/agentized"]) == [
        "runtime/agentized/x.py",
        "src/a.ts",
        "src/nested/deep.ts",
    ]
    assert seen == [(tmp_path, "origin/main")]
    monkeypatch.setattr(gd, "git_changed_names", real_git)
    calls: list = []

    class R1:
        returncode, stdout, stderr = 1, "", "fail1"

    class R2:
        returncode, stdout, stderr = 0, r"src\a.py" + "\n", ""

    def fake_run(cmd, **k):
        calls.append(
            (list(cmd), k.get("cwd"), k.get("capture_output"), k.get("text"), k.get("check"))
        )
        return R1() if len(calls) == 1 else R2()

    monkeypatch.setattr(gd.subprocess, "run", fake_run)
    assert gd.git_changed_names(tmp_path, "origin/main") == ["src/a.py"]
    assert calls == [
        (
            ["git", "diff", "--name-only", "--diff-filter=ACMR", "origin/main...HEAD"],
            tmp_path,
            True,
            True,
            False,
        ),
        (
            ["git", "diff", "--name-only", "--diff-filter=ACMR", "origin/main"],
            tmp_path,
            True,
            True,
            False,
        ),
    ]

    class RFail:
        returncode, stdout, stderr = 2, "", "boom"

    monkeypatch.setattr(gd.subprocess, "run", lambda *a, **k: RFail())
    try:
        gd.git_changed_names(tmp_path, "origin/main")
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert exc.args == ("git diff failed",)
    assert gd.combine_gate_rc("warn", True, 7) == 7 and gd.combine_gate_rc("warn", False, 0) == 0
    assert gd.combine_gate_rc("hard", True, 0) == 1 and gd.combine_gate_rc("hard", False, 0) == 0
    assert gd.combine_gate_rc("hard", False, 3) == 3
