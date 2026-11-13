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

Self-contained under `runtime/agentized/` (foreign connected repos do not need `scripts/quality/`).

| Command | Role |
|---------|------|
| `./bin/agentized quality check` | Module tests + coverage thresholds + mutation hard gate |
| `python3 -m agentized.coverage_report` | Combine → `coverage/combined-*` |
| `./tests/test_mechanical.sh` | Layout / connect / leases (**optional** — only when the file exists) |

Missing coverage artifacts fail the gate (never treated as 100%). Multi-module `combined` sums per-module totals so JSON-only modules are included. Mutation wipes `mutants/` before each run and fails closed on mutmut exit ≠ 0.

Mechanisms adapted from Orbit (combiner + parallel thresholds + incremental mutate list) — not Orbit product content.

## Connect

Pins `quality-gates` skill; installs `.githooks/pre-push` and `.github/workflows/ci.yml` when missing or marked `AGENTIZED:QUALITY` (no clobber of unmarked user files). Sets local `core.hooksPath=.githooks` when unset; preserves an existing user path and Cursor Cloud `agent-hooks`. JS/TS guidance under `templates/quality/`.

## Strong reviewer (AGE-11)

Independent **read-only** reviewer role + orchestration skill, installed by `connect` for Cursor / Claude / Codex (`.cursor/agents/reviewer.md`, `.claude/agents/`, `.codex/agents/` + `strong-reviewer` skill).

Config in [`context/quality.json`](../context/quality.json) → `reviewer`:

| Field | Default | Meaning |
|-------|---------|---------|
| `model` | `claude-opus-4.5` | Strong/frontier model for the reviewer agent |
| `effort` | `high` | Review depth hint in the agent prompt |
| `helper_model` | `composer-2` | Cheap model for implementer / helpers |
| `budget_max` | `3` | Max review rounds per task/PR |
| `delta_lines` | `200` | New reviewable lines since watermark that earn another pass |
| `sensitive_globs` | runtime/workflows/config… | Any change earns another pass |

```bash
./bin/agentized review status
./bin/agentized review allow          # exit 0 → call reviewer; else skip/escalate
./bin/agentized review record --sha <Reviewed-commit> --findings N
./bin/agentized review set --model claude-opus-4.5 --budget-max 3
```

Rules (adapted from Orbit Automated Review Policy / review-delta — not product content):

1. Main agent finishes implementation + green gates **first**, then may call the reviewer.
2. Reviewer never edits/commits/approves; names `Reviewed commit: <sha>`.
3. Watermark + budget live in `.agentized/review-state.json` (local). After `budget_max`, escalate to human — no infinite expensive loops.
4. Forbid reviewer on unchanged heads, tiny format/docs-only deltas, or mid-fix packs.

## Related

AGE-8 env-check: [`AGENT_ENVIRONMENT.md`](./AGENT_ENVIRONMENT.md). AGE-9 process-control: [`process-control.md`](./process-control.md).
