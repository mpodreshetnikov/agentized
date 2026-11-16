"""Unit tests for e2e / DB layer auto-detect hard gates (AGE-31)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agentized import layer_gates as lg


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init", "--allow-empty"], cwd=root, check=True, capture_output=True)


def _commit_all(root: Path, msg: str = "chg") -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg, "--allow-empty"], cwd=root, check=True, capture_output=True)


def test_detect_e2e_playwright_and_package(tmp_path: Path):
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "1.0.0"}}),
        encoding="utf-8",
    )
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "a.spec.ts").write_text("test('x', async () => {})\n", encoding="utf-8")
    det = lg.detect_e2e(tmp_path)
    assert det["present"] is True
    kinds = sorted({e["kind"] for e in det["evidence"]})
    assert kinds == ["config", "package_dep", "tests_dir"]
    assert any(e.get("path") == "playwright.config.ts" for e in det["evidence"])


def test_detect_e2e_absent(tmp_path: Path):
    (tmp_path / "README.md").write_text("no ui\n", encoding="utf-8")
    det = lg.detect_e2e(tmp_path)
    assert det["present"] is False
    assert det["evidence"] == []


def test_detect_db_migrations_and_pgtap(tmp_path: Path):
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE t(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_t.sql").write_text("SELECT plan(1);\nSELECT has_table('t');\n", encoding="utf-8")
    det = lg.detect_db_layer(tmp_path)
    kinds = sorted({e["kind"] for e in det["evidence"]})
    paths = sorted({e["path"] for e in det["evidence"]})
    assert kinds == ["db_tests_dir", "migrations_dir", "pgtap_sql"]
    assert paths == ["db/migrations", "db/tests", "db/tests/test_t.sql"]


def test_detect_db_absent(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    det = lg.detect_db_layer(tmp_path)
    assert det["present"] is False
    assert det["evidence"] == []


def test_e2e_gate_skips_when_absent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lg, "load_quality", lambda *a, **k: {"e2e": {"enabled": "auto", "mode": "hard"}})
    assert lg.run_e2e_gate(tmp_path) == 0
    summary = json.loads((tmp_path / "reports/e2e/e2e-summary.json").read_text(encoding="utf-8"))
    assert summary["skipped"] is True
    assert summary["reason"] == "layer_absent"


def test_e2e_gate_disabled(tmp_path: Path, monkeypatch):
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    monkeypatch.setattr(lg, "load_quality", lambda *a, **k: {"e2e": {"enabled": False, "mode": "hard"}})
    assert lg.run_e2e_gate(tmp_path) == 0
    summary = json.loads((tmp_path / "reports/e2e/e2e-summary.json").read_text(encoding="utf-8"))
    assert summary["reason"] == "disabled"


def test_e2e_requires_tests_for_changed_sources(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok', async () => {})\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const a = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (tmp_path / "src" / "app.ts").write_text("export const a = 2\n", encoding="utf-8")
    _commit_all(tmp_path, "ui")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    monkeypatch.setattr(
        lg,
        "load_quality",
        lambda *a, **k: {
            "e2e": {
                "enabled": "auto",
                "mode": "hard",
                "require_tests_for_changed": True,
                "source_globs": ["src/**"],
                "test_globs": ["e2e/**"],
            }
        },
    )
    assert lg.run_e2e_gate(tmp_path) == 1
    summary = json.loads((tmp_path / "reports/e2e/e2e-summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] is False
    assert any(f["kind"] == "tests_not_updated" for f in summary["findings"])


def test_e2e_pass_when_tests_updated(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok', async () => {})\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const a = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (tmp_path / "src" / "app.ts").write_text("export const a = 2\n", encoding="utf-8")
    (tmp_path / "e2e" / "ok.spec.ts").write_text("test('ok2', async () => {})\n", encoding="utf-8")
    _commit_all(tmp_path, "ui+e2e")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    monkeypatch.setattr(
        lg,
        "load_quality",
        lambda *a, **k: {
            "e2e": {
                "enabled": "auto",
                "mode": "hard",
                "require_tests_for_changed": True,
                "source_globs": ["src/**"],
                "test_globs": ["e2e/**"],
            }
        },
    )
    assert lg.run_e2e_gate(tmp_path) == 0
    summary = json.loads((tmp_path / "reports/e2e/e2e-summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] is True
    assert summary["skipped"] is False


def test_e2e_missing_tests_entirely(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "cypress.config.js").write_text("module.exports = {}\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.ts").write_text("export {}\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (tmp_path / "src" / "x.ts").write_text("export const x = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "ui")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    monkeypatch.setattr(
        lg,
        "load_quality",
        lambda *a, **k: {
            "e2e": {
                "enabled": "auto",
                "mode": "hard",
                "source_globs": ["src/**"],
                "test_globs": ["e2e/**", "cypress/e2e/**"],
            }
        },
    )
    assert lg.run_e2e_gate(tmp_path) == 1
    summary = json.loads((tmp_path / "reports/e2e/e2e-summary.json").read_text(encoding="utf-8"))
    assert any(f["kind"] == "missing_tests" for f in summary["findings"])


def test_db_gate_requires_tests_for_migration_change(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_a.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (mig / "002.sql").write_text("CREATE TABLE b(id int);\n", encoding="utf-8")
    _commit_all(tmp_path, "mig")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    monkeypatch.setattr(
        lg,
        "load_quality",
        lambda *a, **k: {
            "db_tests": {
                "enabled": "auto",
                "mode": "hard",
                "require_tests_for_changed": True,
                "source_globs": ["**/migrations/**"],
                "test_globs": ["**/db/tests/**"],
            }
        },
    )
    assert lg.run_db_tests_gate(tmp_path) == 1
    summary = json.loads(
        (tmp_path / "reports/db_tests/db_tests-summary.json").read_text(encoding="utf-8")
    )
    assert any(f["kind"] == "tests_not_updated" for f in summary["findings"])


def test_db_gate_pass_with_test_update(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_a.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (mig / "002.sql").write_text("CREATE TABLE b(id int);\n", encoding="utf-8")
    (tests / "test_b.sql").write_text("SELECT plan(1);\nSELECT has_table('b');\n", encoding="utf-8")
    _commit_all(tmp_path, "mig+test")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    monkeypatch.setattr(
        lg,
        "load_quality",
        lambda *a, **k: {
            "db_tests": {
                "enabled": "auto",
                "mode": "hard",
                "require_tests_for_changed": True,
                "source_globs": ["**/migrations/**"],
                "test_globs": ["**/db/tests/**"],
            }
        },
    )
    assert lg.run_db_tests_gate(tmp_path) == 0


def test_db_gate_warn_mode_does_not_fail(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001.sql").write_text("CREATE TABLE a(id int);\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (mig / "002.sql").write_text("CREATE TABLE b(id int);\n", encoding="utf-8")
    _commit_all(tmp_path, "mig")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    monkeypatch.setattr(
        lg,
        "load_quality",
        lambda *a, **k: {
            "db_tests": {
                "enabled": "auto",
                "mode": "warn",
                "source_globs": ["**/migrations/**"],
                "test_globs": ["**/db/tests/**"],
            }
        },
    )
    assert lg.run_db_tests_gate(tmp_path) == 0


def test_test_command_failure(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "a.spec.ts").write_text("x\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (tmp_path / "src" / "a.ts").write_text("export const a=1\n", encoding="utf-8")
    (tmp_path / "e2e" / "a.spec.ts").write_text("y\n", encoding="utf-8")
    _commit_all(tmp_path, "both")
    monkeypatch.setenv("LAYER_GATES_BASE", base)
    monkeypatch.setattr(
        lg,
        "load_quality",
        lambda *a, **k: {
            "e2e": {
                "enabled": "auto",
                "mode": "hard",
                "source_globs": ["src/**"],
                "test_globs": ["e2e/**"],
                "test_command": "false",
            }
        },
    )
    assert lg.run_e2e_gate(tmp_path) == 1
    summary = json.loads((tmp_path / "reports/e2e/e2e-summary.json").read_text(encoding="utf-8"))
    assert any(f["kind"] == "test_command_failed" for f in summary["findings"])


def test_fixture_orbit_like_mini_detects_both():
    root = Path(__file__).resolve().parents[2]
    fixture = root / "templates" / "quality" / "fixtures" / "orbit-like-mini"
    assert fixture.is_dir()
    e2e = lg.detect_e2e(fixture)
    db = lg.detect_db_layer(fixture)
    assert e2e["present"] is True
    assert db["present"] is True


def test_host_repo_ignores_templates_fixture(tmp_path: Path):
    """Shipping orbit-like-mini under templates/ must not mark the host as e2e/DB."""
    fixture_src = Path(__file__).resolve().parents[2] / "templates" / "quality" / "fixtures" / "orbit-like-mini"
    dest = tmp_path / "templates" / "quality" / "fixtures" / "orbit-like-mini"
    dest.parent.mkdir(parents=True)
    # shallow copy of markers
    import shutil

    shutil.copytree(fixture_src, dest)
    (tmp_path / "README.md").write_text("host\n", encoding="utf-8")
    e2e = lg.detect_e2e(tmp_path)
    db = lg.detect_db_layer(tmp_path)
    assert [e.get("path") for e in e2e["evidence"]] == []
    assert [e.get("path") for e in db["evidence"]] == []
    assert int(e2e["present"]) + int(db["present"]) == 0


def test_glob_match_helpers():
    assert lg._glob_match("e2e/a.ts", "e2e/**")
    assert lg._glob_match("db/migrations/001.sql", "**/migrations/**")
    assert lg._matches_any("src/app.ts", ["src/**"])
    assert not lg._matches_any("lib/x.ts", ["src/**"])


def test_enabled_mode_parsing():
    assert lg._enabled_mode(True) == "true"
    assert lg._enabled_mode(False) == "false"
    assert lg._enabled_mode("AUTO") == "auto"
