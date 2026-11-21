"""AGE-31 layer gates — real quality.json trees (no mocked load_quality)."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentized import layer_gates as lg
from agentized.quality import default_quality_config, save_quality
from agentized.quality_defaults import default_quality_config as defaults_fn

def _ensure_mini_app(root: Path) -> Path:
    """Minimal playwright + db/tests tree for layer-gate oracles."""
    app = root / "app"
    (app / "src").mkdir(parents=True)
    (app / "src" / "app.ts").write_text("export {}\n", encoding="utf-8")
    (app / "e2e").mkdir()
    (app / "e2e" / "smoke.spec.ts").write_text("test('s', async () => {})\n", encoding="utf-8")
    (app / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (app / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "1.0.0"}}), encoding="utf-8"
    )
    mig = app / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001_init.sql").write_text("CREATE TABLE t(id int);\n", encoding="utf-8")
    tests = app / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_init.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    return app


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=root, check=True, capture_output=True
    )


def _commit_all(root: Path, msg: str = "chg") -> str:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", msg, "--allow-empty"], cwd=root, check=True, capture_output=True
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write_quality(root: Path, **section_overrides: object) -> None:
    cfg = default_quality_config()
    cfg["modules"] = []
    for key, value in section_overrides.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    save_quality(root, cfg)


def _summary(root: Path, gate: str) -> dict:
    return json.loads((root / "reports" / gate / f"{gate}-summary.json").read_text(encoding="utf-8"))


def _decision(*, days: int = 7, approved_by: str = "Maxim") -> dict:
    return {
        "reason": "temporary migration",
        "approved_by": approved_by,
        "expires": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
    }


def _pw_tree(root: Path) -> None:
    (root / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (root / "e2e").mkdir(exist_ok=True)
    (root / "e2e" / "a.spec.ts").write_text("test('a', async () => {})\n", encoding="utf-8")


def test_detect_e2e_and_absent(tmp_path: Path):
    _pw_tree(tmp_path)
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "1.0.0"}}), encoding="utf-8"
    )
    det = lg.detect_e2e(tmp_path, skip_prefixes=())
    assert sorted({e["kind"] for e in det["evidence"]}) == ["config", "package_dep", "tests_dir"]
    assert det["framework"] == "playwright" and det["present"] is True
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "README.md").write_text("x\n", encoding="utf-8")
    assert lg.detect_e2e(empty, skip_prefixes=())["evidence"] == []


def test_detect_db_and_nested_orm(tmp_path: Path):
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE t(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_t.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    det = lg.detect_db_layer(tmp_path, skip_prefixes=())
    assert "migrations_dir" in {e["kind"] for e in det["evidence"]}
    assert det["framework"] in {"pgtap", "sql"}
    mono = tmp_path / "mono"
    (mono / "apps" / "web").mkdir(parents=True)
    (mono / "apps" / "web" / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (mono / "apps" / "web" / "e2e").mkdir()
    (mono / "apps" / "web" / "e2e" / "h.spec.ts").write_text("test('h', async () => {})\n", encoding="utf-8")
    (mono / "services" / "api" / "db" / "migrations").mkdir(parents=True)
    (mono / "services" / "api" / "db" / "migrations" / "001.sql").write_text("SELECT 1;\n", encoding="utf-8")
    assert lg.detect_e2e(mono, skip_prefixes=())["present"] is True
    assert any("services/api/db/migrations" in e.get("path", "") for e in lg.detect_db_layer(mono, skip_prefixes=())["evidence"])
    orm = tmp_path / "orm"
    orm.mkdir()
    (orm / "package.json").write_text(json.dumps({"dependencies": {"prisma": "5"}}), encoding="utf-8")
    (orm / "db" / "tests").mkdir(parents=True)
    (orm / "db" / "tests" / "t.sql").write_text("SELECT 1;\n", encoding="utf-8")
    assert lg.detect_db_layer(orm, skip_prefixes=())["framework"] == "prisma"


def test_skip_prefixes_agentized_only(tmp_path: Path):
    (tmp_path / "templates" / "e2e").mkdir(parents=True)
    (tmp_path / "templates" / "e2e" / "a.spec.ts").write_text("test('a')\n", encoding="utf-8")
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    assert lg.is_agentized_repo(tmp_path) is False
    assert lg.skip_rel_prefixes(tmp_path) == ()
    assert lg.detect_e2e(tmp_path)["present"] is True
    (tmp_path / "runtime" / "agentized").mkdir(parents=True)
    (tmp_path / "templates" / "quality").mkdir(parents=True)
    assert lg.skip_rel_prefixes(tmp_path) == ("templates/", "tests/fixtures/")
    assert lg.skip_rel_prefixes(tmp_path, {"skip_rel_prefixes": ["vendor/"]}) == ("vendor/",)


def test_disable_decision_rules():
    assert lg.DISABLE_DECISION_MAX_DAYS == 14
    clock = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = {"reason": "pause", "approved_by": "Maxim"}
    assert lg.disable_decision_valid(
        {"disable_decision": {**base, "expires": (clock + timedelta(days=14)).isoformat()}}, now=clock
    ) is True
    assert lg.disable_decision_valid(
        {"disable_decision": {**base, "expires": (clock + timedelta(days=14, seconds=1)).isoformat()}},
        now=clock,
    ) is False
    assert lg.disable_decision_valid(
        {"disable_decision": {**base, "expires": (clock + timedelta(milliseconds=500)).isoformat()}},
        now=clock,
    ) is True
    assert lg.disable_decision_valid(
        {"disable_decision": {**base, "expires": clock.isoformat()}}, now=clock
    ) is False
    exp = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    assert lg.disable_decision_valid({"disable_decision": {"approved_by": "Maxim", "expires": exp}}) is False
    assert lg.disable_decision_valid({"disable_decision": {"reason": "", "approved_by": "Maxim", "expires": exp}}) is False
    assert lg.disable_decision_valid({"disable_decision": {"reason": "x", "approved_by": "", "expires": exp}}) is False
    assert lg.disable_decision_valid({"disable_decision": {"reason": "x", "approved_by": "Maxim", "expires": 1}}) is False
    assert lg.disable_decision_valid({"disable_decision": "nope"}) is False
    assert lg.disable_decision_valid({}) is False
    assert lg.disable_decision_valid(
        {"disable_decision": {**base, "expires": "2026-01-08T00:00:00"}}, now=clock
    ) is False
    assert lg.disable_decision_valid(
        {"disable_decision": {**base, "expires": "not-a-date"}}, now=clock
    ) is False
    assert lg.disable_decision_valid(
        {"disable_decision": {**base, "expires": "2026-01-08T00:00:00+00:00"}}, now=datetime(2026, 1, 1)
    ) is False
    # now=None uses utc clock; naive now rejected.
    assert lg.disable_decision_valid(
        {"disable_decision": {**base, "expires": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}},
        now=None,
    ) is True


def test_e2e_disabled_requires_decision(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    _pw_tree(tmp_path)
    _write_quality(tmp_path, e2e={"enabled": False, "mode": "hard", "test_command": "true"})
    _commit_all(tmp_path, "init")
    monkeypatch.delenv("LAYER_GATES_BASE", raising=False)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(f["kind"] == "disabled_without_decision" for f in _summary(tmp_path, "e2e")["findings"])
    _write_quality(tmp_path, e2e={"enabled": False, "mode": "hard", "disable_decision": _decision()})
    assert lg.run_e2e_gate(tmp_path) == 0
    assert _summary(tmp_path, "e2e")["reason"] == "disabled_by_decision"


def test_red_commands_and_require_false(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    _pw_tree(tmp_path)
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto", "mode": "hard", "source_globs": ["src/**"],
            "test_globs": ["e2e/**"], "test_command": "false",
        },
    )
    base = _commit_all(tmp_path, "base")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(f["kind"] == "test_command_failed" for f in _summary(tmp_path, "e2e")["findings"])
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "t.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        db_tests={
            "enabled": "auto", "mode": "hard", "source_globs": ["**/migrations/**"],
            "test_globs": ["**/db/tests/**"], "test_command": "exit 1",
        },
    )
    base2 = _commit_all(tmp_path, "db")
    monkeypatch.setenv("LAYER_GATES_BASE", base2)
    assert lg.run_db_tests_gate(tmp_path) == 1
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto", "require_tests_for_changed": False, "mode": "hard",
            "test_command": "true",
        },
    )
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(
        f["kind"] == "require_disabled_without_decision"
        for f in _summary(tmp_path, "e2e")["findings"]
    )


def test_missing_suite_and_changed_sources(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    _pw_tree(tmp_path)
    (tmp_path / "e2e" / "a.spec.ts").write_text("   \n", encoding="utf-8")
    (tmp_path / "e2e" / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const a = 1\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto", "mode": "hard", "source_globs": ["src/**"],
            "test_globs": ["e2e/**"], "test_command": "true",
        },
    )
    base = _commit_all(tmp_path, "base")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(f["kind"] == "missing_tests" for f in _summary(tmp_path, "e2e")["findings"])
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok', async () => {})\n", encoding="utf-8")
    base_suite = _commit_all(tmp_path, "suite")
    (tmp_path / "src" / "app.ts").write_text("export const a = 2\n", encoding="utf-8")
    _commit_all(tmp_path, "ui")
    monkeypatch.setenv("LAYER_GATES_BASE", base_suite)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(f["kind"] == "tests_not_updated" for f in _summary(tmp_path, "e2e")["findings"])
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok2', async () => {})\n", encoding="utf-8")
    _commit_all(tmp_path, "ui+e2e")
    assert lg.run_e2e_gate(tmp_path) == 0


def test_git_fail_closed_and_autodetect(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    _pw_tree(tmp_path)
    _write_quality(
        tmp_path,
        e2e={"enabled": "auto", "mode": "hard", "base_ref": "does-not-exist", "test_command": "true"},
    )
    _commit_all(tmp_path, "init")
    monkeypatch.delenv("LAYER_GATES_BASE", raising=False)
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(f["kind"] == "git_diff_failed" for f in _summary(tmp_path, "e2e")["findings"])
    with pytest.raises(lg.GitDiffError, match="git diff failed"):
        lg._changed_files(tmp_path, "no-such-ref-zzzz")
    assert lg.default_test_command("e2e", {"framework": "playwright"}) == "npx playwright test"
    assert lg.default_test_command("e2e", {"framework": "cypress"}) == "npx cypress run"
    assert lg.default_test_command("db_tests", {"framework": "prisma"}) is None
    assert lg.default_test_command("db_tests", {"framework": "pgtap"}) == (
        "pg_prove db/tests/*.sql tests/db/*.sql pgtap/*.sql"
    )
    (tmp_path / "supabase").mkdir(exist_ok=True)
    assert lg._has_supabase(tmp_path) is False
    (tmp_path / "supabase" / "config.toml").write_text("[project]\n", encoding="utf-8")
    assert lg.default_test_command("db_tests", {"framework": "sql"}, root=tmp_path) == "supabase test db"


def test_test_command_required_orm(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"prisma": "5"}}), encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "t.sql").write_text("SELECT 1;\n", encoding="utf-8")
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        db_tests={
            "enabled": "auto", "mode": "hard", "source_globs": ["**/migrations/**"],
            "test_globs": ["**/db/tests/**"], "test_command": None,
        },
    )
    base = _commit_all(tmp_path, "base")
    (mig / "002.sql").write_text("CREATE TABLE b(id int);\n", encoding="utf-8")
    (tests / "t2.sql").write_text("SELECT 2;\n", encoding="utf-8")
    _commit_all(tmp_path, "mig")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_db_tests_gate(tmp_path) == 1
    assert any(f["kind"] == "test_command_required" for f in _summary(tmp_path, "db_tests")["findings"])


def test_apply_layer_upgrades_persists(tmp_path: Path):
    cfg = defaults_fn()
    cfg["e2e"] = {"enabled": False, "mode": "warn"}
    cfg["gates"] = {"ci": ["coverage", "mutation"], "pre_push": ["mutation"]}
    save_quality(tmp_path, cfg)
    up = lg.apply_layer_upgrades_to_repo(tmp_path)
    assert "e2e.enabled" in up and "e2e.mode" in up
    assert "gates.ci" in up
    loaded = json.loads((tmp_path / "context" / "quality.json").read_text(encoding="utf-8"))
    assert loaded["e2e"]["enabled"] == "auto"
    assert loaded["e2e"]["mode"] == "hard"
    assert loaded["gates"]["ci"] == ["coverage", "e2e", "db_tests", "mutation"]
    assert lg.apply_layer_upgrades_to_repo(tmp_path) == []


def test_install_ensure_quality_hook_oracles(tmp_path: Path):
    import agentized.connect as connect_mod
    from agentized.quality import load_quality

    lg.install_ensure_quality_hook()
    wrapped = connect_mod.ensure_quality_config
    assert getattr(wrapped, "_age31_layer_hook", False) is True
    assert connect_mod.ensure_quality_config is wrapped  # after second install
    lg.install_ensure_quality_hook()
    assert connect_mod.ensure_quality_config is wrapped
    cfg = defaults_fn()
    cfg["e2e"] = {"enabled": False, "mode": "warn"}
    cfg["db_tests"] = {"enabled": False, "mode": "warn"}
    cfg["gates"] = {"ci": ["mutation"], "pre_push": ["mutation"]}
    cfg["test_smells"] = {"mode": "hard", "enabled": True}
    cfg["architecture"] = {"mode": "hard", "enabled": True}
    save_quality(tmp_path, cfg)
    out = wrapped(tmp_path, "context", coverage_pct=91)
    assert out["created"] is False and out["coverage_pct"] == 91
    assert out["path"].endswith("quality.json")
    modes = out["upgraded_modes"]
    assert {"e2e.enabled", "e2e.mode", "db_tests.enabled", "db_tests.mode", "gates.ci", "gates.pre_push"} <= set(modes)
    loaded = load_quality(tmp_path)
    assert loaded["e2e"] == {**loaded["e2e"], "enabled": "auto", "mode": "hard"}
    assert loaded["e2e"]["enabled"] == "auto" and loaded["db_tests"]["enabled"] == "auto"
    assert loaded["gates"]["ci"].index("e2e") < loaded["gates"]["ci"].index("mutation")
    assert wrapped(tmp_path, "context")["upgraded_modes"] == []


def test_orbit_mini_and_upgrade(tmp_path: Path, monkeypatch):
    root = _ensure_mini_app(tmp_path)
    _git_init(root)
    _write_quality(
        root,
        e2e={
            "enabled": "auto", "mode": "hard", "source_globs": ["src/**"],
            "test_globs": ["e2e/**"], "test_command": "true", "skip_rel_prefixes": [],
        },
        db_tests={
            "enabled": "auto", "mode": "hard", "source_globs": ["**/migrations/**"],
            "test_globs": ["**/db/tests/**"], "test_command": "true", "skip_rel_prefixes": [],
        },
    )
    base = _commit_all(root, "base")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_e2e_gate(root) == 0 and lg.run_db_tests_gate(root) == 0
    data = {
        "e2e": {"enabled": False, "mode": "warn"},
        "db_tests": {"enabled": False, "mode": "warn"},
        "gates": {"ci": ["coverage", "mutation"], "pre_push": ["mutation"]},
    }
    up = lg.upgrade_layer_gate_config(data)
    assert "e2e.enabled" in up and data["gates"]["ci"] == ["coverage", "e2e", "db_tests", "mutation"]
    created: dict = {"gates": {"ci": ["coverage"], "pre_push": ["coverage"]}}
    lg.upgrade_layer_gate_config(created)
    assert created["e2e"] == {"enabled": "auto", "mode": "hard", "require_tests_for_changed": True}
    bad = {"e2e": {"enabled": "auto", "mode": "hard"}, "db_tests": {"enabled": "auto", "mode": "hard"}, "gates": "bogus"}
    lg.upgrade_layer_gate_config(bad)
    assert bad["gates"]["ci"] == ["e2e", "db_tests"]
    gates: list = ["coverage"]
    assert lg._ensure_gate_list(gates, "e2e") is True and gates == ["coverage", "e2e"]
    # full-cover dogfood glob (fnmatch * matches /) covers layer_gates.py
    globs = list(defaults_fn()["mutation"]["include_globs"])
    assert globs == ["runtime/agentized/*.py"]


def test_helpers_deps_context_skips(tmp_path: Path, monkeypatch):
    assert lg._JSON_ENCODING == "utf-8" and lg._CMD_OUTPUT_LIMIT == 4000
    assert lg._normalize_rel(r"db\migrations/") == "db/migrations"
    assert lg._normalize_rel("db/migrations") == "db/migrations"
    assert lg._looks_like_db_dir("db/migrations/") == "migrations_dir"
    assert lg._looks_like_db_dir("pgtap/") == "pgtap_dir"
    assert lg._looks_like_db_dir("tests/db") == "db_tests_dir"
    assert lg._looks_like_db_dir("tests/sql") == "db_tests_dir"
    assert lg._looks_like_db_dir("db/tests") == "db_tests_dir"
    assert lg._looks_like_db_dir("src/components") is None
    assert lg._glob_match("e2e/a.ts", "e2e/**") is True
    assert lg._enabled_mode(False) == "false"
    assert lg._enabled_mode(True) == "true"
    assert lg._enabled_mode("AUTO") == "auto"
    g1 = ["mutation"]
    assert lg._ensure_gate_list(g1, "e2e") is True and g1 == ["e2e", "mutation"]
    g2 = ["e2e", "mutation"]
    assert lg._ensure_gate_list(g2, "e2e") is False and g2 == ["e2e", "mutation"]
    g3 = ["coverage"]
    assert lg._ensure_gate_list(g3, "db_tests") is True and g3 == ["coverage", "db_tests"]
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    path = pkg / "package.json"
    path.write_bytes(json.dumps({
        "dependencies": {"prisma": "1"}, "devDependencies": {"@playwright/test": "1"},
        "peerDependencies": {"cypress": "1"}, "optionalDependencies": {"drizzle-orm": "1"},
    }).encode("utf-8"))
    assert lg._read_package_deps(path) == {"prisma", "@playwright/test", "cypress", "drizzle-orm"}
    py = tmp_path / "py"
    py.mkdir()
    (py / "pyproject.toml").write_text('[project]\ndependencies = [\n  "sqlalchemy",\n]\n', encoding="utf-8")
    (py / "requirements.txt").write_text("alembic==1\n", encoding="utf-8")
    found = lg._read_python_deps(py, ("pyproject.toml",))
    assert "requirements.txt" in {rel for rel, _ in found}
    assert any("alembic" in names for _, names in found)
    # pyproject skipped via prefixes; requirements still counted.
    found2 = lg._read_python_deps(py, ())
    assert {rel for rel, _ in found2} >= {"pyproject.toml", "requirements.txt"}
    assert any("sqlalchemy" in names for _, names in found2)
    (tmp_path / "marker.txt").write_text("yes", encoding="utf-8")
    rc, out = lg._run_command(tmp_path, "test -f marker.txt && echo HELLO_GATE")
    assert rc == 0 and isinstance(out, str) and "HELLO_GATE" in out
    rc_big, out_big = lg._run_command(tmp_path, "python3 -c 'print(\"x\" * 5000)'")
    assert rc_big == 0 and len(out_big) == 4000
    _git_init(tmp_path)
    _pw_tree(tmp_path)
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "t.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={"enabled": "auto", "mode": "hard", "test_command": "true", "source_globs": ["src/**"], "test_globs": ["e2e/**"]},
        db_tests={
            "enabled": "auto", "mode": "hard", "test_command": "true",
            "source_globs": ["**/migrations/**"], "test_globs": ["**/db/tests/**"],
        },
    )
    alt = tmp_path / "ctx-alt"
    alt.mkdir()
    cfg = default_quality_config()
    cfg["modules"] = []
    cfg["e2e"] = {"enabled": False, "mode": "hard", "test_command": "true"}
    cfg["db_tests"] = {"enabled": False, "mode": "hard", "test_command": "true"}
    (alt / "quality.json").write_text(json.dumps(cfg), encoding="utf-8")
    _commit_all(tmp_path, "init")
    monkeypatch.setenv("LAYER_GATES_BASE", "HEAD")
    assert lg.run_e2e_gate(tmp_path, context="context") == 0
    assert lg.run_e2e_gate(tmp_path, context="ctx-alt") == 1
    assert lg.run_db_tests_gate(tmp_path, context="ctx-alt") == 1
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto", "mode": "hard",
            "skip_rel_prefixes": ["playwright.config.ts", "e2e/", "e2e"],
            "test_command": "true", "source_globs": ["src/**"], "test_globs": ["e2e/**"],
        },
        db_tests={
            "enabled": "auto", "mode": "hard", "skip_rel_prefixes": ["db/"], "test_command": "true",
            "source_globs": ["**/migrations/**"], "test_globs": ["**/db/tests/**"],
        },
    )
    # Hide playwright dep under pkg/ as well as root config/e2e.
    skip = ("playwright.config.ts", "e2e/", "e2e", "pkg/")
    assert lg.detect_e2e(tmp_path, skip_prefixes=skip)["present"] is False
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto", "mode": "hard", "skip_rel_prefixes": list(skip),
            "test_command": "true", "source_globs": ["src/**"], "test_globs": ["e2e/**"],
        },
        db_tests={
            "enabled": "auto", "mode": "hard",
            "skip_rel_prefixes": ["db/", "py/", "pkg/"],
            "test_command": "true",
            "source_globs": ["**/migrations/**"], "test_globs": ["**/db/tests/**"],
        },
    )
    assert lg.run_e2e_gate(tmp_path) == 0 and _summary(tmp_path, "e2e")["reason"] == "layer_absent"
    assert lg.run_db_tests_gate(tmp_path) == 0 and _summary(tmp_path, "db_tests")["reason"] == "layer_absent"
