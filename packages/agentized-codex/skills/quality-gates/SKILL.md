---
name: quality-gates
description: High-signal testing strategy and Agentized coverage/mutation hard gates. Use when writing tests, configuring modules, or running quality check / pre-push / CI.
---

# High-signal testing & quality gates

## Test-writing rules (Orbit / Maxim)

1. **Do not mock the module under test.** Fake collaborators at the boundary; exercise real MUT code.
2. **Weak checks cannot be the primary oracle.** Truthy / `is not None` / substring / mock-call-only asserts are supporting signals at best — the test must assert observable behavior.
3. **The test must fail when the logic breaks.** Prefer arranging inputs that distinguish correct vs incorrect results.
4. **Do not mirror production formulas in tests.** Compute expected values from first principles or fixtures, not by copying the implementation.
5. **Shared fixtures when logic is duplicated.** If two places implement the same rule, both must assert against the same shared fixture/table (see `shared_fixtures` in `context/quality.json`).

## Strategy (anti-smell)

- Prefer tests that would fail if the behavior changed — not snapshots of implementation details.
- Cover branches that encode product rules; skip tautologies and pure wiring churn.
- One module = one `test_command` + coverage artifacts in `context/quality.json`.
- Combined coverage aggregates **all** modules (including JSON-only); missing artifacts **fail** (never fake 100%).
- Property-based tests (Hypothesis / fast-check) for pure modules — pilot 1–2 modules first.
- E2E (when UI exists): key scenarios only; on failure keep video+screenshots as CI artifacts; new specs run 3× for flakes. No pixel compares, snapshot markup, or formal contracts.

## Gates (`context/quality.json`)

| Gate | Default | Metric |
|------|---------|--------|
| Coverage | hard 80% lines+branches | Uncovered lines limited by coverage — not by mutation |
| Mutation | hard **`mutationScoreCovered = 100%`** | Zero surviving mutants on covered lines; do **not** gate overall `mutationScore` |
| Test smells | **warn** | Weak oracles / mock-call-only / `@patch` MUT |
| Architecture | **warn** (pilot) | import-linter (Py) / dependency-cruiser (JS) |
| Batch release | process | Reviewed PRs may share one CI; keep “up-to-date before merge” |

Mutation is **incremental** (changed files vs base), one command, required on CI + pre-push. If no relevant diff → skip **pass** (never false-fail). Compute covered score from tool JSON when built-in thresholds use the wrong metric (see `templates/quality/run-mutation-js.cjs.example`).

## Commands

```bash
./bin/agentized quality check
# optional when present:
./tests/test_mechanical.sh
```

- Do not bypass a red coverage or mutation gate.
- Do not lower `mutation.min_score_covered` below 100 to “make CI green” — strengthen tests instead.

## Connect templates

Pre-push / CI call `agentized quality check`. Mechanical suite and `requirements-dev.txt` run only if those files exist in the target repo. Extra guidance under `templates/quality/` (Stryker wrapper, E2E, import-linter, dependency-cruiser, batch-release, eslint test smells).
