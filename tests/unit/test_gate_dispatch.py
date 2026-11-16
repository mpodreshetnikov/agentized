"""AGE-34 gate_dispatch helpers."""
from __future__ import annotations

from pathlib import Path

from agentized import gate_dispatch as gd


def test_language_for_path_exts():
    assert gd.language_for_path("src/a.py") == "python"
    assert gd.language_for_path("src/a.ts") == "typescript"
    assert gd.language_for_path("src/a.tsx") == "typescript"
    assert gd.language_for_path("src/a.js") == "javascript"
    assert gd.language_for_path("src/a.mjs") == "javascript"
    assert gd.language_for_path("src/a.cjs") == "javascript"
    assert gd.language_for_path("src/a.jsx") == "javascript"
    assert gd.language_for_path("pkg/types.d.ts") is None
    assert gd.language_for_path("README.md") is None
    assert gd.language_for_path("src/a.go") is None


def test_mutation_tool_for_language():
    assert gd.mutation_tool_for_language({"tools": {"python": "mutmut"}}, "python") == "mutmut"
    assert gd.mutation_tool_for_language({"tools": {"typescript": "stryker"}}, "typescript") == "stryker"
    assert gd.mutation_tool_for_language({"tool": "mutmut"}, "python") == "mutmut"
    assert gd.mutation_tool_for_language({"tool": "mutmut"}, "typescript") is None
    assert gd.mutation_tool_for_language({}, "python") is None


def test_architecture_tool_for_language():
    assert (
        gd.architecture_tool_for_language(
            {"tools": {"javascript": "dependency-cruiser"}}, "javascript"
        )
        == "dependency-cruiser"
    )
    assert gd.architecture_tool_for_language({"tool": "import-linter"}, "python") == "import-linter"
    assert gd.architecture_tool_for_language({"tool": "import-linter"}, "typescript") is None


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
