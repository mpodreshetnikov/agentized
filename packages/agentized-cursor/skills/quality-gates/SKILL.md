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

## E2E / DB layer gates (when present)

Auto-detect Playwright/Cypress (configs/deps/`e2e/`) or DB (migrations/ORM/pgTAP/`db/tests`). When present, gate is **hard**: suite must **exist and run** (`test_command` or autodetect `npx playwright test` / `supabase test db` / `pg_prove`); source changes need some `test_globs` path in the same diff (**limitation:** any matching test file counts — not per-source). `enabled=false` only with human `disable_decision` `{reason, approved_by, expires≤14d}`. Absent layer → skip pass.

Write e2e for key user journeys (visible outcomes; no pixels/snapshots). Write DB tests for migration contracts (real DB/pgTAP; same PR as migration).

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

Pre-push / CI call `agentized quality check`. Mechanical suite and `requirements-dev.txt` run only if those files exist in the target repo. Extra guidance under `templates/quality/` (Stryker wrapper, E2E, DB/pgTAP, import-linter, dependency-cruiser, batch-release, eslint test smells).
