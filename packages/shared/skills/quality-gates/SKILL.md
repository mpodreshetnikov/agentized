---
name: quality-gates
description: High-signal testing strategy and Agentized coverage/mutation hard gates. Use when writing tests, configuring modules, or running quality check / pre-push / CI.
---

# High-signal testing & quality gates

## Strategy (anti-smell)

- Prefer tests that would fail if the behavior changed — not snapshots of implementation details.
- Cover branches that encode product rules; skip tautologies and pure wiring churn.
- One module = one `test_command` + coverage artifacts in `context/quality.json`.
- Combined coverage aggregates **all** modules (including JSON-only); missing artifacts **fail** (never fake 100%).

## Commands

```bash
./bin/agentized quality check
# optional when present:
./tests/test_mechanical.sh
```

- Coverage default **80%** lines & branches (`connect --coverage` / `quality set-coverage`).
- Mutation is a **hard** gate on covered changed lines (`mutation.min_score_covered`).
- Do not bypass a red coverage or mutation gate.

## Connect templates

Pre-push / CI call `agentized quality check`. Mechanical suite and `requirements-dev.txt` run only if those files exist in the target repo.
