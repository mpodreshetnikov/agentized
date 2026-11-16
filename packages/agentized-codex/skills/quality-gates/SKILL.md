---
name: quality-gates
description: High-signal testing strategy and Agentized coverage/mutation/e2e/DB hard gates. Use when writing tests, configuring modules, or running quality check / pre-push / CI.
---

# High-signal testing & quality gates

## Test-writing rules (Orbit / Maxim)

1. **Do not mock the module under test.** Fake collaborators at the boundary; exercise real MUT code.
2. **Weak checks cannot be the primary oracle.** Truthy / `is not None` / substring / mock-call-only asserts are supporting signals at best — the test must assert observable behavior.
3. **The test must fail when the logic breaks.** Prefer arranging inputs that distinguish correct vs incorrect results.
4. **Do not mirror production formulas in tests.** Compute expected values from first principles or fixtures, not by copying the implementation.
5. **Shared fixtures when logic is duplicated.** If two places implement the same rule, both must assert against the same shared fixture/table (see `shared_fixtures` in `context/quality.json`).

## E2E tests (when UI / Playwright etc. is present)

Auto-detect: Playwright / Cypress / Nightwatch / WebdriverIO configs or deps, or `e2e/` / `tests/e2e/` / `cypress/e2e/`. When present, the **e2e** gate is **hard**: changing UI/app source globs requires matching e2e test updates in the same change set (and optional `e2e.test_command`).

How to write them:

1. **Key scenarios only** — critical user journeys, not exhaustive UI coverage.
2. **Assert outcomes users can see** (role/text/URL/state), never pixels, snapshot markup, or formal contracts (`e2e.forbid`).
3. **On failure keep video + screenshots** as CI artifacts (`on_failure_artifacts`).
4. **New specs run 3×** locally/CI to surface flakes (`new_spec_retries`, default 3).
5. **Same PR as the UI change** — gate fails if `src/app/...` (etc.) changes with no `e2e/**` (or configured `test_globs`) updates.
6. Templates: `templates/quality/e2e-playwright.config.ts.example`, `e2e-ci-snippet.yml.example`, fixture `templates/quality/fixtures/orbit-like-mini/`.

## DB tests (when migrations / SQL / pgTAP is present)

Auto-detect: `migrations/`, `db/migrations/`, Prisma/Supabase/Alembic/Flyway dirs, `schema.sql`, `pgtap/`, `db/tests/`, or pgTAP SQL (`SELECT plan(`). When present, the **db_tests** gate is **hard**: changing migration/schema sources requires matching DB test updates.

How to write them:

1. **Test the migration’s observable contract** — tables/columns/constraints/indexes/row invariants after apply (pgTAP `has_table` / `col_type_is`, or equivalent SQL assertions).
2. **One focused test file per migration theme** (or clearly named suite); update tests in the **same PR** as the migration.
3. **No app-layer mocks** — run against a real throwaway DB / transaction (`BEGIN…ROLLBACK`) when using pgTAP.
4. **Do not re-encode ORM helpers** in the test; assert catalog/data facts.
5. Optional `db_tests.test_command` (e.g. `pg_prove db/tests/*.sql`) runs when sources changed.
6. Template: `templates/quality/db-tests-pgtap.example.sql`; fixture under `templates/quality/fixtures/orbit-like-mini/db/`.

Absent e2e or DB layers → gates **skip pass** (`enabled: auto`). Agentized dogfood has neither.

## Strategy (anti-smell)

- Prefer tests that would fail if the behavior changed — not snapshots of implementation details.
- Cover branches that encode product rules; skip tautologies and pure wiring churn.
- One module = one `test_command` + coverage artifacts in `context/quality.json`.
- Combined coverage aggregates **all** modules (including JSON-only); missing artifacts **fail** (never fake 100%).
- Property-based tests (Hypothesis / fast-check) for pure modules — pilot 1–2 modules first.

## Gates (`context/quality.json`)

| Gate | Default | Metric |
|------|---------|--------|
| Coverage | hard 80% lines+branches | Uncovered lines limited by coverage — not by mutation |
| Mutation | hard **`mutationScoreCovered = 100%`** | Zero surviving mutants on covered lines; do **not** gate overall `mutationScore` |
| Test smells | **hard** (blocking) | Weak oracles / mock-call-only / `@patch` MUT |
| Architecture | **hard** (blocking) | import-linter (Py) / dependency-cruiser (JS) |
| E2E | **hard when present** (`enabled: auto`) | Changed UI sources → e2e tests updated (+ optional command) |
| DB tests | **hard when present** (`enabled: auto`) | Changed migrations/schema → DB tests updated (+ optional command) |
| Batch release | process | Reviewed PRs may share one CI; keep “up-to-date before merge” |

Mutation is **incremental** (changed files vs base), one command, required on CI + pre-push. If no relevant diff → skip **pass** (never false-fail). Compute covered score from tool JSON when built-in thresholds use the wrong metric (see `templates/quality/run-mutation-js.cjs.example`).

## Commands

```bash
./bin/agentized quality check
# optional when present:
./tests/test_mechanical.sh
```

- Do not bypass a red coverage, mutation, test-smell, architecture, e2e, or db_tests gate.
- Do not lower `mutation.min_score_covered` below 100 to “make CI green” — strengthen tests instead.
- Do not flip smells/architecture/e2e/db_tests back to `warn` to green CI — fix the finding or add a pointwise allowlist with a reason comment.
- Do not set `e2e.enabled` / `db_tests.enabled` to `false` just to silence a present layer — add the missing tests.

## Connect templates

Pre-push / CI call `agentized quality check`. Mechanical suite and `requirements-dev.txt` run only if those files exist in the target repo. Extra guidance under `templates/quality/` (Stryker wrapper, E2E, DB/pgTAP, import-linter, dependency-cruiser, batch-release, eslint test smells, orbit-like-mini fixture).
