# Process control (Agentized)

AGE-9 / AGE-35 / AGE-40: claim before code edits + reviewable PR size. Config: [`context/process-control.json`](../context/process-control.json).

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

`process_guard` runs on Write/Edit (and Codex `apply_patch`) before lease-warn. Cursor hooks use `failClosed: true`. Broken `process-control.json` → deny + exit **2**. Runtime import failure of claim guard → deny + exit **2**.

## Reviewable PR size (AGE-32 / AGE-35 / AGE-40)

Hard gate: **≤1500** insertions OK (**inclusive**); hard-fail only when insertions **>** limit (`over >{limit}`; exit 1). Warn at **≥** `warn_at` (`warn_at_pct`, default 75%). No silent defaults for bad fields: `reviewable_lines` int **1..1500** (not bool); `warn_at_pct` number **1..100**. Bad `0`/`null`/`[]`/`"abc"`/`{}` → clean exit 1. Missing file → defaults `1500`/`75` then validated. Limit cannot self-raise: read `reviewable_lines` from **base ref** config when present; always cap **1500**.

Base default `origin/main` (`PROCESS_BASE` / `--base`). **Refuse** `HEAD`/`@` and bases that are not ancestors of `origin/main`. CI sets `PROCESS_BASE` to the PR base sha. Hook/`|| true` removal and size helpers live in `process_size`.

```bash
./bin/agentized process size
./bin/agentized process size --base origin/main --json
PROCESS_BASE=<pr-base-sha> ./bin/agentized process size
```

Warn at `warn_at_pct` of the effective limit. CLI streams stderr whenever `ok` is false (not only `level == over`).

**Connect baseline (AGE-85):** when HEAD has `{context}/.agentized/managed.json` but the size base does not (first connect push, or no `origin/main` yet), insertions on connect-installed bootstrap paths (`AGENTS.md`, `{context}/**`, `.githooks/`, harness dirs, …) are excluded from the count. User/source paths still count — not a generic bypass. After `managed.json` exists on the base, the normal full diff applies. `process format-disables` on that first push (no `origin/main`) scans the whole HEAD tree vs the empty tree — every disable counts; only the ancestry check is dropped. Hook scripts that connect installs ship with no disable comments.

## Tip hygiene (AGE-76)

Hard gate inside `agentized tasks-validate` (dogfood pre-push / CI). Always checks `context/tasks/INDEX.md` equals `agentized index` rebuild. (`connect` skeleton → `rebuild_task_index` is AGE-68 — not this gate.) Template quality CI/pre-push do **not** run tip hygiene until that seed lands.

When a PR number is known, **at least one** task must have `pr:` pointing at that PR, status `self-review` or `done`, and claim released (`claim:` empty or `_(пусто)_` only — the template `_(пусто или кто ведёт)_` counts as **held**). Template `родитель` (`_(пусто для корневой задачи; …)_`) is also held — use a real parent id or `_(пусто)_`. `agentized new` defaults parent to `_(пусто)_` and requires `--value` for `Ценность:`.

PR number resolution:

- On GitHub Actions `pull_request`, `GITHUB_REF` (`refs/pull/N/…`) wins.
- `AGENTIZED_PR` / `TIP_HYGIENE_PR` / `GITHUB_PR_NUMBER` / `--pr` must **agree** with that N or the gate fails (blocks override dodges).
- Missing PR number on `pull_request` → fail.
- `push` / local without a PR number → skip linked-task checks (INDEX still required).

```bash
./bin/agentized tasks-validate
./bin/agentized ready <TASK_ID> --review-note "…" [--pr '#N']
```

`ready` only from `in-progress` → `self-review` + claim `_(пусто)_`. Already `self-review` → no-op (no writes). Other statuses refused.

## Format / lint disable comments (T-261121-8c84)

Hard CI + pre-push gate (dogfood and `templates/quality/`): PRs must not **add** formatter/linter/coverage/mutation disables. Scopes: Python COMMENT tokens (`*.py`/`*.pyi`/`*.pyw` — fmt/noqa/pragma/type:ignore/pylint/mypy/pyright), JS/TS comments (`eslint-disable`, `prettier-ignore`, `@ts-ignore|nocheck|expect-error`, Stryker disable), and config keys (ruff `per-file-ignores`/`exclude`/`extend-exclude`, coverage `omit`, mutmut excludes, Stryker ignore/disableComments). HEAD blob only; renames followed for base; non-UTF-8 blobs fail naming the file. **No allowlist** unless Maxim approves a sole-purpose change. Same base rules as size (`PROCESS_BASE` / `--base`; refuse `HEAD`).

```bash
./bin/agentized process format-disables
PROCESS_BASE=<pr-base-sha> ./bin/agentized process format-disables --json
```

## Spec approval gate (AGE-28) — core

Optional `spec_approval` policy (defaults off). Pure evaluation lives in
`runtime/agentized/spec_approval*.py` (text + defaults + decisions):

- Complex-tagged tasks need a real `## Spec` (not `TODO` / `…` / `_(…)` / trivial
  `x` / `.` / `ok` / `<fill>` / unchecked fill-me; at least three words).
- `## Approval` must list `approved-by:` someone **other than** the claim owner
  (agent addresses like `cursoragent@…` also count as the owner).
- That approver must match `merge_policy.human_participants` (full email) **and**
  must have committed the approval line (typed text alone never passes).
- Agent/bot committers never count.

CLI / CI / pre-push wiring for `process spec-approval` ships in a follow-up PR.

## Spec / decision hygiene

Keep decisions in `context/decisions/` when they change process rules. Prefer one claimable child task per reviewable PR; split when approaching the size limit.

### ADR format

Create with `agentized adr --title "…" [--status proposed|accepted|superseded|deprecated] [--tasks T-…,T-…]`. Files are `context/decisions/ADR-YYMMDD-xxx-<slug>.md` with YAML front matter (`id`, quoted `title`, `status`, `date`, `tasks`) then `# Title` / Context / Decision / Consequences. Default status is **`proposed`** (human confirms heavy artifacts). Titles refuse blank/control characters; task ids must match `T-YYMMDD-xxxx`.

## No GitHub Stacked PRs

**Banned going forward.** Every PR targets `main` (or the repo default branch), never another feature/PR branch. Sequence merges (land A, then open B from updated `main`), or ship one PR. Do not use GitHub Stacked PRs / `stack_on` for new Agentized work.

## Connect

`agentized connect` pins `process-control.json` (no clobber) and wires `process_guard.py` into Cursor / Claude / Codex hooks. Keep Cursor `failClosed: true` when editing hooks. External repos without local `packages/` or `templates/quality` use the **installed Agentized root**.
