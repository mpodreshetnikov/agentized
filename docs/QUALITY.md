# Quality (Agentized)

Configurable multi-module coverage, incremental mutation hard gate, test-smell + architecture hard gates (blocking by default), pre-push/CI. Practices aligned with Orbit / Maxim (13–15.11.2026) — not Orbit product content.

## Config

[`context/quality.json`](../context/quality.json) — versioned SoT. Default coverage **80%** lines & branches. Connected projects **and** Agentized dogfood use **`mutation.min_score_covered = 100`** (gate `mutationScoreCovered` only — never overall `mutationScore`). Test smells and architecture gates default to **`mode: hard`** (exit ≠ 0 on findings) — same as mutation.

```bash
./bin/agentized connect --coverage 85
./bin/agentized quality set-coverage 85
# or edit context/quality.json
```

| Field | Meaning |
|-------|---------|
| `modules[]` | `source`, `test_command`, coverage artifacts, optional local thresholds |
| `mutation.gate` | `hard` on **`mutationScoreCovered`** for **whole changed files** matching `include_globs` (default **100**; never gate overall `mutationScore`; not hunk-only) |
| `mutation.include_globs` | Which changed sources enter the mutation set. Default/dogfood: `runtime/agentized/*.py` (Python `fnmatch` `*` matches `/`, so one pattern covers flat and nested modules; a separate `**` glob is redundant) |
| AST-noop exclusion | After name/glob selection, drop files where `ast.dump(ast.parse(x), include_attributes=False)` matches base vs head **raw bytes** (encoding cookie respected). Missing base, decode/parse errors, and git errors **stay in scope** (fail-closed; never silent exclude). Excluded names are logged. |
| `test_smells` | Hard-by-default AST lint for weak oracles / mock-call-only (JS: eslint template); `mode: warn` only if explicitly kept |
| `architecture` | Hard-by-default module boundaries (`import-linter` or builtin edges; JS: dependency-cruiser) |
| `property_based` | Hypothesis / fast-check pilot modules |
| `e2e` | Key scenarios + failure artifacts + 3× new specs (templates only when no UI) |
| `shared_fixtures` | Same duplicated logic → shared fixture both sides must match |
| `batch_release` | Reviewed PRs may share one CI; keep up-to-date branch protection |
| `gates.pre_push` / `gates.ci` | Ordered gate names |

## Commands

Self-contained under `runtime/agentized/` (foreign connected repos do not need `scripts/quality/`).

| Command | Role |
|---------|------|
| `./bin/agentized quality check` | Module tests + coverage + test_smells + architecture + mutation |
| `python3 -m agentized.coverage_report` | Combine → `coverage/combined-*` |
| `./tests/test_mechanical.sh` | Layout / connect / leases (**optional** — only when the file exists) |
| `ruff format --check` (CI) | Hard gate on **changed** `*.py` vs PR base / push before (AGE-48; `line-length = 100`) |

Missing coverage artifacts fail the gate (never treated as 100%). Multi-module `combined` sums per-module totals so JSON-only modules are included. Mutation is incremental vs base on **whole changed files** (not format hunks only), drops AST-equivalent (noop) files, skips cleanly when no mutable files remain, wipes `mutants/` before each run, and fails closed on mutmut exit ≠ 0. Do not lower the covered-score gate — strengthen tests.

## Connect

Pins `quality-gates` skill; installs `.githooks/pre-push` and `.github/workflows/ci.yml` when missing or marked `AGENTIZED:QUALITY` (no clobber of unmarked user files). Sets local `core.hooksPath=.githooks` when unset; preserves an existing user path and Cursor Cloud `agent-hooks`. Language templates under `templates/quality/` (Stryker covered-score wrapper, Playwright e2e, import-linter, dependency-cruiser, batch-release, eslint smells).

On reconnect, `ensure_quality_config` flips `test_smells.mode` / `architecture.mode` from **`warn` → `hard`** when still set to warn (AGE-19 policy). Other fields stay as-is. Skill / reviewer pins still follow managed-hash: untouched auto-update; user edits → `skipped_user`.

New projects get hard defaults with no manual steps: smells=`hard`, architecture=`hard`, `mutationScoreCovered=100`, coverage=80.

## Strong reviewer (AGE-11)

Independent **read-only** reviewer role + orchestration skill, installed by `connect` for Cursor / Claude / Codex:

- Cursor: `.cursor/agents/reviewer.md` → `grok-4.7[reasoning_effort=medium]`
- Claude: `.claude/agents/reviewer.md` → `claude-fable-5-2` + `disallowedTools`
- Codex: `.codex/agents/reviewer.toml` **only** (never `.md`) → `gpt-6-astra`

The reviewer **never** uses caveman/ultracave — expanded findings only. Human-facing acceptance reports (`short`, 5 blocks) also never use caveman — see the `acceptance-artifacts` skill.

Config in [`context/quality.json`](../context/quality.json) → `reviewer`:

| Field | Default | Meaning |
|-------|---------|---------|
| `harnesses.cursor.model` | `grok-4.7[reasoning_effort=medium]` | Cursor reviewer |
| `harnesses.claude.model` | `claude-fable-5-2` | Claude reviewer |
| `harnesses.codex.model` | `gpt-6-astra` | Codex reviewer |
| `helper_model` | `composer-2` | Cheap model for implementer / helpers |
| `budget_max` | `3` | Max review rounds per task/PR |
| `delta_lines` | `200` | New reviewable lines since watermark that earn another pass |
| `sensitive_globs` | runtime/workflows/config… | Any change earns another pass |

```bash
./bin/agentized review status [--scope TASK-or-PR]
./bin/agentized review allow [--scope TASK-or-PR]   # exit 0 → call reviewer; else skip/escalate/blocked
./bin/agentized review record --sha <Reviewed-commit> --findings N [--scope TASK-or-PR]
./bin/agentized review reset --scope TASK-or-PR     # fresh budget for a new task/PR
./bin/agentized review set --harness cursor --model 'grok-4.7[reasoning_effort=medium]'
./bin/agentized reporting set --level short|technical
```

Scope (task/PR identity): `--scope` or env `AGENTIZED_REVIEW_SCOPE` (default `default`). Budget + watermark are **per scope**, so unrelated work does not share `used` / watermark. Start a new task/PR with a new scope or `review reset`.

Rules (adapted from Orbit Automated Review Policy / review-delta — not product content):

1. Main agent finishes implementation + green gates **first**, then may call the reviewer.
2. Reviewer never edits/commits/approves; names `Reviewed commit: <sha>`.
3. Watermark + budget live in `.agentized/review-state.json` (local, keyed by scope). After `budget_max` for that scope, escalate to human — no infinite expensive loops.
4. Forbid reviewer on unchanged heads, tiny format/docs-only deltas, or mid-fix packs — **except** when `open_findings > 0` and head moved (fix-pack re-review).
5. Invalid / missing watermark commits block review (recovery: reset or re-record); `record` rejects non-existent SHAs.

## Related

AGE-8 env-check: [`AGENT_ENVIRONMENT.md`](./AGENT_ENVIRONMENT.md). AGE-9 process-control: [`process-control.md`](./process-control.md).
