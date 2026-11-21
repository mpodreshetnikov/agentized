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
        "third_party/**",
        "**/dist/**",
        "**/build/**",
        "**/out/**",
        "**/.venv/**",
        "**/venv/**",
        "**/__pycache__/**",
        "**/.tox/**",
        "**/site-packages/**",
        "mutants/**",
        "coverage/**",
        "reports/**",
        "**/*.min.js",
        "**/generated/**",
        "**/.git/**",
        "**/target/**",
        "**/Pods/**",
        "packages/**",
        "templates/**",
        "**/*.example",
        "**/*.example.*",
        "**/*.example.cjs",
        "**/*.example.mjs",
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
