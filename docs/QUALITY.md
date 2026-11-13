# Quality (Agentized)

AGE-7: configurable multi-module coverage, incremental mutation as a **hard gate**, pre-push/CI.

## Config

[`context/quality.json`](../context/quality.json) — versioned SoT. Default coverage **80%** lines & branches.

```bash
./bin/agentized connect --coverage 85
./bin/agentized quality set-coverage 85
# or edit context/quality.json
```

| Field | Meaning |
|-------|---------|
| `modules[]` | `source`, `test_command`, coverage artifacts, optional local thresholds |
| `mutation.gate` | `hard` — fails CI when covered mutation score on changed include_globs is below `min_score_covered` (default 50; ratchet toward 80) |
| `mutation.include_globs` | Which changed sources enter the mutation set (harness wiring often excluded) |
| `gates.pre_push` / `gates.ci` | Ordered gate names |

## Commands

| Command | Role |
|---------|------|
| `python3 scripts/quality/coverage_check.py` | Module tests + threshold checks + combined ≥ threshold |
| `python3 scripts/quality/coverage_report.py` | Combine → `coverage/combined-*` |
| `python3 scripts/quality/run_mutation.py` | Incremental mutmut; **fails on survivors** |
| `./tests/test_mechanical.sh` | Layout / connect / leases |

Mechanisms adapted from Orbit (combiner + parallel thresholds + incremental mutate list) — not Orbit product content. Mutation follows the agreed **required** gate (Orbit #272 shipped advisory).

## Connect

Pins `quality-gates` skill; installs `.githooks/pre-push` and `.github/workflows/ci.yml` when missing or marked `AGENTIZED:QUALITY` (no clobber of unrelated files). JS/TS guidance under `templates/quality/`.

## Later slices

AGE-8 env-check/cloud hooks; AGE-9 communication/autonomy skills.
