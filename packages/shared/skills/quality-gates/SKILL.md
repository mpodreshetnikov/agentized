---
name: quality-gates
description: Run Agentized coverage/mutation gates from context/quality.json. Use before push/PR or when CI quality fails.
---

# Quality gates

- Config: `{context}/quality.json` (default coverage **80%** lines+branches). Change via `connect --coverage <pct>`, `quality set-coverage`, or edit the file.
- Mutation is a **hard gate** on covered changed lines (mutmut); not advisory.
- Commands: `python3 scripts/quality/coverage_check.py`, `python3 scripts/quality/run_mutation.py`, `./tests/test_mechanical.sh`.
- CLI: `agentized quality show|set-coverage|check`.
- Connect pins this skill and installs `.githooks/pre-push` / `.github/workflows/ci.yml` only when missing or marked `AGENTIZED:QUALITY`.
- JS/TS: `templates/quality/stryker.config.mjs.example` + `run-mutation-js.cjs.example` (hard `thresholds.break`).
- AGE-8 env-check / AGE-9 process skills are out of scope here — see `docs/QUALITY.md`.
