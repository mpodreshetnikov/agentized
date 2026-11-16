# Process control (Agentized)

AGE-9: claim before code edits + reviewable PR size. Config: [`context/process-control.json`](../context/process-control.json).

## Claim before edits

Agents must hold an **in-progress** task claim before changing watched paths (`runtime/**`, `scripts/**`, `packages/**`, …). Context task/lease/digest paths are excluded.

```bash
./bin/agentized claim <TASK_ID> --owner <you>
./bin/agentized process claim runtime/agentized/foo.py
```

| Mode | Who | Behavior |
|------|-----|----------|
| `claim_mode_agent=refuse` | Cursor/Claude/Codex cloud (or labeled agent) | Hook/CLI **deny** without claim |
| `claim_mode_local=warn` | Local interactive | Warn only |

`process_guard` hook runs on Write/Edit (and Codex `apply_patch`) before lease-warn.

## Reviewable PR size (AGE-32 / AGE-35)

Default limit **1500** insertions vs `origin/main` (override with `PROCESS_BASE` / `--base`, or `reviewable_lines` in `process-control.json`). Warn at **75%** of the limit (`warn_at_pct`). Over the limit **hard-fails** `agentized process size` (exit 1). Hook/`|| true` removal and base-ref fail-closed are AGE-35 (`process_size`).

```bash
./bin/agentized process size
./bin/agentized process size --base origin/main --json
```

## Spec approval gate (AGE-28)

Config block: `spec_approval` in [`context/process-control.json`](../context/process-control.json). **Off by default.** When enabled: fail-closed + CI/pre-push.

| Knob | Default | Meaning |
|------|---------|---------|
| `enabled` | `false` | When true, CI + pre-push `process spec-approval` checks gated tasks |
| `complex_tag` | `complex` | Tag that marks a task as requiring Spec + Approval |
| `spec_heading` | `## Spec` | Required real Spec content (`TODO` / `…` / `_(…)` do not count) |
| `approval_heading` | `## Approval` | Approver on `merge_policy.human_participants` (full email) **or** approval line committed by non-owner |

Checks every status from `in-progress` onward (`self-review`, `for-review`, `blocked`, `done`, …), not only `in-progress`.

```bash
./bin/agentized process spec-approval
./bin/agentized process spec-approval --json
```

## Spec / decision hygiene

Keep decisions in `context/decisions/` when they change process rules. Prefer one claimable child task per reviewable PR; split when approaching the size limit.

### ADR format

Create with `agentized adr --title "…" [--status proposed|accepted|superseded|deprecated] [--tasks T-…,T-…]`. Files are `context/decisions/ADR-YYMMDD-xxx-<slug>.md` with YAML front matter (`id`, quoted `title`, `status`, `date`, `tasks`) then `# Title` / Context / Decision / Consequences. Default status is **`proposed`** (human confirms heavy artifacts). Titles refuse blank/control characters; task ids must match `T-YYMMDD-xxxx`.

## No GitHub Stacked PRs

**Banned going forward.** Every PR targets `main` (or the repo default branch), never another feature/PR branch. Sequence merges (land A, then open B from updated `main`), or ship one PR. Do not use GitHub Stacked PRs / `stack_on` for new Agentized work.

## Connect

`agentized connect` pins `process-control.json` (no clobber) and wires `process_guard.py` into Cursor / Claude / Codex hooks. External repos without local `packages/` or `templates/quality` use the **installed Agentized root**.
