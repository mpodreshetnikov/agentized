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

## Reviewable PR size

Default limit **1500** insertions vs `origin/main` (override with `PROCESS_BASE` / `--base`). Warn at **75%** of the limit; over the limit fails `agentized process size` (pre-push prints size, does not hard-fail the push on size alone).

```bash
./bin/agentized process size
./bin/agentized process size --base origin/main --json
```

## Spec / decision hygiene

Keep decisions in `context/decisions/` when they change process rules. Prefer one claimable child task per reviewable PR; split when approaching the size limit.

## No GitHub Stacked PRs

**Banned going forward.** Every PR targets `main` (or the repo default branch), never another feature/PR branch. Sequence merges (land A, then open B from updated `main`), or ship one PR. Do not use GitHub Stacked PRs / `stack_on` for new Agentized work.

## Connect

`agentized connect` pins `process-control.json` (no clobber) and wires `process_guard.py` into Cursor / Claude / Codex hooks. External repos without local `packages/` or `templates/quality` use the **installed Agentized root**.
