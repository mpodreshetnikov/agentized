# External Project Context (AGE-25)

`context/context.json` selects nested vs external Project Context. Quality/process/env-check JSON and pinned skills/hooks/agents stay in the **code** repo context dir.

```json
{
  "version": 1,
  "placement": "external",
  "external": {
    "path": "../agentized-context",
    "remote": "git@github.com:example/agentized-context.git"
  }
}
```

## Rules

- Fail-closed: invalid JSON/placement/empty `external.path` → error (no nested fallback).
- `external.path` inside the code repo requires gitignore.
- Clone Context to `external.path`, then `agentized connect` + `env-check` (exit **1** if clone missing/incomplete — local and cloud).
- Registry dirs (`tasks`, `leases`, …, `NAV.md`) live in the external clone; connect creates **relative** bridges under `context/` for nested-path callers.
- Bridges are **not committed**: connect appends the six paths to `.gitignore`. Foreign/conflict paths **refuse** (atomic: all six preflighted before any link). Empty or `.gitkeep`-only dirs under `context/` may be cleared for bridges; **local→external migration of living registry content is manual** (copy into the external clone, then untrack in the code repo — see steps below). Connect does **not** auto-move trees.
- Claim/status/index: CLI/connect resolve via `registry_root`; after bridges, `context/tasks` ≡ registry.

## Local → external switch (step by step)

1. Create/clone the Context repo at `external.path` with `NAV.md` and `tasks/` (plus leases/decisions/goals/digests as needed).
2. Copy living registry content from the code-repo `context/` dirs into that clone; commit **in the Context repo**.
3. Set `context/context.json` to `placement: external` with `path` / `remote`.
4. Run `agentized connect` (creates relative bridges + `.gitignore` entries for the six bridge paths).
5. In the **code** repo, untrack moved trees that used to be real dirs:
   `git rm -r --cached context/tasks context/leases context/decisions context/goals context/digests context/NAV.md` (skip paths that were never tracked).
6. Commit in the code repo **only**: `context/context.json`, `.gitignore` (bridge rules), and CI/config pins that stay nested. Do **not** commit the bridge symlinks.
7. Confirm `git status` is clean except that intended commit; bridges show as ignored. Re-run `agentized env-check`.

See also [`AGENT_ENVIRONMENT.md`](AGENT_ENVIRONMENT.md), [`connect-contract.md`](connect-contract.md).
