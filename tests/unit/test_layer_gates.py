"""AGE-31a layer detection — exact evidence oracles (no gate runner yet)."""

from __future__ import annotations

import json
from pathlib import Path

from agentized import layer_gates as lg


def _pw_tree(root: Path) -> None:
    (root / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (root / "e2e").mkdir(exist_ok=True)
    (root / "e2e" / "a.spec.ts").write_text("test('a', async () => {})\n", encoding="utf-8")


def test_detect_e2e_exact_evidence(tmp_path: Path):
    _pw_tree(tmp_path)
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "1.0.0"}}), encoding="utf-8"
    )
    det = lg.detect_e2e(tmp_path, skip_prefixes=())
    assert det["present"] is True
    assert det["framework"] == "playwright"
    assert {"kind": "config", "path": "playwright.config.ts"} in det["evidence"]
    assert {
        "kind": "package_dep",
        "path": "package.json",
        "detail": "@playwright/test",
    } in det["evidence"]
    assert {"kind": "tests_dir", "path": "e2e"} in det["evidence"]
    # Nested web/e2e must report tests_dir "e2e" under web, not parent "web"
    # (kills cypress_e2e `and`→`or` false positives on */e2e/*).
    nested = tmp_path / "nested"
    (nested / "web" / "e2e").mkdir(parents=True)
    (nested / "web" / "e2e" / "a.spec.ts").write_text("test('a')\n", encoding="utf-8")
    nested_det = lg.detect_e2e(nested, skip_prefixes=())
    assert {"kind": "tests_dir", "path": "web/e2e"} in nested_det["evidence"]
    assert {"kind": "tests_dir", "path": "web"} not in nested_det["evidence"]
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "README.md").write_text("x\n", encoding="utf-8")
    absent = lg.detect_e2e(empty, skip_prefixes=())
    assert absent == {"present": False, "evidence": [], "framework": None}
    # Cypress: exact path cypress/e2e (not cypress alone).
    cy = tmp_path / "cy"
    (cy / "cypress" / "e2e").mkdir(parents=True)
    (cy / "cypress" / "e2e" / "a.cy.js").write_text("it('a', () => {})\n", encoding="utf-8")
    (cy / "cypress.config.js").write_text("module.exports = {}\n", encoding="utf-8")
    (cy / "package.json").write_text(
        json.dumps({"devDependencies": {"cypress": "13"}}), encoding="utf-8"
    )
    cy_det = lg.detect_e2e(cy, skip_prefixes=())
    assert cy_det["present"] is True and cy_det["framework"] == "cypress"
    assert {"kind": "tests_dir", "path": "cypress/e2e"} in cy_det["evidence"]
    assert {"kind": "config", "path": "cypress.config.js"} in cy_det["evidence"]
    assert {
        "kind": "package_dep",
        "path": "package.json",
        "detail": "cypress",
    } in cy_det["evidence"]
    # reports/e2e ignored; placeholder-only playwright/ absent.
    (tmp_path / "reports" / "e2e").mkdir(parents=True)
    (tmp_path / "reports" / "e2e" / "x.spec.ts").write_text("test('x')\n", encoding="utf-8")
    ph = tmp_path / "playwright_empty"
    (ph / "playwright").mkdir(parents=True)
    (ph / "playwright" / ".gitkeep").write_text("", encoding="utf-8")
    assert lg.detect_e2e(ph, skip_prefixes=())["present"] is False
    # continue (not break) past skipped prefix: later z_ok config still found.
    skip_root = tmp_path / "skip_walk"
    (skip_root / "a_skip").mkdir(parents=True)
    (skip_root / "a_skip" / "playwright.config.ts").write_text(
        "export default {}\n", encoding="utf-8"
    )
    (skip_root / "z_ok").mkdir(parents=True)
    (skip_root / "z_ok" / "playwright.config.js").write_text(
        "export default {}\n", encoding="utf-8"
    )
    skipped = lg.detect_e2e(skip_root, skip_prefixes=("a_skip/",))
    assert {"kind": "config", "path": "z_ok/playwright.config.js"} in skipped["evidence"]
    assert skipped["present"] is True
    # Empty e2e dir then later real e2e: continue (not break) on empty dir_rel.
    empty_then = tmp_path / "empty_then"
    (empty_then / "a_empty" / "e2e").mkdir(parents=True)
    (empty_then / "a_empty" / "e2e" / ".gitkeep").write_text("", encoding="utf-8")
    (empty_then / "z_real" / "e2e").mkdir(parents=True)
    (empty_then / "z_real" / "e2e" / "a.spec.ts").write_text("test('a')\n", encoding="utf-8")
    # Touch a file under a_empty/e2e path walk: use a real file path that references empty dir
    # via sibling; detection walks z_real file and a_empty placeholder-only.
    et = lg.detect_e2e(empty_then, skip_prefixes=())
    assert {"kind": "tests_dir", "path": "z_real/e2e"} in et["evidence"]
    assert {"kind": "tests_dir", "path": "a_empty/e2e"} not in et["evidence"]
    # Multi-dep join oracle (kills ",".join → "XX,XX".join).
    multi_pkg = tmp_path / "multi_pkg"
    multi_pkg.mkdir()
    (multi_pkg / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "1", "cypress": "1"}}),
        encoding="utf-8",
    )
    multi_det = lg.detect_e2e(multi_pkg, skip_prefixes=())
    assert {
        "kind": "package_dep",
        "path": "package.json",
        "detail": "@playwright/test,cypress",
    } in multi_det["evidence"]
    # skip_prefixes=None uses agentized defaults; explicit () does not.
    dog = tmp_path / "dogfood"
    (dog / "runtime" / "agentized").mkdir(parents=True)
    (dog / "templates" / "quality").mkdir(parents=True)
    (dog / "templates" / "e2e").mkdir(parents=True)
    (dog / "templates" / "e2e" / "a.spec.ts").write_text("test('a')\n", encoding="utf-8")
    none_det = lg.detect_e2e(dog)  # skip_prefixes=None → skips templates/
    assert none_det["present"] is False
    empty_skip = lg.detect_e2e(dog, skip_prefixes=())
    assert empty_skip["present"] is True
    assert {"kind": "tests_dir", "path": "templates/e2e"} in empty_skip["evidence"]
    assert lg.default_test_command("e2e", {"framework": "playwright"}) == "npx playwright test"
    assert lg.default_test_command("e2e", {"framework": "cypress"}) == "npx cypress run"
    assert lg.default_test_command("e2e", {"framework": None}) is None
    assert lg.default_test_command("other", {"framework": "playwright"}) is None


def test_detect_db_exact_evidence(tmp_path: Path):
    mig = tmp_path / "db" / "migrations"
    mig.mkdir(parents=True)
    (mig / ".gitkeep").write_text("", encoding="utf-8")
    (mig / "001.sql").write_text("CREATE TABLE t(id int);\n", encoding="utf-8")
    tests = tmp_path / "db" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_t.sql").write_text("SELECT plan(1);\n", encoding="utf-8")
    (tmp_path / "schema.sql").write_text("CREATE TABLE x(id int);\n", encoding="utf-8")
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (tmp_path / "schema.prisma").write_text("model T { id Int }\n", encoding="utf-8")
    pgt = tmp_path / "pgtap"
    pgt.mkdir()
    (pgt / "t.sql").write_text("x", encoding="utf-8")
    ws = tmp_path / "flyway" / "sql"
    ws.mkdir(parents=True)
    (ws / "blank.sql").write_text("\n\n", encoding="utf-8")
    det = lg.detect_db_layer(tmp_path)
    assert det["present"] is True
    assert det["framework"] == "pgtap"
    assert {"kind": "migrations_dir", "path": "db/migrations"} in det["evidence"]
    assert {"kind": "marker_file", "path": "schema.sql"} in det["evidence"]
    assert {"kind": "marker_file", "path": "alembic.ini"} in det["evidence"]
    assert {"kind": "marker_file", "path": "schema.prisma"} in det["evidence"]
    assert {"kind": "pgtap_dir", "path": "pgtap"} in det["evidence"]
    assert {"kind": "pgtap_sql", "path": "db/tests/test_t.sql"} in det["evidence"]
    assert {"kind": "migrations_dir", "path": "flyway/sql"} not in det["evidence"]
    # continue past skipped prefix + later zzz marker still found (kills break).
    (tmp_path / "a_skip").mkdir()
    (tmp_path / "a_skip" / "x.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "zzz_extra.sql").write_text("SELECT plan(9);\n", encoding="utf-8")
    walked = lg.detect_db_layer(tmp_path, skip_prefixes=("a_skip/",))
    assert {"kind": "migrations_dir", "path": "db/migrations"} in walked["evidence"]
    assert {"kind": "pgtap_sql", "path": "zzz_extra.sql"} in walked["evidence"]
    # placeholder then real sibling: continue (not break) on .gitkeep
    ph = tmp_path / "ph_mig" / "db" / "migrations"
    ph.mkdir(parents=True)
    (ph / ".gitkeep").write_text("", encoding="utf-8")
    (ph / "002.sql").write_text("CREATE TABLE u(id int);\n", encoding="utf-8")
    ph_det = lg.detect_db_layer(tmp_path / "ph_mig", skip_prefixes=())
    assert {"kind": "migrations_dir", "path": "db/migrations"} in ph_det["evidence"]
    # empty-file then real: continue not break; size==0 oracle
    empty_mig = tmp_path / "empty_mig" / "db" / "migrations"
    empty_mig.mkdir(parents=True)
    (empty_mig / "000.sql").write_text("", encoding="utf-8")
    (empty_mig / "003.sql").write_text("CREATE TABLE v(id int);\n", encoding="utf-8")
    assert {
        "kind": "migrations_dir",
        "path": "db/migrations",
    } in lg.detect_db_layer(tmp_path / "empty_mig", skip_prefixes=())["evidence"]
    # OSError on first migration file then real sibling (continue≠break)
    os_mig = tmp_path / "os_mig" / "db" / "migrations"
    os_mig.mkdir(parents=True)
    locked_sql = os_mig / "000.sql"
    locked_sql.write_text("x\n", encoding="utf-8")
    locked_sql.chmod(0o000)
    (os_mig / "001.sql").write_text("CREATE TABLE w(id int);\n", encoding="utf-8")
    try:
        assert {
            "kind": "migrations_dir",
            "path": "db/migrations",
        } in lg.detect_db_layer(tmp_path / "os_mig", skip_prefixes=())["evidence"]
    finally:
        locked_sql.chmod(0o644)
    mono = tmp_path / "mono"
    (mono / "apps" / "web" / "e2e").mkdir(parents=True)
    (mono / "apps" / "web" / "playwright.config.ts").write_text(
        "export default {}\n", encoding="utf-8"
    )
    (mono / "apps" / "web" / "e2e" / "h.spec.ts").write_text(
        "test('h', async () => {})\n", encoding="utf-8"
    )
    (mono / "services" / "api" / "db" / "migrations").mkdir(parents=True)
    (mono / "services" / "api" / "db" / "migrations" / "001.sql").write_text(
        "SELECT 1;\n", encoding="utf-8"
    )
    assert lg.detect_e2e(mono, skip_prefixes=())["present"] is True
    assert {
        "kind": "migrations_dir",
        "path": "services/api/db/migrations",
    } in lg.detect_db_layer(mono, skip_prefixes=())["evidence"]
    orm = tmp_path / "orm"
    orm.mkdir()
    (orm / "package.json").write_text(
        json.dumps({"dependencies": {"prisma": "5"}}), encoding="utf-8"
    )
    (orm / "db" / "tests").mkdir(parents=True)
    (orm / "db" / "tests" / "t.sql").write_text("SELECT 1;\n", encoding="utf-8")
    orm_det = lg.detect_db_layer(orm, skip_prefixes=())
    assert orm_det["present"] is True and orm_det["framework"] == "prisma"
    assert {"kind": "orm_dep", "path": "package.json", "detail": "prisma"} in orm_det["evidence"]
    tap_only = tmp_path / "tap_only"
    tap_only.mkdir()
    (tap_only / "a.sql").write_text("tap: 1\n", encoding="utf-8")
    tap_det = lg.detect_db_layer(tap_only, skip_prefixes=())
    assert tap_det["present"] is True
    assert tap_det["evidence"] == [{"kind": "pgtap_sql", "path": "a.sql"}]
    assert tap_det["framework"] == "pgtap"
    pg_only = tmp_path / "pg_only"
    pg_only.mkdir()
    (pg_only / "b.sql").write_text("uses pgtap helpers\n", encoding="utf-8")
    assert {"kind": "pgtap_sql", "path": "b.sql"} in lg.detect_db_layer(pg_only, skip_prefixes=())[
        "evidence"
    ]
    bin_sql = tmp_path / "bin_sql"
    bin_sql.mkdir()
    (bin_sql / "c.sql").write_bytes(b"SELECT plan(1);\n\xff\xfe\n")
    assert {"kind": "pgtap_sql", "path": "c.sql"} in lg.detect_db_layer(bin_sql, skip_prefixes=())[
        "evidence"
    ]
    # Truncation: '(' of select plan( sits at index 4000 — [:4000] misses, [:4001] hits.
    long_sql = tmp_path / "long_sql"
    long_sql.mkdir()
    (long_sql / "late.sql").write_bytes(b"x" * 3989 + b"select plan(1);\n")
    assert {"kind": "pgtap_sql", "path": "late.sql"} not in lg.detect_db_layer(
        long_sql, skip_prefixes=()
    )["evidence"]
    (long_sql / "early.sql").write_bytes(b"x" * 3988 + b"select plan(1);\n")
    assert {"kind": "pgtap_sql", "path": "early.sql"} in lg.detect_db_layer(
        long_sql, skip_prefixes=()
    )["evidence"]
    bad_sql = tmp_path / "bad_sql"
    bad_sql.mkdir()
    nop = bad_sql / "a.sql"
    nop.write_text("x\n", encoding="utf-8")
    nop.chmod(0o000)
    (bad_sql / "z.sql").write_text("SELECT plan(2);\n", encoding="utf-8")
    try:
        bad_det = lg.detect_db_layer(bad_sql, skip_prefixes=())
    finally:
        nop.chmod(0o644)
    assert {"kind": "pgtap_sql", "path": "z.sql"} in bad_det["evidence"]
    pyorm = tmp_path / "pyorm"
    pyorm.mkdir()
    (pyorm / "requirements.txt").write_text("sqlalchemy\n", encoding="utf-8")
    py_det = lg.detect_db_layer(pyorm, skip_prefixes=())
    assert py_det["present"] is True
    assert {"kind": "orm_dep", "path": "requirements.txt", "detail": "sqlalchemy"} in py_det[
        "evidence"
    ]
    multi = tmp_path / "multi_js"
    multi.mkdir()
    (multi / "package.json").write_text(
        json.dumps({"dependencies": {"prisma": "1", "drizzle-orm": "1"}}), encoding="utf-8"
    )
    mdet = lg.detect_db_layer(multi, skip_prefixes=())
    assert {"kind": "orm_dep", "path": "package.json", "detail": "drizzle-orm,prisma"} in mdet[
        "evidence"
    ]
    sql_only = tmp_path / "sql_only"
    (sql_only / "db" / "migrations").mkdir(parents=True)
    (sql_only / "db" / "migrations" / "001.sql").write_text(
        "CREATE TABLE a(id int);\n", encoding="utf-8"
    )
    sql_det = lg.detect_db_layer(sql_only, skip_prefixes=())
    assert sql_det["present"] is True and sql_det["framework"] == "sql"
    # skip_prefixes=None skips templates; explicit () keeps them.
    dog = tmp_path / "dog_db"
    (dog / "runtime" / "agentized").mkdir(parents=True)
    (dog / "templates" / "quality").mkdir(parents=True)
    (dog / "templates" / "db" / "migrations").mkdir(parents=True)
    (dog / "templates" / "db" / "migrations" / "001.sql").write_text(
        "CREATE TABLE t(id int);\n", encoding="utf-8"
    )
    dog_none = lg.detect_db_layer(dog)
    assert dog_none["present"] is False
    dog_empty = lg.detect_db_layer(dog, skip_prefixes=())
    assert dog_empty["present"] is True
    assert {
        "kind": "migrations_dir",
        "path": "templates/db/migrations",
    } in dog_empty["evidence"]
    # multi python deps join
    multi_py = tmp_path / "multi_py"
    multi_py.mkdir()
    (multi_py / "requirements.txt").write_text("django\nalembic\n", encoding="utf-8")
    mp = lg.detect_db_layer(multi_py, skip_prefixes=())
    assert {
        "kind": "orm_dep",
        "path": "requirements.txt",
        "detail": "alembic,django",
    } in mp["evidence"]
    sb = tmp_path / "sb"
    (sb / "supabase").mkdir(parents=True)
    (sb / "supabase" / "config.toml").write_text("[db]\n", encoding="utf-8")
    assert lg._has_supabase(sb) is True
    assert (
        lg.default_test_command("db_tests", {"framework": "pgtap"}, root=sb) == "supabase test db"
    )
    assert (
        lg.default_test_command("db_tests", {"framework": "pgtap"})
        == "pg_prove db/tests/*.sql tests/db/*.sql pgtap/*.sql"
    )
    assert lg.default_test_command("db_tests", {"framework": "sql"}) is None


def test_framework_helpers_missing_keys():
    assert lg._db_framework([{"kind": "pgtap_sql", "path": "t.sql"}]) == "pgtap"
    assert lg._db_framework([{"kind": "pgtap_dir", "path": "pgtap"}]) == "pgtap"
    assert (
        lg._db_framework([{"kind": "orm_dep", "path": "package.json", "detail": "prisma"}])
        == "prisma"
    )
    assert (
        lg._db_framework([{"kind": "orm_dep", "path": "p.json", "detail": "drizzle-orm"}])
        == "drizzle"
    )
    assert (
        lg._db_framework([{"kind": "orm_dep", "path": "requirements.txt", "detail": "alembic"}])
        == "alembic"
    )
    assert (
        lg._db_framework([{"kind": "orm_dep", "path": "requirements.txt", "detail": "sqlalchemy"}])
        == "alembic"
    )
    assert (
        lg._db_framework([{"kind": "orm_dep", "path": "requirements.txt", "detail": "django"}])
        == "django"
    )
    assert lg._db_framework([{"kind": "migrations_dir", "path": "db/migrations"}]) == "sql"
    assert lg._db_framework([{"kind": "marker_file", "path": "schema.sql"}]) == "sql"
    assert lg._db_framework([{"kind": "db_tests_dir", "path": "db/tests"}]) == "sql"
    # orm_dep alone (no path/detail tokens) still sql via kinds ∩ orm_dep
    assert lg._db_framework([{"kind": "orm_dep"}]) == "sql"
    assert lg._db_framework([]) is None
    assert lg._db_framework([{"kind": "other", "path": "x"}]) is None
    assert lg._e2e_framework([{"kind": "config", "path": "playwright.config.ts"}]) == "playwright"
    assert (
        lg._e2e_framework([{"kind": "package_dep", "path": "package.json", "detail": "cypress"}])
        == "cypress"
    )
    assert lg._e2e_framework([{"kind": "config", "path": "vite.config.ts"}]) is None
    # Missing path/detail must not invent framework tokens via bad defaults.
    assert lg._e2e_framework([{"kind": "config"}]) is None
    assert lg._db_framework([{"kind": "marker_file"}]) == "sql"
    assert lg._evidence_blob([{"path": "A", "detail": "B"}, {"path": "C"}]) == "a b c "


def test_skip_prefixes_agentized_only(tmp_path: Path):
    (tmp_path / "templates" / "e2e").mkdir(parents=True)
    (tmp_path / "templates" / "e2e" / "a.spec.ts").write_text("test('a')\n", encoding="utf-8")
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    assert lg.is_agentized_repo(tmp_path) is False
    assert lg.skip_rel_prefixes(tmp_path) == ()
    assert lg.detect_e2e(tmp_path)["present"] is True
    (tmp_path / "templates" / "quality").mkdir(parents=True)
    assert lg.is_agentized_repo(tmp_path) is False
    (tmp_path / "agentized").mkdir()
    assert lg.is_agentized_repo(tmp_path) is True
    (tmp_path / "agentized").rmdir()
    (tmp_path / "runtime" / "agentized").mkdir(parents=True)
    assert lg.is_agentized_repo(tmp_path) is True
    assert lg.skip_rel_prefixes(tmp_path) == ("templates/", "tests/fixtures/")
    assert lg.skip_rel_prefixes(tmp_path, {"skip_rel_prefixes": ["vendor/"]}) == ("vendor/",)
    only_tpl = tmp_path / "only_tpl"
    (only_tpl / "templates" / "quality").mkdir(parents=True)
    (only_tpl / "runtime" / "agentized").mkdir(parents=True)
    (only_tpl / "templates" / "e2e").mkdir(parents=True)
    (only_tpl / "templates" / "e2e" / "a.spec.ts").write_text("test('a')\n", encoding="utf-8")
    assert lg.detect_e2e(only_tpl)["present"] is False


def test_helpers_deps_paths_and_skip(tmp_path: Path):
    assert lg._JSON_ENCODING == "utf-8"
    assert lg._normalize_rel(r"db\migrations/") == "db/migrations"
    assert lg._normalize_rel("db/migrations") == "db/migrations"
    assert lg._normalize_rel("foo/X") == "foo/X"
    assert lg._looks_like_db_dir("db/migrations/") == "migrations_dir"
    assert lg._looks_like_db_dir("pgtap") == "pgtap_dir"
    assert lg._looks_like_db_dir("pgtap/") == "pgtap_dir"
    assert lg._looks_like_db_dir("vendor/pgtap") == "pgtap_dir"
    assert lg._looks_like_db_dir("tests/db") == "db_tests_dir"
    assert lg._looks_like_db_dir("tests/sql") == "db_tests_dir"
    assert lg._looks_like_db_dir("db/tests") == "db_tests_dir"
    assert lg._looks_like_db_dir("src/components") is None
    # _is_skipped_rel: backslash normalize + trailing-slash prefix equality
    assert lg._is_skipped_rel(r"templates\e2e\a.ts", ("templates/",)) is True
    assert lg._is_skipped_rel("templates", ("templates/",)) is True
    assert lg._is_skipped_rel("libX", ("libX/",)) is True
    assert lg._is_skipped_rel("templates_other/x", ("templates/",)) is False
    assert lg._is_skipped_rel("vendor/x", ("vendor",)) is True
    # _uniq_evidence: .get without defaults → None for missing keys
    assert lg._uniq_evidence(
        [{"kind": "a", "path": "1"}, {"kind": "a", "path": "1"}, {"kind": "b", "path": "2"}]
    ) == [{"kind": "a", "path": "1"}, {"kind": "b", "path": "2"}]
    assert lg._uniq_evidence([{"path": "1"}, {"kind": "a"}]) == [{"path": "1"}, {"kind": "a"}]
    assert lg._uniq_evidence([{}, {}]) == [{}]
    # missing kind is None, not "XXXX"/"" — keep distinct from explicit kind
    assert len(lg._uniq_evidence([{"path": "1"}, {"kind": "XXXX", "path": "1"}])) == 2
    assert len(lg._uniq_evidence([{"path": "1"}, {"kind": None, "path": "1"}])) == 1
    assert lg._is_skipped_rel("libY/a.ts", ("libX/",)) is False
    assert lg._is_skipped_rel("libX/a.ts", ("libX/",)) is True
    path = tmp_path / "package.json"
    path.write_bytes(
        json.dumps(
            {
                "dependencies": {"prisma": "1"},
                "devDependencies": {"@playwright/test": "1"},
                "peerDependencies": {"cypress": "1"},
                "optionalDependencies": {"drizzle-orm": "1"},
            }
        ).encode("utf-8")
    )
    assert lg._read_package_deps(path) == {"prisma", "@playwright/test", "cypress", "drizzle-orm"}
    assert lg._read_package_deps(tmp_path / "missing.json") == set()
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert lg._read_package_deps(tmp_path / "bad.json") == set()
    (tmp_path / "arr.json").write_text("[]", encoding="utf-8")
    assert lg._read_package_deps(tmp_path / "arr.json") == set()
    py = tmp_path / "py"
    py.mkdir()
    (py / "pyproject.toml").write_text(
        '[project]\ndependencies = [\n  "sqlalchemy",\n]\n', encoding="utf-8"
    )
    (py / "requirements.txt").write_text("alembic==1\n", encoding="utf-8")
    found = lg._read_python_deps(py, ("pyproject.toml",))
    assert "requirements.txt" in {rel for rel, _ in found}
    assert any("alembic" in names for _, names in found)
    found2 = lg._read_python_deps(py, ())
    assert {rel for rel, _ in found2} >= {"pyproject.toml", "requirements.txt"}
    assert any("sqlalchemy" in names for _, names in found2)
    req_only = tmp_path / "req_only"
    req_only.mkdir()
    (req_only / "requirements.txt").write_text("django\n", encoding="utf-8")
    (req_only / "requirements-bin.txt").write_bytes(b"alembic==1\n\xff\xfe\n")
    noperm = req_only / "requirements-noperm.txt"
    noperm.write_text("unused\n", encoding="utf-8")
    noperm.chmod(0o000)
    try:
        found3 = lg._read_python_deps(req_only, ())
    finally:
        noperm.chmod(0o644)
    assert {rel for rel, _ in found3} >= {"requirements.txt", "requirements-bin.txt"}
    assert any("django" in n for _, n in found3) and any("alembic" in n for _, n in found3)
    qonly = tmp_path / "qonly"
    qonly.mkdir()
    (qonly / "pyproject.toml").write_text(
        "install_requires=[\"django\", 'alembic']\n", encoding="utf-8"
    )
    found4 = lg._read_python_deps(qonly, ())
    names4 = set().union(*(n for _, n in found4))
    assert names4 == {"django", "alembic"}
    d = tmp_path / "dircheck"
    (d / "e2e").mkdir(parents=True)
    (d / "e2e" / ".keep").write_text("", encoding="utf-8")
    assert lg._dir_has_real_files(d, "e2e", ()) is False
    (d / "e2e" / "a.spec.ts").write_text("test('a')\n", encoding="utf-8")
    assert lg._dir_has_real_files(d, "e2e", ()) is True
    assert lg._dir_has_real_files(d, "e2e", ("e2e/",)) is False
    assert lg._dir_has_real_files(d, "missing", ()) is False
    # nested dir before file still finds real file
    nest = tmp_path / "nest" / "e2e" / "deep"
    nest.mkdir(parents=True)
    (nest / "x.spec.ts").write_text("test('x')\n", encoding="utf-8")
    assert lg._dir_has_real_files(tmp_path / "nest", "e2e", ()) is True
    # skipped vendor/ path then real sibling (continue≠break on SKIP_DIR_NAMES)
    vd = tmp_path / "vend" / "e2e"
    (vd / "vendor").mkdir(parents=True)
    (vd / "vendor" / "x.ts").write_text("test('x')\n", encoding="utf-8")
    (vd / "z.ts").write_text("test('z')\n", encoding="utf-8")
    assert lg._dir_has_real_files(tmp_path / "vend", "e2e", ()) is True
    # size-1 whitespace-only then real later file
    ws = tmp_path / "wsdir" / "e2e"
    ws.mkdir(parents=True)
    (ws / "a_blank.ts").write_text(" ", encoding="utf-8")
    (ws / "z_real.ts").write_text("test('z')\n", encoding="utf-8")
    assert lg._dir_has_real_files(tmp_path / "wsdir", "e2e", ()) is True
    # lone size-1 non-whitespace must count (kills st_size==0 → ==1)
    one = tmp_path / "onedir" / "e2e"
    one.mkdir(parents=True)
    (one / "x.ts").write_bytes(b"x")
    assert lg._dir_has_real_files(tmp_path / "onedir", "e2e", ()) is True
    # skip prefix on first file, real later sibling (continue≠break)
    sk = tmp_path / "skipdir" / "e2e"
    sk.mkdir(parents=True)
    (sk / "a_skip.ts").write_text("test('a')\n", encoding="utf-8")
    (sk / "z_ok.ts").write_text("test('z')\n", encoding="utf-8")
    assert lg._dir_has_real_files(tmp_path / "skipdir", "e2e", ("e2e/a_skip.ts",)) is True
    assert lg._dir_has_real_files(tmp_path / "skipdir", "e2e", ("e2e/",)) is False
    # placeholder then real (continue≠break)
    ph2 = tmp_path / "ph2" / "e2e"
    ph2.mkdir(parents=True)
    (ph2 / ".gitkeep").write_text("", encoding="utf-8")
    (ph2 / "z.ts").write_text("test('z')\n", encoding="utf-8")
    assert lg._dir_has_real_files(tmp_path / "ph2", "e2e", ()) is True
    # empty size-0 then real (continue≠break)
    em = tmp_path / "emdir" / "e2e"
    em.mkdir(parents=True)
    (em / "a_empty.ts").write_text("", encoding="utf-8")
    (em / "z.ts").write_text("test('z')\n", encoding="utf-8")
    assert lg._dir_has_real_files(tmp_path / "emdir", "e2e", ()) is True
    # whitespace-only then real (continue≠break on strip-empty)
    ws2 = tmp_path / "ws2" / "e2e"
    ws2.mkdir(parents=True)
    (ws2 / "a_ws.ts").write_text("\n\n", encoding="utf-8")
    (ws2 / "z.ts").write_text("test('z')\n", encoding="utf-8")
    assert lg._dir_has_real_files(tmp_path / "ws2", "e2e", ()) is True
    # OSError on first file must continue to later readable sibling
    locked = tmp_path / "lockdir" / "e2e"
    locked.mkdir(parents=True)
    bad = locked / "a_locked.ts"
    bad.write_text("x\n", encoding="utf-8")
    bad.chmod(0o000)
    (locked / "z_ok.ts").write_text("test('z')\n", encoding="utf-8")
    try:
        assert lg._dir_has_real_files(tmp_path / "lockdir", "e2e", ()) is True
    finally:
        bad.chmod(0o644)
    assert lg._decode_text(tmp_path / "arr.json") == "[]"
    assert lg._evidence_blob([{"path": None}]) == " "
