"""AGE-31 layer gates — real quality.json trees (no mocked load_quality)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agentized import layer_gates as lg
from agentized.connect import ensure_quality_config
from agentized.quality import default_quality_config, save_quality
from agentized.quality_defaults import default_quality_config as defaults_fn


REPO = Path(__file__).resolve().parents[2]
FIXTURE_MINI = REPO / "templates" / "quality" / "fixtures" / "orbit-like-mini"
FIXTURE_MONO = REPO / "templates" / "quality" / "fixtures" / "orbit-like-monorepo"
FIXTURE_ORM = REPO / "templates" / "quality" / "fixtures" / "orbit-like-orm-only"


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True, capture_output=True)


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
    # Tiny module so coverage_check is not needed when calling gates directly
    cfg["modules"] = []
    for key, value in section_overrides.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    save_quality(root, cfg)


def _summary(root: Path, gate: str) -> dict:
    return json.loads((root / "reports" / gate / f"{gate}-summary.json").read_text(encoding="utf-8"))


def test_detect_e2e_playwright_package_and_dir(tmp_path: Path):
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "1.0.0"}}), encoding="utf-8"
    )
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "a.spec.ts").write_text("test('x', async () => {})\n", encoding="utf-8")
    det = lg.detect_e2e(tmp_path, skip_prefixes=())
    kinds = sorted({e["kind"] for e in det["evidence"]})
    assert kinds == ["config", "package_dep", "tests_dir"]
    assert det["framework"] == "playwright"
    assert det["present"] is True


def test_detect_e2e_absent(tmp_path: Path):
    (tmp_path / "README.md").write_text("no ui\n", encoding="utf-8")
    det = lg.detect_e2e(tmp_path, skip_prefixes=())
    assert det["evidence"] == []
    assert det["framework"] is None


def test_detect_db_migrations_and_pgtap(tmp_path: Path):
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE t(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_t.sql").write_text("SELECT plan(1);\nSELECT has_table('t');\n", encoding="utf-8")
    det = lg.detect_db_layer(tmp_path, skip_prefixes=())
    kinds = sorted({e["kind"] for e in det["evidence"]})
    assert "migrations_dir" in kinds
    assert "db_tests_dir" in kinds or "pgtap_sql" in kinds
    assert det["framework"] in {"pgtap", "sql"}


def test_detect_db_absent(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    det = lg.detect_db_layer(tmp_path, skip_prefixes=())
    assert det["evidence"] == []


def test_nested_monorepo_and_orm_fixtures_detect():
    mono_e2e = lg.detect_e2e(FIXTURE_MONO, skip_prefixes=())
    mono_db = lg.detect_db_layer(FIXTURE_MONO, skip_prefixes=())
    assert mono_e2e["present"] is True
    assert any("apps/web" in e.get("path", "") for e in mono_e2e["evidence"])
    assert mono_db["present"] is True
    assert any("services/api/db/migrations" in e.get("path", "") for e in mono_db["evidence"])

    orm = lg.detect_db_layer(FIXTURE_ORM, skip_prefixes=())
    assert orm["present"] is True
    assert orm["framework"] == "prisma"
    assert any(e.get("kind") == "orm_dep" for e in orm["evidence"])


def test_skip_prefixes_only_for_agentized_layout(tmp_path: Path):
    # User repo with real templates/e2e must NOT be skipped by default.
    (tmp_path / "templates" / "e2e").mkdir(parents=True)
    (tmp_path / "templates" / "e2e" / "a.spec.ts").write_text("test('a')\n", encoding="utf-8")
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    assert lg.is_agentized_repo(tmp_path) is False
    assert lg.skip_rel_prefixes(tmp_path) == ()
    det = lg.detect_e2e(tmp_path)
    assert det["present"] is True

    # Agentized-shaped host skips templates/
    (tmp_path / "runtime" / "agentized").mkdir(parents=True)
    (tmp_path / "templates" / "quality").mkdir(parents=True)
    assert lg.is_agentized_repo(tmp_path) is True
    assert lg.skip_rel_prefixes(tmp_path) == ("templates/", "tests/fixtures/")
    # Configurable override
    assert lg.skip_rel_prefixes(tmp_path, {"skip_rel_prefixes": ["vendor/"]}) == ("vendor/",)


def test_host_agentized_ignores_shipped_fixtures():
    # Against the real Agentized checkout, templates fixtures must not mark present.
    e2e = lg.detect_e2e(REPO)
    db = lg.detect_db_layer(REPO)
    assert [e.get("path") for e in e2e["evidence"] if str(e.get("path", "")).startswith("templates/")] == []
    assert [e.get("path") for e in db["evidence"] if str(e.get("path", "")).startswith("templates/")] == []


def _decision(*, days: int = 7, approved_by: str = "Maxim") -> dict:
    from datetime import datetime, timedelta, timezone

    exp = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    return {
        "reason": "temporary migration",
        "approved_by": approved_by,
        "expires": exp,
    }


def test_e2e_gate_disabled_with_layer_fails_without_decision(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "a.spec.ts").write_text("test('a', async () => {})\n", encoding="utf-8")
    _write_quality(tmp_path, e2e={"enabled": False, "mode": "hard", "test_command": "true"})
    _commit_all(tmp_path, "init")
    monkeypatch.delenv("LAYER_GATES_BASE", raising=False)
    assert lg.run_e2e_gate(tmp_path) == 1
    summary = _summary(tmp_path, "e2e")
    assert summary["passed"] is False
    assert any(f["kind"] == "disabled_without_decision" for f in summary["findings"])


def test_e2e_gate_disabled_with_disable_decision_passes(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "a.spec.ts").write_text("test('a', async () => {})\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={"enabled": False, "mode": "hard", "disable_decision": _decision()},
    )
    _commit_all(tmp_path, "init")
    assert lg.run_e2e_gate(tmp_path) == 0
    assert _summary(tmp_path, "e2e")["reason"] == "disabled_by_decision"


def test_disable_decision_rejects_missing_approved_by_and_long_expiry():
    from datetime import datetime, timedelta, timezone

    far = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    near = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    results = [
        int(
            lg.disable_decision_valid(
                {"disable_decision": {"reason": "x", "expires": far, "approved_by": "Maxim"}}
            )
        ),
        int(
            lg.disable_decision_valid(
                {"disable_decision": {"reason": "x", "expires": near, "approved_by": ""}}
            )
        ),
        int(lg.disable_decision_valid({"disable_decision": _decision(days=3)})),
    ]
    assert results == [0, 0, 1]


def test_disable_decision_max_days_default_is_14():
    from datetime import datetime, timedelta, timezone

    assert lg.DISABLE_DECISION_MAX_DAYS == 14
    clock = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = {
        "reason": "pause",
        "approved_by": "Maxim",
    }
    # Exactly 14 days ahead is allowed; 14d+1s is not (default max_days=14).
    ok = {
        **base,
        "expires": (clock + timedelta(days=14)).isoformat(),
    }
    too_long = {
        **base,
        "expires": (clock + timedelta(days=14, seconds=1)).isoformat(),
    }
    assert lg.disable_decision_valid({"disable_decision": ok}, now=clock) is True
    assert lg.disable_decision_valid({"disable_decision": too_long}, now=clock) is False
    # Explicit max_days=15 would allow too_long — proves default is not 15.
    assert (
        lg.disable_decision_valid({"disable_decision": too_long}, now=clock, max_days=15)
        is True
    )
    # expires == clock is expired (not a strict `<` check).
    equal = {**base, "expires": clock.isoformat()}
    assert lg.disable_decision_valid({"disable_decision": equal}, now=clock) is False
    # Sub-second remaining must still be valid (kills `remaining <= 1` mutants).
    soon = {
        **base,
        "expires": (clock + timedelta(milliseconds=500)).isoformat(),
    }
    assert lg.disable_decision_valid({"disable_decision": soon}, now=clock) is True


def test_disable_decision_rejects_empty_or_missing_reason():
    from datetime import datetime, timedelta, timezone

    exp = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    assert (
        lg.disable_decision_valid(
            {"disable_decision": {"approved_by": "Maxim", "expires": exp}}
        )
        is False
    )
    assert (
        lg.disable_decision_valid(
            {"disable_decision": {"reason": "", "approved_by": "Maxim", "expires": exp}}
        )
        is False
    )
    assert (
        lg.disable_decision_valid(
            {"disable_decision": {"reason": "   ", "approved_by": "Maxim", "expires": exp}}
        )
        is False
    )
    assert lg.disable_decision_valid({"disable_decision": "nope"}) is False
    assert lg.disable_decision_valid({}) is False


def test_disable_decision_offset_zulu_and_rejects_naive_or_invalid():
    from datetime import datetime, timedelta, timezone

    clock = datetime(2026, 1, 1, tzinfo=timezone.utc)
    offset = {
        "reason": "pause",
        "approved_by": "Maxim",
        "expires": "2026-01-08T00:00:00+00:00",
    }
    assert lg.disable_decision_valid({"disable_decision": offset}, now=clock) is True
    zulu = {
        "reason": "pause",
        "approved_by": "Maxim",
        "expires": "2026-01-08T00:00:00Z",
    }
    assert lg.disable_decision_valid({"disable_decision": zulu}, now=clock) is True
    naive = {
        "reason": "pause",
        "approved_by": "Maxim",
        "expires": "2026-01-08T00:00:00",
    }
    assert lg.disable_decision_valid({"disable_decision": naive}, now=clock) is False
    bad = {"reason": "pause", "approved_by": "Maxim", "expires": "not-a-date"}
    assert lg.disable_decision_valid({"disable_decision": bad}, now=clock) is False
    assert (
        lg.disable_decision_valid(
            {"disable_decision": {"reason": "x", "approved_by": "Maxim", "expires": 123}},
            now=clock,
        )
        is False
    )
    # now without tz rejected
    assert (
        lg.disable_decision_valid(
            {"disable_decision": offset}, now=datetime(2026, 1, 1)
        )
        is False
    )


def test_require_false_without_decision_fails(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "a.spec.ts").write_text("test('a', async () => {})\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto",
            "require_tests_for_changed": False,
            "mode": "hard",
            "test_command": "true",
        },
    )
    _commit_all(tmp_path, "init")
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(
        f["kind"] == "require_disabled_without_decision"
        for f in _summary(tmp_path, "e2e")["findings"]
    )


def test_red_e2e_command_fails_gate(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "a.spec.ts").write_text("test('a', async () => {})\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto",
            "mode": "hard",
            "source_globs": ["src/**"],
            "test_globs": ["e2e/**"],
            "test_command": "false",
        },
    )
    base = _commit_all(tmp_path, "base")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(f["kind"] == "test_command_failed" for f in _summary(tmp_path, "e2e")["findings"])


def test_red_db_command_fails_gate(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "t.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        db_tests={
            "enabled": "auto",
            "mode": "hard",
            "source_globs": ["**/migrations/**"],
            "test_globs": ["**/db/tests/**"],
            "test_command": "exit 1",
        },
    )
    base = _commit_all(tmp_path, "base")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_db_tests_gate(tmp_path) == 1
    assert any(f["kind"] == "test_command_failed" for f in _summary(tmp_path, "db_tests")["findings"])


def test_gitkeep_only_counts_as_missing_suite(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_path / "e2e" / "empty.spec.ts").write_text("   \n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const a = 1\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto",
            "mode": "hard",
            "source_globs": ["src/**"],
            "test_globs": ["e2e/**"],
            "test_command": "true",
        },
    )
    base = _commit_all(tmp_path, "base")
    # Even without further source changes, missing real suite must fail.
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(f["kind"] == "missing_tests" for f in _summary(tmp_path, "e2e")["findings"])


def test_missing_suite_before_no_change_shortcut(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    # no db tests at all
    _write_quality(
        tmp_path,
        db_tests={
            "enabled": "auto",
            "mode": "hard",
            "source_globs": ["**/migrations/**"],
            "test_globs": ["**/db/tests/**"],
            "test_command": "true",
        },
    )
    base = _commit_all(tmp_path, "base")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_db_tests_gate(tmp_path) == 1
    summary = _summary(tmp_path, "db_tests")
    assert summary["reason"] == "missing_tests"
    assert summary["skipped"] is False


def test_e2e_requires_tests_for_changed_sources(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok', async () => {})\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const a = 1\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto",
            "mode": "hard",
            "require_tests_for_changed": True,
            "source_globs": ["src/**"],
            "test_globs": ["e2e/**"],
            "test_command": "true",
        },
    )
    base = _commit_all(tmp_path, "base")
    (tmp_path / "src" / "app.ts").write_text("export const a = 2\n", encoding="utf-8")
    _commit_all(tmp_path, "ui")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(f["kind"] == "tests_not_updated" for f in _summary(tmp_path, "e2e")["findings"])


def test_e2e_pass_when_tests_updated(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok', async () => {})\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const a = 1\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto",
            "mode": "hard",
            "source_globs": ["src/**"],
            "test_globs": ["e2e/**"],
            "test_command": "true",
        },
    )
    base = _commit_all(tmp_path, "base")
    (tmp_path / "src" / "app.ts").write_text("export const a = 2\n", encoding="utf-8")
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok2', async () => {})\n", encoding="utf-8")
    _commit_all(tmp_path, "ui+e2e")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_e2e_gate(tmp_path) == 0
    summary = _summary(tmp_path, "e2e")
    assert summary["passed"] is True
    assert summary["skipped"] is False


def test_deleted_source_counts_in_diff(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok', async () => {})\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "old.ts").write_text("export const a = 1\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto",
            "mode": "hard",
            "source_globs": ["src/**"],
            "test_globs": ["e2e/**"],
            "test_command": "true",
        },
    )
    base = _commit_all(tmp_path, "base")
    (tmp_path / "src" / "old.ts").unlink()
    _commit_all(tmp_path, "delete-src")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert "src/old.ts" in _summary(tmp_path, "e2e")["changedSources"]


def test_bad_base_ref_fails_closed(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok', async () => {})\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={"enabled": "auto", "mode": "hard", "base_ref": "does-not-exist", "test_command": "true"},
    )
    _commit_all(tmp_path, "init")
    monkeypatch.delenv("LAYER_GATES_BASE", raising=False)
    monkeypatch.delenv("MUTATION_BASE", raising=False)
    assert lg.run_e2e_gate(tmp_path) == 1
    assert any(f["kind"] == "git_diff_failed" for f in _summary(tmp_path, "e2e")["findings"])


def test_changed_files_raises_git_diff_error(tmp_path: Path):
    _git_init(tmp_path)
    _commit_all(tmp_path, "empty")
    with pytest.raises(lg.GitDiffError, match="git diff failed"):
        lg._changed_files(tmp_path, "no-such-ref-zzzz")


def test_test_command_required_when_no_default(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    # ORM-only style: prisma dep + db tests, framework prisma → no default command
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"prisma": "5.0.0"}}), encoding="utf-8"
    )
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "t.sql").write_text("SELECT 1;\n", encoding="utf-8")
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        db_tests={
            "enabled": "auto",
            "mode": "hard",
            "source_globs": ["**/migrations/**"],
            "test_globs": ["**/db/tests/**"],
            "test_command": None,
        },
    )
    base = _commit_all(tmp_path, "base")
    (mig / "002.sql").write_text("CREATE TABLE b(id int);\n", encoding="utf-8")
    (tests / "t2.sql").write_text("SELECT 2;\n", encoding="utf-8")
    _commit_all(tmp_path, "mig")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.run_db_tests_gate(tmp_path) == 1
    assert any(f["kind"] == "test_command_required" for f in _summary(tmp_path, "db_tests")["findings"])


def test_default_playwright_command():
    det = {"framework": "playwright", "evidence": []}
    assert lg.default_test_command("e2e", det) == "npx playwright test"
    assert lg.default_test_command("db_tests", {"framework": "prisma"}) is None


def test_default_test_command_all_frameworks(tmp_path: Path):
    assert lg.default_test_command("e2e", {"framework": "cypress"}) == "npx cypress run"
    assert lg.default_test_command("e2e", {"framework": "nightwatch"}) == "npx nightwatch"
    assert lg.default_test_command("e2e", {"framework": "webdriverio"}) == "npx wdio run"
    assert lg.default_test_command("e2e", {"framework": "unknown"}) is None
    assert lg.default_test_command("e2e", {"framework": None}) is None
    assert lg.default_test_command("other", {"framework": "playwright"}) is None
    assert (
        lg.default_test_command("db_tests", {"framework": "pgtap"})
        == "pg_prove db/tests/*.sql tests/db/*.sql pgtap/*.sql"
    )
    # supabase dir alone (no config.toml) must NOT autodetect
    (tmp_path / "supabase").mkdir()
    assert lg._has_supabase(tmp_path) is False
    assert lg.default_test_command("db_tests", {"framework": "sql"}, root=tmp_path) is None
    (tmp_path / "supabase" / "config.toml").write_text("[project]\n", encoding="utf-8")
    assert lg._has_supabase(tmp_path) is True
    assert (
        lg.default_test_command("db_tests", {"framework": "sql"}, root=tmp_path)
        == "supabase test db"
    )


def test_orbit_like_mini_through_gates(tmp_path: Path, monkeypatch):
    shutil.copytree(FIXTURE_MINI, tmp_path / "app")
    root = tmp_path / "app"
    _git_init(root)
    _write_quality(
        root,
        e2e={
            "enabled": "auto",
            "mode": "hard",
            "source_globs": ["src/**"],
            "test_globs": ["e2e/**"],
            "test_command": "true",
            "skip_rel_prefixes": [],
        },
        db_tests={
            "enabled": "auto",
            "mode": "hard",
            "source_globs": ["**/migrations/**"],
            "test_globs": ["**/db/tests/**"],
            "test_command": "true",
            "skip_rel_prefixes": [],
        },
    )
    base = _commit_all(root, "base")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    assert lg.detect_e2e(root, skip_prefixes=())["present"] is True
    assert lg.detect_db_layer(root, skip_prefixes=())["present"] is True
    # Layer present → suite must run (test_command=true stands in for playwright/pg_prove).
    assert lg.run_e2e_gate(root) == 0
    assert lg.run_db_tests_gate(root) == 0
    assert _summary(root, "e2e")["skipped"] is False
    assert _summary(root, "e2e")["testCommand"] == "true"
    assert _summary(root, "db_tests")["skipped"] is False


def test_default_commands_include_supabase(tmp_path: Path):
    (tmp_path / "supabase").mkdir()
    (tmp_path / "supabase" / "config.toml").write_text("[project]\n", encoding="utf-8")
    assert (
        lg.default_test_command("db_tests", {"framework": "sql"}, root=tmp_path)
        == "supabase test db"
    )
    assert lg.default_test_command("e2e", {"framework": "playwright"}, root=tmp_path) == (
        "npx playwright test"
    )


def test_upgrade_layer_gate_config_injects_gates_and_reenables():
    data = {
        "e2e": {"enabled": False, "mode": "warn"},
        "db_tests": {"enabled": False, "mode": "warn"},
        "gates": {"ci": ["coverage", "mutation"], "pre_push": ["mutation"]},
    }
    upgraded = lg.upgrade_layer_gate_config(data)
    assert "e2e.enabled" in upgraded
    assert "e2e.mode" in upgraded
    assert "db_tests.enabled" in upgraded
    assert "db_tests.mode" in upgraded
    assert "gates.ci" in upgraded
    assert "gates.pre_push" in upgraded
    assert data["e2e"]["enabled"] == "auto"
    assert data["e2e"]["mode"] == "hard"
    assert data["gates"]["ci"] == ["coverage", "e2e", "db_tests", "mutation"]
    assert data["gates"]["pre_push"] == ["e2e", "db_tests", "mutation"]
    # Idempotent
    assert lg.upgrade_layer_gate_config(data) == []


def test_upgrade_creates_missing_sections_with_exact_defaults():
    data: dict = {"gates": {"ci": ["coverage"], "pre_push": ["coverage"]}}
    upgraded = lg.upgrade_layer_gate_config(data)
    assert "e2e.created" in upgraded
    assert "db_tests.created" in upgraded
    assert data["e2e"] == {
        "enabled": "auto",
        "mode": "hard",
        "require_tests_for_changed": True,
    }
    assert data["db_tests"] == {
        "enabled": "auto",
        "mode": "hard",
        "require_tests_for_changed": True,
    }
    assert set(data["e2e"]) == {"enabled", "mode", "require_tests_for_changed"}
    assert "enabled" in data["e2e"] and "ENABLED" not in data["e2e"]
    assert data["gates"]["ci"] == ["coverage", "e2e", "db_tests"]
    assert data["gates"]["pre_push"] == ["coverage", "e2e", "db_tests"]


def test_upgrade_ignores_missing_mode_and_enabled_keys():
    data = {
        "e2e": {"require_tests_for_changed": True},
        "db_tests": {"mode": "hard"},
        "gates": {"ci": ["e2e", "db_tests", "mutation"], "pre_push": ["e2e", "db_tests", "mutation"]},
    }
    assert lg.upgrade_layer_gate_config(data) == []
    assert "enabled" not in data["e2e"]
    assert data["e2e"].get("mode") is None
    # Explicit warn still upgrades; explicit false still re-enables.
    data2 = {
        "e2e": {"enabled": False, "mode": "warn"},
        "db_tests": {"enabled": "false", "mode": "WARN"},
        "gates": {"ci": ["mutation"], "pre_push": ["mutation"]},
    }
    up = lg.upgrade_layer_gate_config(data2)
    assert "e2e.mode" in up and "e2e.enabled" in up
    assert "db_tests.mode" in up and "db_tests.enabled" in up
    assert data2["e2e"]["mode"] == "hard"
    assert data2["e2e"]["enabled"] == "auto"


def test_upgrade_repairs_non_dict_gates_and_non_list_gate_lists():
    data = {
        "e2e": {"enabled": "auto", "mode": "hard"},
        "db_tests": {"enabled": "auto", "mode": "hard"},
        "gates": "bogus",
    }
    up = lg.upgrade_layer_gate_config(data)
    assert isinstance(data["gates"], dict)
    assert data["gates"] is not None
    assert "gates" in data and "GATES" not in data and "XXgatesXX" not in data
    assert data["gates"]["ci"] == ["e2e", "db_tests"]
    assert data["gates"]["pre_push"] == ["e2e", "db_tests"]
    assert "gates.ci" in up and "gates.pre_push" in up

    data3 = {
        "e2e": {"enabled": "auto", "mode": "hard"},
        "db_tests": {"enabled": "auto", "mode": "hard"},
        "gates": {"ci": "nope", "pre_push": 3},
    }
    up3 = lg.upgrade_layer_gate_config(data3)
    assert data3["gates"]["ci"] == ["e2e", "db_tests"]
    assert data3["gates"]["pre_push"] == ["e2e", "db_tests"]
    assert isinstance(data3["gates"]["ci"], list)
    assert "gates.ci" in up3


def test_ensure_gate_list_appends_exact_name():
    gates: list = ["coverage"]
    assert lg._ensure_gate_list(gates, "e2e") is True
    assert gates == ["coverage", "e2e"]
    assert lg._ensure_gate_list(gates, "e2e") is False
    assert gates == ["coverage", "e2e"]
    with_mut = ["coverage", "mutation"]
    assert lg._ensure_gate_list(with_mut, "db_tests") is True
    assert with_mut == ["coverage", "db_tests", "mutation"]


def test_read_package_deps_all_dependency_blocks(tmp_path: Path):
    assert lg._JSON_ENCODING == "utf-8"
    path = tmp_path / "package.json"
    path.write_bytes(
        json.dumps(
            {
                "dependencies": {"prisma": "1"},
                "devDependencies": {"@playwright/test": "1"},
                "peerDependencies": {"cypress": "1"},
                "optionalDependencies": {"drizzle-orm": "1"},
            },
            ensure_ascii=False,
        ).encode("utf-8")
    )
    names = lg._read_package_deps(path)
    assert names == {"prisma", "@playwright/test", "cypress", "drizzle-orm"}
    bad = tmp_path / "bad.json"
    bad.write_text("[1,2,3]\n", encoding="utf-8")
    assert lg._read_package_deps(bad) == set()
    missing = tmp_path / "nope.json"
    assert lg._read_package_deps(missing) == set()


def test_looks_like_db_dir_normalizes_slashes():
    assert lg._normalize_rel(r"db\migrations/") == "db/migrations"
    assert lg._normalize_rel("db/migrations/") == "db/migrations"
    assert lg._looks_like_db_dir("db/migrations/") == "migrations_dir"
    assert lg._looks_like_db_dir(r"db\migrations") == "migrations_dir"
    assert lg._looks_like_db_dir("apps/api/db/migrations") == "migrations_dir"
    assert lg._looks_like_db_dir("pgtap/") == "pgtap_dir"
    assert lg._looks_like_db_dir("tests/db/") == "db_tests_dir"
    assert lg._looks_like_db_dir("src/components") is None


def test_detect_db_layer_continue_not_break_on_placeholder(tmp_path: Path):
    # First migration file is placeholder; later real file must still be found (continue≠break).
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / ".gitkeep").write_text("", encoding="utf-8")
    (mig / "001_real.sql").write_text("CREATE TABLE t(id int);\n", encoding="utf-8")
    det = lg.detect_db_layer(tmp_path, skip_prefixes=())
    assert det["present"] is True
    assert any(e.get("path") == "db/migrations" for e in det["evidence"])


def test_detect_db_layer_kind_from_looks_like(tmp_path: Path):
    pgtap = tmp_path / "pgtap"
    pgtap.mkdir()
    (pgtap / "t.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    det = lg.detect_db_layer(tmp_path, skip_prefixes=())
    kinds = {e["kind"] for e in det["evidence"]}
    assert "pgtap_dir" in kinds or "pgtap_sql" in kinds
    assert det["framework"] == "pgtap"


def test_detect_db_skips_prefix_then_continues(tmp_path: Path):
    # Skip migrations/ but still find pgtap/ (continue, not break).
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001.sql").write_text("CREATE TABLE t(id int);\n", encoding="utf-8")
    pgtap = tmp_path / "pgtap"
    pgtap.mkdir()
    (pgtap / "t.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    det = lg.detect_db_layer(tmp_path, skip_prefixes=("migrations/",))
    paths = {e.get("path") for e in det["evidence"]}
    assert "migrations" not in paths
    assert "pgtap" in paths or any(str(p).startswith("pgtap") for p in paths)


def test_read_python_deps_pyproject_and_skip_continue(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = [\n  "sqlalchemy",\n]\n', encoding="utf-8"
    )
    (tmp_path / "requirements-dev.txt").write_text("django>=4\n", encoding="utf-8")
    # Skipped path must continue (not break) so requirements-dev still scanned.
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "requirements.txt").write_text("alembic\n", encoding="utf-8")
    # Put a skipped requirements at root via prefix match on a copy path:
    (tmp_path / "skipme").mkdir()
    # Use prefixes that skip nothing under root names we care about, then
    # also verify skip of a requirements file by prefix on its rel path.
    found = lg._read_python_deps(tmp_path, ())
    rels = {rel for rel, _ in found}
    assert "pyproject.toml" in rels
    assert "requirements-dev.txt" in rels
    assert {dep for _, deps in found for dep in deps} >= {"sqlalchemy", "django"}

    # First candidate skipped, second still collected (continue not break).
    (tmp_path / "requirements.txt").write_text("alembic==1\n", encoding="utf-8")
    found2 = lg._read_python_deps(tmp_path, ("pyproject.toml", "requirements-dev.txt"))
    rels2 = {rel for rel, _ in found2}
    assert "pyproject.toml" not in rels2
    assert "requirements-dev.txt" not in rels2
    assert "requirements.txt" in rels2
    assert any("alembic" in deps for _, deps in found2)


def test_run_gates_honor_non_default_context(tmp_path: Path, monkeypatch):
    """load_quality(root, context) must use the passed context (kill dropped-arg mutants)."""
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "a.spec.ts").write_text("test('a', async () => {})\n", encoding="utf-8")
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "t.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    # Default context: valid enabled auto + green command
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto",
            "mode": "hard",
            "test_command": "true",
            "source_globs": ["src/**"],
            "test_globs": ["e2e/**"],
        },
        db_tests={
            "enabled": "auto",
            "mode": "hard",
            "test_command": "true",
            "source_globs": ["**/migrations/**"],
            "test_globs": ["**/db/tests/**"],
        },
    )
    # Alternate context: enabled false without decision → must fail when selected
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
    assert any(
        f["kind"] == "disabled_without_decision"
        for f in _summary(tmp_path, "e2e")["findings"]
    )
    assert lg.run_db_tests_gate(tmp_path, context="context") == 0
    assert lg.run_db_tests_gate(tmp_path, context="ctx-alt") == 1
    assert any(
        f["kind"] == "disabled_without_decision"
        for f in _summary(tmp_path, "db_tests")["findings"]
    )


def test_db_gate_honors_section_skip_prefixes(tmp_path: Path, monkeypatch):
    """prefixes must come from section — None/default must not ignore skip_rel_prefixes."""
    _git_init(tmp_path)
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "t.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        db_tests={
            "enabled": "auto",
            "mode": "hard",
            "skip_rel_prefixes": ["db/"],
            "test_command": "true",
            "source_globs": ["**/migrations/**"],
            "test_globs": ["**/db/tests/**"],
        },
    )
    _commit_all(tmp_path, "init")
    monkeypatch.setenv("LAYER_GATES_BASE", "HEAD")
    assert lg.run_db_tests_gate(tmp_path) == 0
    summary = _summary(tmp_path, "db_tests")
    assert summary["skipped"] is True
    assert summary["reason"] == "layer_absent"


def test_e2e_gate_honors_section_skip_prefixes(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "a.spec.ts").write_text("test('a', async () => {})\n", encoding="utf-8")
    _write_quality(
        tmp_path,
        e2e={
            "enabled": "auto",
            "mode": "hard",
            "skip_rel_prefixes": ["playwright.config.ts", "e2e/"],
            "test_command": "true",
            "source_globs": ["src/**"],
            "test_globs": ["e2e/**"],
        },
    )
    _commit_all(tmp_path, "init")
    monkeypatch.setenv("LAYER_GATES_BASE", "HEAD")
    assert lg.run_e2e_gate(tmp_path) == 0
    summary = _summary(tmp_path, "e2e")
    assert summary["skipped"] is True
    assert summary["reason"] == "layer_absent"


def test_run_command_cwd_capture_and_limit(tmp_path: Path):
    assert lg._CMD_OUTPUT_LIMIT == 4000
    (tmp_path / "marker.txt").write_text("yes", encoding="utf-8")
    rc, out = lg._run_command(tmp_path, "test -f marker.txt && echo HELLO_GATE")
    assert rc == 0
    assert isinstance(out, str)
    assert "HELLO_GATE" in out
    rc_err, out_err = lg._run_command(tmp_path, "echo ERR_GATE 1>&2")
    assert rc_err == 0
    assert "ERR_GATE" in out_err
    rc_pwd, out_pwd = lg._run_command(tmp_path, "pwd")
    assert rc_pwd == 0
    assert tmp_path.resolve().as_posix() in out_pwd.replace("\\", "/")
    # Truncate to exact limit
    rc_big, out_big = lg._run_command(
        tmp_path, "python3 -c 'print(\"x\" * 5000)'"
    )
    assert rc_big == 0
    assert isinstance(out_big, str)
    assert len(out_big) == 4000


def test_detect_e2e_evidence_uses_path_key(tmp_path: Path):
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "hidden").mkdir()
    (tmp_path / "hidden" / "playwright.config.js").write_text("module.exports={}\n", encoding="utf-8")
    det = lg.detect_e2e(tmp_path, skip_prefixes=("hidden/",))
    assert det["present"] is True
    assert all("path" in e for e in det["evidence"])
    assert all("XXpathXX" not in e for e in det["evidence"])
    assert all(not str(e.get("path", "")).startswith("hidden/") for e in det["evidence"])
    assert any(e.get("path") == "playwright.config.ts" for e in det["evidence"])


def test_defaults_include_layer_gates_in_mutation_globs():
    cfg = defaults_fn()
    globs = list(cfg["mutation"]["include_globs"])
    assert globs.count("runtime/agentized/layer_gates.py") == 1
    ci = list(cfg["gates"]["ci"])
    assert ci.index("e2e") < ci.index("mutation")
    assert ci.index("db_tests") < ci.index("mutation")


def test_glob_and_enabled_helpers():
    assert lg._glob_match("e2e/a.ts", "e2e/**") is True
    assert lg._glob_match("db/migrations/001.sql", "**/migrations/**") is True
    assert lg._matches_any("src/app.ts", ["src/**"]) is True
    assert lg._enabled_mode(True) == "true"
    assert lg._enabled_mode(False) == "false"
    assert lg._enabled_mode("AUTO") == "auto"
    assert lg._enabled_mode("true") == "true"
    assert lg._glob_match("a.ts", "e2e/**") is False
    assert lg._glob_match("apps/web/e2e/a.ts", "**/e2e/**") is True
