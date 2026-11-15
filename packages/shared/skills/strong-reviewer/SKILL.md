---
name: strong-reviewer
description: When and how the main Agentized agent invokes the independent read-only reviewer subagent/skill — budget, watermark, gates-first. Use before handoff after real code changes, never on tiny format edits.
---

# Strong reviewer (orchestration)

## Role split

| Role | Model | Job |
|------|-------|-----|
| Main / helpers | cheap (`reviewer.helper_model`) | Implement, test, fix |
| `reviewer` agent | per-harness (`reviewer.harnesses.<cursor\|claude\|codex>`) | Read-only severity report |

Config: `{context}/quality.json` → `reviewer.*` (defaults set by connect).

## Caveman — **exception**

The `reviewer` does **not** use caveman/ultracave. Always write **expanded, unambiguous** findings and accept/reject rationale. Working agents stay ultracave; reviewer never does.

## Scope (task/PR budget)

Budget + watermark are **per scope** (`--scope` or `AGENTIZED_REVIEW_SCOPE`, default `default`). Use a distinct scope per task/PR, or `agentized review reset --scope <id>` when starting unrelated work so prior rounds do not exhaust the next task.

## When the main agent may call the reviewer

1. Implementation for the slice is **done**.
2. All quality gates have been run and are green (`agentized quality check` / pre-push).
3. Then either:
   - first review for this task/PR scope, or
   - a **full fix pack** for prior findings is pushed (`open_findings > 0` → `review allow` requests even if the delta is small), or
   - `agentized review allow` says the delta since the watermark earns another pass (new surface / sensitive paths).

## When to forbid a call

- Tiny edit / format / comment / rename-only / docs-only with no behavior change **and** no open findings.
- No real code change since the last reviewed watermark (`agentized review allow` → skip).
- Mid-fix: unfinished findings or red gates (except after a pushed fix pack with `open_findings > 0`).
- Budget exhausted for **this scope** (`used >= budget_max`, default **3**) — escalate to the human; or reset/switch scope for new work.
- Watermark unavailable (`action=blocked`) — reset scope or re-record a valid commit; do not treat as skip.

## How to call

1. `./bin/agentized review allow --scope <task-or-pr>` (or `--json`).
2. If `ok` and `action=request`: spawn the **reviewer** subagent (Cursor: `.cursor/agents/reviewer.md`; Claude: `.claude/agents/reviewer.md`; Codex: `.codex/agents/reviewer.toml` only — never `.md`) in a **fresh** context. Pass base ref + watermark sha.
3. After the report: `./bin/agentized review record --sha <Reviewed-commit> --findings <N> --scope <task-or-pr>`.
4. Fix by **class**, push one pack, re-check allow before the next call.

## Never

- Ask the reviewer to edit or approve its own work.
- Burn rounds on unchanged heads.
- Merge after a clean review without explicit owner confirmation.
