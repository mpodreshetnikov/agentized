"""Fail-closed language coverage (AGE-24 part a)."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentized.languages import (
    DEFAULT_EXCLUDE_GLOBS,
    SUPPORTED_GATES,
    _file_contains_any,
    _glob_excluded,
    _globs_cover,
    _module_has_lang,
    architecture_tool_for_language,
    check_language_coverage,
    default_languages_config,
    detect_languages,
    js_architecture_runner_present,
    js_ts_runners_verified,
    language_for_path,
    missing_gates_for_language,
    mutation_tool_for_language,
    stryker_runner_present,
    validate_supported_list,
)

def _excludes(*extra: str) -> list[str]:
    return list(DEFAULT_EXCLUDE_GLOBS) + list(extra)

_KEYS = {"ok", "detected", "unsupported", "missing_gates", "message", "skipped"}

def _shape(r: dict) -> dict:
    assert set(r) == _KEYS
    assert r["skipped"] is False
    assert isinstance(r["message"], str) and len(r["message"]) > 0
    return r

def _cfg(**overrides):
    base = {
        "languages": {"supported": ["python", "javascript", "typescript"], "exclude_globs": _excludes()},
        "modules": [{"id": "runtime", "source": ["src"], "test_command": "pytest", "coverage_lcov": "coverage/lcov.info"}],
        "mutation": {
            "enabled": True,
            "tools": {"python": "mutmut", "javascript": "stryker", "typescript": "stryker"},
            "include_globs": ["src/**/*.py", "src/**/*.ts", "src/**/*.js"],
        },
        "test_smells": {"enabled": True, "include_globs": ["tests/unit/**/*.py", "**/*.{test,spec}.{js,jsx,ts,tsx}"]},
        "architecture": {
            "enabled": True,
            "tools": {"python": "import-linter", "javascript": "dependency-cruiser", "typescript": "dependency-cruiser"},
            "config": ".importlinter", "js_config": ".dependency-cruiser.cjs",
        },
    }
    base.update(overrides)
    return base

def _runners(root: Path) -> None:
    d = root / "scripts" / "quality"
    d.mkdir(parents=True, exist_ok=True)
    (d / "stryker-runner").write_text("1\n", encoding="utf-8")
    (d / "architecture-runner").write_text("1\n", encoding="utf-8")
    (root / ".dependency-cruiser.cjs").write_text("module.exports = {}\n", encoding="utf-8")

def test_constants_and_language_for_path():
    assert SUPPORTED_GATES == ("tests", "coverage", "mutation", "smells", "architecture")
    assert "packages/**" not in DEFAULT_EXCLUDE_GLOBS
    assert "templates/**" not in DEFAULT_EXCLUDE_GLOBS
    cases = [
        ("a.py", "python"), ("a.pyi", "python"), ("a.ts", "typescript"), ("a.tsx", "typescript"),
        ("a.js", "javascript"), ("a.jsx", "javascript"), ("a.mjs", "javascript"), ("a.cjs", "javascript"),
        ("a.go", "go"), ("a.rs", "rust"), ("App.vue", "vue"), ("mix.ex", "elixir"),
        ("x.d.ts", None), ("src/x.D.TS", None), (".hidden.py", None), ("", None),
        ("readme.md", None), ("data.json", None), ("x.png", None), ("README", None),
        ("weird.qzz", "unknown"), ("dir\\a.py", "python"),
    ]
    assert [(r, language_for_path(r)) for r, _ in cases] == cases
    assert validate_supported_list(["python", "go"]) == ["go"]
    assert default_languages_config()["supported"] == ["python", "javascript", "typescript"]

def test_glob_excluded_and_globs_cover():
    cases = [
        ("vendor/x.py", ["vendor/**"], True), ("vendor", ["vendor/**"], True),
        ("src/x.py", ["vendor/**"], False), ("foo/bar.py", ["**/bar.py"], True),
        ("pkg/a/b.py", ["pkg/**/*.py"], True), ("pkg/a/b.ts", ["pkg/**/*.py"], False),
        ("x.py", ["*.py"], True), ("deep/x.py", ["*.py"], True),
        ("x.py", [""], False), ("a\\b.py", ["a/b.py"], True),
        ("directory/x.py", ["dir/**"], False),
        ("dir/file.py", ["dir/**"], True),
        ("a/**/*.x/b.py", ["a/**/*.x/**/*.py"], False),
    ]
    assert [(r, p, _glob_excluded(r, p)) for r, p, _ in cases] == cases
    assert _glob_excluded("nested/vendor/a.py", ["**/vendor/**"]) is True
    assert _glob_excluded("vendor", ["**/vendor/**"]) is True
    assert _glob_excluded("pkg/a/b.py", ["pkg/**/*.py"]) is True
    assert _glob_excluded("pkg/a/b.py", ["pkg/**/*.ts"]) is False
    assert _globs_cover([], "python") is False
    assert _globs_cover(["**/*.py"], "go") is False
    assert [_globs_cover(["**/*.py"], "go"), _globs_cover(["**/*.py"], "python")] == [False, True]
    assert _globs_cover(["**/*.{js,jsx}"], "javascript") is True
    assert _globs_cover(["**/*.json"], "javascript") is False
    assert _globs_cover(["src/**/*.ts"], "typescript") is True

def test_detect_excludes_and_caps(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
    for name in ("dist", "vendor"):
        (tmp_path / name).mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("1", encoding="utf-8")
    (tmp_path / "vendor" / "x.go").write_text("package x\n", encoding="utf-8")
    (tmp_path / "packages" / "shared").mkdir(parents=True)
    (tmp_path / "packages" / "shared" / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "templates" / "quality").mkdir(parents=True)
    (tmp_path / "templates" / "quality" / "x.js").write_text("1", encoding="utf-8")
    found = detect_languages(tmp_path, exclude_globs=_excludes())
    assert set(found) == {"python", "javascript"}
    assert set(found["python"]) == {"packages/shared/a.py", "src/a.py"}
    assert found["javascript"] == ["templates/quality/x.js"]
    dog = detect_languages(tmp_path, exclude_globs=_excludes("packages/**", "templates/**"))
    assert dog == {"python": ["src/a.py"]}
    with pytest.raises(ValueError, match="exclude_globs is required"):
        detect_languages(tmp_path, exclude_globs=None)
    assert detect_languages(tmp_path / "nope", exclude_globs=_excludes()) == {}
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "weird.qzz").write_text("x", encoding="utf-8")
    found = detect_languages(tmp_path, exclude_globs=_excludes("packages/**", "templates/**", "src/**", "dist/**", "vendor/**"))
    assert len(found["python"]) == 8 and found["unknown"] == ["weird.qzz"]

def test_module_has_lang_and_file_contains(tmp_path: Path):
    (tmp_path / "types.d.ts").write_text("export {}\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("x=1\n", encoding="utf-8")
    assert [
        _module_has_lang(tmp_path, {"source": ["types.d.ts"]}, "typescript"),
        _module_has_lang(tmp_path, {"source": ["missing-dir"]}, "python"),
        _module_has_lang(tmp_path, {"source": ["app.py"]}, "python"),
    ] == [False, False, True]
    d = tmp_path / "src"
    d.mkdir()
    (d / "b.d.ts").write_text("export {}\n", encoding="utf-8")
    assert _module_has_lang(tmp_path, {"source": ["src"]}, "typescript") is False
    (d / "aaa").mkdir()
    (d / "zzz.ts").write_text("export {}\n", encoding="utf-8")
    assert _module_has_lang(tmp_path, {"source": ["src"]}, "typescript") is True
    assert _file_contains_any(tmp_path / "missing.py", ("x",)) is False
    p = tmp_path / "f.txt"
    p.write_text("alpha beta gamma", encoding="utf-8")
    assert _file_contains_any(p, ("nope", "beta")) is True
    assert _file_contains_any(p, ("nope", "zzz")) is False

def test_runners_and_js_ts_verified(tmp_path: Path):
    assert [stryker_runner_present(tmp_path), js_architecture_runner_present(tmp_path)] == [False, False]
    path = tmp_path / "scripts" / "quality" / "run-mutation-js.cjs"
    path.parent.mkdir(parents=True)
    path.write_text("// stryker wrapper\n", encoding="utf-8")
    assert stryker_runner_present(tmp_path) is True
    assert js_architecture_runner_present(tmp_path) is False
    mut = tmp_path / "agentized" / "mutation.py"
    mut.parent.mkdir(parents=True)
    mut.write_text("def _run_stryker_gate():\n    return 0\n", encoding="utf-8")
    arch = tmp_path / "agentized" / "architecture_gate.py"
    arch.write_text("def _run_dependency_cruiser(a, b):\n    return 0, ''\n", encoding="utf-8")
    assert [stryker_runner_present(tmp_path), js_architecture_runner_present(tmp_path)] == [True, True]
    _runners(tmp_path)
    cfg_ok = {
        "mutation": {"tools": {"typescript": "stryker"}},
        "architecture": {
            "tools": {"typescript": "dependency-cruiser"},
            "js_config": ".dependency-cruiser.cjs",
        },
    }
    assert [
        js_ts_runners_verified(tmp_path, "python", {}),
        js_ts_runners_verified(tmp_path, "typescript", {"mutation": {}}),
        js_ts_runners_verified(tmp_path, "typescript", {"mutation": None}),
        js_ts_runners_verified(
            tmp_path, "typescript",
            {"mutation": {"tools": {"typescript": "stryker"}},
             "architecture": {"tools": {"typescript": "dependency-cruiser"}}},
        ),
        js_ts_runners_verified(tmp_path, "typescript", cfg_ok),
        js_ts_runners_verified(
            tmp_path, "typescript",
            {"mutation": {"tools": {"typescript": "stryker"}},
             "architecture": {"tools": {"typescript": "unknown-tool"}}},
        ),
        js_ts_runners_verified(
            tmp_path, "typescript",
            {"mutation": {"tools": {"typescript": "stryker"}}, "architecture": None},
        ),
    ] == [True, False, False, False, True, False, False]
    _runners(tmp_path)
    assert js_ts_runners_verified(
        tmp_path, "javascript",
        {"mutation": {"tools": {"javascript": "stryker"}},
         "architecture": {"tools": {"javascript": "dependency-cruiser"}, "config": ".dependency-cruiser.cjs"}},
    ) is True
    assert js_ts_runners_verified(
        tmp_path, "javascript",
        {"mutation": {"tools": {"javascript": "stryker"}},
         "architecture": {"tools": {"javascript": "dependency-cruiser"}}},
    ) is False
    assert mutation_tool_for_language({"tool": ""}, "python") is None
    assert mutation_tool_for_language({"tools": {"python": "mutmut"}}, "python") == "mutmut"
    assert architecture_tool_for_language({"tools": {"python": "import-linter"}}, "python") == "import-linter"

def test_missing_gates_matrix(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x=1\n", encoding="utf-8")
    (src / "a.js").write_text("export {}\n", encoding="utf-8")
    assert missing_gates_for_language(tmp_path, "python", _cfg(test_smells={"enabled": False}, architecture={"enabled": False})) == ["smells", "architecture"]
    assert missing_gates_for_language(tmp_path, "python", _cfg(mutation={"enabled": True, "tools": {"python": "mutmut"}, "include_globs": []})) == ["mutation"]
    cfg = _cfg(test_smells={"enabled": True, "include_globs": []})
    assert "smells" in missing_gates_for_language(tmp_path, "python", cfg)
    cfg2 = _cfg(test_smells={"enabled": True, "include_globs": ["**/*.ts"]})
    assert "smells" in missing_gates_for_language(tmp_path, "python", cfg2)
    bad_js = _cfg(
        modules=[{"id": "web", "source": ["src"], "test_command": "vitest", "coverage_lcov": "c.lcov"}],
        mutation={"enabled": True, "tools": {"javascript": "stryker"}, "include_globs": ["**/*.py"]},
        test_smells={"enabled": True, "include_globs": ["**/*.py"]},
        architecture={"enabled": True, "tools": {"javascript": "dependency-cruiser"}, "js_config": ".dependency-cruiser.cjs"},
    )
    miss = missing_gates_for_language(tmp_path, "javascript", bad_js)
    assert "mutation" in miss and "smells" in miss

    # coverage_json + builtin arch; js arch via config key
    cfg3 = {
        "modules": [{"id": "r", "source": ["src"], "test_command": "pytest", "coverage_json": "c.json"}],
        "mutation": {"tools": {"python": "mutmut"}, "include_globs": ["**/*.py"]},
        "test_smells": {"enabled": True, "include_globs": ["**/*.py"]},
        "architecture": {"enabled": True, "tools": {"python": "builtin"}},
    }
    assert missing_gates_for_language(tmp_path, "python", cfg3) == []

def test_check_coverage_refuses(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "src" / "a.go").write_text("package main\n", encoding="utf-8")
    r = check_language_coverage(tmp_path, cfg=_cfg(languages={"supported": ["python"], "exclude_globs": _excludes(), "detect": False}))
    _shape(r)
    assert r["ok"] is False and "detect=false" in r["message"] and r["detected"] == {}
    r = check_language_coverage(tmp_path, cfg=_cfg(languages={"supported": [], "exclude_globs": _excludes()}))
    _shape(r)
    assert r["ok"] is False and "supported is missing or empty" in r["message"]
    r = check_language_coverage(tmp_path, cfg=_cfg(languages={"supported": ["python"], "exclude_globs": []}))
    _shape(r)
    assert r["ok"] is False and "exclude_globs is missing or empty" in r["message"]
    r = check_language_coverage(tmp_path, cfg=_cfg(languages={"supported": ["python", "go"], "exclude_globs": _excludes()}))
    _shape(r)
    assert r["ok"] is False and r["unsupported"] == ["go"]
    r = check_language_coverage(tmp_path, cfg=_cfg(languages={"supported": ["python"], "exclude_globs": _excludes()}))
    _shape(r)
    assert r["ok"] is False and "go" in r["unsupported"]
    r = check_language_coverage(tmp_path, cfg=_cfg(languages={"supported": None, "exclude_globs": _excludes()}))
    _shape(r)
    assert r["ok"] is False
    r = check_language_coverage(tmp_path, cfg=_cfg(languages={"supported": ["python"], "exclude_globs": None}))
    _shape(r)
    assert r["ok"] is False

def test_check_coverage_missing_gates_and_ok(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
    r = check_language_coverage(
        tmp_path, cfg=_cfg(languages={"supported": ["python"], "exclude_globs": _excludes()}, modules=[]),
        require_gates=False,
    )
    _shape(r)
    assert r["ok"] is True and r["missing_gates"] == {} and "python" in r["message"]
    (tmp_path / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    r = check_language_coverage(tmp_path, cfg=_cfg(languages={"supported": ["python", "typescript"], "exclude_globs": _excludes()}))
    _shape(r)
    assert r["ok"] is False and "typescript" in r["missing_gates"]
    # python ok with full gates
    r = check_language_coverage(
        tmp_path,
        cfg=_cfg(languages={"supported": ["python"], "exclude_globs": _excludes("**/*.ts", "**/*.tsx", "**/*.js")}),
    )
    _shape(r)
    assert r["ok"] is True and r["message"] == "language coverage OK: python"
    # js ok only with runners
    _runners(tmp_path)
    (tmp_path / "src" / "a.js").write_text("export const x = 1\n", encoding="utf-8")
    r = check_language_coverage(
        tmp_path,
        cfg=_cfg(
            languages={"supported": ["javascript"], "exclude_globs": _excludes("**/*.py", "**/*.ts")},
            modules=[{"id": "web", "source": ["src"], "test_command": "vitest", "coverage_lcov": "coverage/lcov.info"}],
            mutation={"enabled": True, "tools": {"javascript": "stryker"}, "include_globs": ["src/**/*.js"]},
        ),
    )
    _shape(r)
    assert r["ok"] is True and r["detected"] == {"javascript": ["src/a.js"]}
    # ts single-file module + eslint-boundaries
    app = tmp_path / "app.ts"
    app.write_text("export {}\n", encoding="utf-8")
    r = check_language_coverage(
        tmp_path,
        cfg=_cfg(
            languages={"supported": ["typescript"], "exclude_globs": _excludes("src/**", "**/*.js", "**/*.py")},
            modules=[{"id": "onefile", "source": ["app.ts"], "test_command": "vitest", "coverage_lcov": "c.lcov"}],
            mutation={"enabled": True, "tools": {"typescript": "stryker"}, "include_globs": ["**/*.ts"]},
            architecture={"enabled": True, "tools": {"typescript": "eslint-boundaries"}},
        ),
    )
    _shape(r)
    assert r["ok"] is True and r["detected"] == {"typescript": ["app.ts"]}
    from agentized.quality import save_quality
    save_quality(tmp_path, _cfg(languages={"supported": ["python"], "exclude_globs": _excludes("**/*.ts", "**/*.js", "**/*.tsx")}))
    r = check_language_coverage(tmp_path)
    _shape(r)
    assert r["ok"] is True and r["message"] == "language coverage OK: python"

def test_single_tool_and_oserror_branches(tmp_path: Path, monkeypatch):
    assert mutation_tool_for_language({"tool": "mutmut"}, "python") == "mutmut"
    assert mutation_tool_for_language({"tool": "stryker"}, "python") is None
    assert architecture_tool_for_language({"tool": "import-linter"}, "python") == "import-linter"
    assert architecture_tool_for_language({"tool": "nope"}, "python") is None
    # file module wrong ext continues
    (tmp_path / "a.js").write_text("1\n", encoding="utf-8")
    assert _module_has_lang(tmp_path, {"source": ["a.js"]}, "python") is False
    # OSError on read
    target = tmp_path / "blocked.txt"
    target.write_text("marker-here", encoding="utf-8")
    real = Path.read_bytes
    def boom(self, *a, **k):
        if self == target:
            raise OSError("blocked")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_bytes", boom)
    assert _file_contains_any(target, ("marker",)) is False
    # js runner present but architecture runner missing → verified false
    scripts = tmp_path / "scripts" / "quality"
    scripts.mkdir(parents=True)
    (scripts / "stryker-runner").write_text("1\n", encoding="utf-8")
    cfg = {
        "mutation": {"tools": {"javascript": "stryker"}},
        "architecture": {
            "tools": {"javascript": "dependency-cruiser"},
            "js_config": ".dependency-cruiser.cjs",
        },
    }
    assert js_ts_runners_verified(tmp_path, "javascript", cfg) is False
    # covering modules missing test_command / coverage
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
    miss = missing_gates_for_language(
        tmp_path,
        "python",
        {
            "modules": [{"id": "x", "source": ["src"]}],
            "mutation": {"enabled": True, "tools": {"python": "mutmut"}, "include_globs": ["**/*.py"]},
            "test_smells": {"enabled": True, "include_globs": ["**/*.py"]},
            "architecture": {"enabled": True, "tools": {"python": "builtin"}},
        },
    )
    assert miss[:2] == ["tests", "coverage"]

def test_check_non_dict_languages(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
    r = check_language_coverage(
        tmp_path,
        cfg={"languages": ["not-a-dict"], "modules": [], "mutation": {}, "test_smells": {}, "architecture": {}},
    )
    _shape(r)
    assert r["ok"] is False and "supported is missing or empty" in r["message"]

def test_runner_paths_isolated(tmp_path: Path):
    assert [stryker_runner_present(tmp_path), js_architecture_runner_present(tmp_path)] == [False, False]
    for rel, body, check in (
        ("runtime/agentized/mutation.py", "def _run_stryker_gate():\n    return 0\n", stryker_runner_present),
        ("agentized/mutation.py", "def _run_stryker_gate():\n    return 0\n", stryker_runner_present),
        ("runtime/agentized/architecture_gate.py", "def _run_dependency_cruiser(a, b):\n    return 0, ''\n", js_architecture_runner_present),
        ("agentized/architecture_gate.py", "def _run_eslint_boundaries():\n    return 0\n", js_architecture_runner_present),
        ("scripts/quality/run-architecture-js.cjs", "1\n", js_architecture_runner_present),
        ("run-mutation-js.cjs", "1\n", stryker_runner_present),
    ):
        path = tmp_path.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        assert check(tmp_path) is True
        path.unlink()
    assert language_for_path("foo.bar.py") == "python"
    assert language_for_path("file.backup.md") is None

def test_survivor_killers(tmp_path: Path, monkeypatch):
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x=1\n", encoding="utf-8")
    real_rel, n = Path.relative_to, {"i": 0}

    def boom(self, other):
        n["i"] += 1
        if n["i"] == 1:
            raise ValueError("skip")
        return real_rel(self, other)

    monkeypatch.setattr(Path, "relative_to", boom)
    found_py = detect_languages(tmp_path, exclude_globs=_excludes()).get("python") or []
    assert len(found_py) == 1 and found_py[0] in {"a.py", "b.py"}
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
    assert missing_gates_for_language(
        tmp_path, "python", _cfg(architecture={"enabled": False, "tools": {"python": "import-linter"}, "config": ".importlinter"}),
    ) == ["architecture"]
    assert "architecture" in missing_gates_for_language(
        tmp_path, "python",
        _cfg(architecture={"enabled": True, "tools": {"python": "nope"}, "config": ".importlinter"}),
    )
    (tmp_path / "src" / "a.js").write_text("export {}\n", encoding="utf-8")
    r = check_language_coverage(
        tmp_path, cfg=_cfg(languages={"supported": ["python"], "exclude_globs": _excludes()}),
    )
    assert r["unsupported"] == ["javascript"] and r["missing_gates"] == {}
    _runners(tmp_path)
    js_ok = {
        "modules": [{"id": "w", "source": ["src"], "test_command": "vitest", "coverage_lcov": "c.lcov"}],
        "mutation": {"tools": {"javascript": "stryker"}, "include_globs": ["**/*.js"]},
        "test_smells": {"enabled": True, "include_globs": ["**/*.js"]},
        "architecture": {
            "enabled": True, "tools": {"javascript": "dependency-cruiser"},
            "js_config": ".dependency-cruiser.cjs",
        },
    }
    assert "architecture" not in missing_gates_for_language(tmp_path, "javascript", js_ok)
    assert missing_gates_for_language(
        tmp_path, "javascript",
        {**js_ok, "architecture": {"enabled": True, "tools": {"javascript": "dependency-cruiser"}}},
    ) == ["architecture", "mutation"]
    from agentized.quality import save_quality
    alt = "ctx-alt"
    (tmp_path / alt).mkdir()
    save_quality(
        tmp_path, _cfg(languages={"supported": ["python"], "exclude_globs": _excludes("**/*.js")}),
        context_rel=alt,
    )
    r = check_language_coverage(tmp_path, context=alt)
    _shape(r)
    assert r["ok"] is True and r["message"] == "language coverage OK: python"
    bad = {
        "modules": [{"id": "r", "source": ["src"], "test_command": "pytest", "coverage_lcov": "c.lcov"}],
        "mutation": "bad", "test_smells": "bad", "architecture": "bad",
    }
    assert missing_gates_for_language(tmp_path, "python", bad) == ["mutation", "smells", "architecture"]
