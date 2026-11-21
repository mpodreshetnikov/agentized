"""AGE-34 gate_dispatch helpers — pin constants + branch oracles."""
from __future__ import annotations

from pathlib import Path

from agentized import gate_dispatch as gd


def test_ext_lang_and_tool_maps_pinned():
    assert gd._EXT_LANG == {
        ".py": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
    }
    assert gd.MUTATION_TOOLS == {
        "python": frozenset({"mutmut"}),
        "javascript": frozenset({"stryker"}),
        "typescript": frozenset({"stryker"}),
    }
    assert gd.ARCHITECTURE_TOOLS == {
        "python": frozenset({"import-linter", "builtin"}),
        "javascript": frozenset({"dependency-cruiser", "eslint-boundaries"}),
        "typescript": frozenset({"dependency-cruiser", "eslint-boundaries"}),
    }
    assert gd.DEFAULT_EXCLUDE_GLOBS == (
        "node_modules/**",
        "vendor/**",
        "**/dist/**",
        "**/build/**",
        "**/.venv/**",
        "**/__pycache__/**",
        "mutants/**",
        "coverage/**",
        "reports/**",
        "**/*.min.js",
        "**/.git/**",
        "packages/**",
        "templates/**",
        "**/*.example",
        "**/*.example.*",
    )


def test_language_for_path_exts():
    vector = [
        ("src/a.py", "python"),
        ("src/A.PYI", "python"),
        ("src/a.ts", "typescript"),
        ("src/a.tsx", "typescript"),
        ("src/a.js", "javascript"),
        ("src/a.mjs", "javascript"),
        ("src/a.cjs", "javascript"),
        ("src/a.jsx", "javascript"),
        ("pkg/types.d.ts", None),
        ("README.md", None),
        ("src/a.go", None),
        (r"win\path\b.ts", "typescript"),
    ]
    assert [(p, gd.language_for_path(p)) for p, _ in vector] == vector


def test_mutation_tool_for_language():
    assert gd.mutation_tool_for_language({"tools": {"python": "MutMut"}}, "python") == "mutmut"
    assert (
        gd.mutation_tool_for_language({"tools": {"typescript": "stryker"}}, "typescript")
        == "stryker"
    )
    assert gd.mutation_tool_for_language({"tool": "mutmut"}, "python") == "mutmut"
    assert gd.mutation_tool_for_language({"tool": "mutmut"}, "typescript") is None
    assert gd.mutation_tool_for_language({"tool": ""}, "python") is None
    assert gd.mutation_tool_for_language({}, "python") is None
    assert gd.mutation_tool_for_language({"tools": {"python": ""}}, "python") is None


def test_architecture_tool_for_language():
    assert (
        gd.architecture_tool_for_language(
            {"tools": {"javascript": "dependency-cruiser"}}, "javascript"
        )
        == "dependency-cruiser"
    )
    assert gd.architecture_tool_for_language({"tool": "import-linter"}, "python") == "import-linter"
    assert gd.architecture_tool_for_language({"tool": "builtin"}, "python") == "builtin"
    assert gd.architecture_tool_for_language({"tool": "import-linter"}, "typescript") is None
    assert gd.architecture_tool_for_language({}, "python") is None


def test_glob_excluded_branches():
    assert gd._glob_excluded("node_modules/x.js", ["node_modules/**"]) is True
    assert gd._glob_excluded("dist/a.js", ["**/dist/**"]) is True
    assert gd._glob_excluded(r"vendor\x.js", ["vendor/**"]) is True
    assert gd._glob_excluded("pkg/foo.min.js", ["**/*.min.js"]) is True
    assert gd._glob_excluded("foo/bar", ["**/bar"]) is True  # **/ strip + fnmatch
    assert gd._glob_excluded("packages/x.py", ["packages/**"]) is True
    assert gd._glob_excluded("packages", ["packages/**"]) is True
    assert gd._glob_excluded("packages/x/y.py", ["packages/**"]) is True
    assert gd._glob_excluded("src/a.ts", ["packages/**"]) is False
    assert gd._glob_excluded("src/a.ts", []) is False


def test_detect_languages(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("1\n", encoding="utf-8")
    found = gd.detect_languages(tmp_path, exclude_globs=list(gd.DEFAULT_EXCLUDE_GLOBS))
    assert sorted(found.keys()) == ["python", "typescript"]
    assert found["typescript"] == ["src/a.ts"]
    assert found["python"] == ["src/b.py"]


def test_detect_languages_default_excludes_and_bucket_cap(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(10):
        (src / f"f{i}.py").write_text("x=1\n", encoding="utf-8")
    found = gd.detect_languages(tmp_path)  # uses DEFAULT_EXCLUDE_GLOBS
    assert len(found["python"]) == 8
    assert gd.detect_languages(tmp_path / "missing") == {}


def test_detect_languages_skips_non_files(tmp_path: Path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x=1\n", encoding="utf-8")

    real_relative = Path.relative_to

    def boom(self, other):
        if self.name == "bad.py":
            raise ValueError("outside")
        return real_relative(self, other)

    (tmp_path / "bad.py").write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr(Path, "relative_to", boom)
    found = gd.detect_languages(tmp_path, exclude_globs=[])
    assert "python" in found


def test_is_test_path_and_changed_sources(tmp_path: Path, monkeypatch):
    paths = [
        "runtime/agentized/test_smells.py",
        "runtime/agentized/js_smells.py",
        "tests/unit/test_foo.py",
        "src/foo.test.ts",
        "src/__tests__/x.ts",
        "src/util.ts",
        "pkg/foo_test.py",
        "pkg/foo-test.js",
        "pkg/foo.spec.js",
    ]
    assert [gd.is_test_path(p) for p in paths] == [
        False,
        False,
        True,
        True,
        True,
        False,
        True,
        True,
        True,
    ]
    monkeypatch.setattr(
        gd,
        "git_changed_names",
        lambda root, base: [
            "src/a.ts",
            "src/a.test.ts",
            "runtime/agentized/x.py",
            "tests/unit/t.py",
            "README.md",
        ],
    )
    assert gd.changed_source_files(tmp_path, "origin/main", ["src", "runtime/agentized"]) == [
        "runtime/agentized/x.py",
        "src/a.ts",
    ]


def test_git_changed_names_fallback_and_fail(tmp_path: Path, monkeypatch):
    n = {"i": 0}

    class R1:
        returncode = 1
        stdout = ""
        stderr = "fail1"

    class R2:
        returncode = 0
        stdout = "src/a.py\n"
        stderr = ""

    def fake_run(*a, **k):
        n["i"] += 1
        return R1() if n["i"] == 1 else R2()

    monkeypatch.setattr(gd.subprocess, "run", fake_run)
    assert gd.git_changed_names(tmp_path, "origin/main") == ["src/a.py"]

    class RFail:
        returncode = 2
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(gd.subprocess, "run", lambda *a, **k: RFail())
    try:
        gd.git_changed_names(tmp_path, "origin/main")
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert exc.code == 2
