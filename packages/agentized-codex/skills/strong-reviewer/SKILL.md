---
name: strong-reviewer
description: When and how the main Agentized agent invokes the independent read-only reviewer subagent/skill — budget, watermark, gates-first. Use before handoff after real code changes, never on tiny format edits.
---

# Strong reviewer (orchestration)

## Role split

| Role | Model | Job |
|------|-------|-----|
| Main / helpers | cheap (`reviewer.helper_model`) | Implement, test, fix |
| `reviewer` agent | strong (`reviewer.model`, high effort) | Read-only severity report |

Config: `{context}/quality.json` → `reviewer.*` (defaults set by connect).

## When the main agent may call the reviewer

1. Implementation for the slice is **done**.
2. All quality gates have been run and are green (`agentized quality check` / pre-push).
3. Then either:
   - first review for this task/PR, or
   - a **full fix pack** for prior findings is pushed, or
   - `agentized review allow` says the delta since the watermark earns another pass (new surface / sensitive paths).

## When to forbid a call

- Tiny edit / format / comment / rename-only / docs-only with no behavior change.
- No real code change since the last reviewed watermark (`agentized review allow` → skip).
- Mid-fix: unfinished findings or red gates.
- Budget exhausted (`used >= budget_max`, default **3**) — escalate to the human with open findings; do not loop.

## How to call

1. `./bin/agentized review allow` (or `agentized review allow --json`).
2. If `ok` and `action=request`: spawn the **reviewer** subagent (Cursor/Claude: `.cursor/agents/reviewer.md` / `.claude/agents/reviewer.md`; Codex: same role via `.codex/agents/reviewer.md` + this skill) in a **fresh** context. Pass base ref + watermark sha.
3. After the report: `./bin/agentized review record --sha <Reviewed-commit> --findings <N>`.
4. Fix by **class**, push one pack, re-check allow before the next call.

## Never

- Ask the reviewer to edit or approve its own work.
- Burn rounds on unchanged heads.
- Merge after a clean review without explicit owner confirmation.
