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
- Bridges are **not committed**: connect appends the six paths to `.gitignore`. Foreign/conflict paths **refuse** (atomic: all six preflighted before any link). Empty or `.gitkeep`-only dirs under `context/` may be cleared for bridges; **local→external migration of living registry content is manual** (copy into the external clone, then **delete** the local trees so bridges can land — see steps below). Connect does **not** auto-move trees. `git rm --cached` alone is **not** enough: disk files still block bridges.
- Claim/status/index: CLI/connect resolve via `registry_root`; after bridges, `context/tasks` ≡ registry.

## Local → external switch (step by step)

Order matters: **connect after local trees are gone**. Living local dirs under `context/` refuse bridges (`local context path blocks external bridge`).

1. Create/clone the Context repo at `external.path` (empty git checkout is fine).
2. Copy living registry content from the code-repo `context/` into that clone (`NAV.md`, `tasks/`, `leases/`, `decisions/`, `goals/`, `digests/` as present); commit **in the Context repo**.
3. Set `context/context.json` to `placement: external` with `path` / `remote`.
4. **Delete** the local trees from the code repo (disk + index), not merely untrack:
   ```bash
   git rm -r --ignore-unmatch context/tasks context/leases context/decisions context/goals context/digests context/NAV.md
   ```
   Use `--ignore-unmatch`: a fresh connect may only have `NAV.md` / `tasks` / `leases` — bare pathspecs for missing dirs exit **128** and block the rest of the procedure. Untracked/absent pathspecs are OK (ignored). Do **not** use `git rm -r --cached` alone — files left on disk still block bridges.
5. Run `agentized connect` (seeds missing empty indexes if needed; creates relative bridges + `.gitignore` for the six bridge paths).
6. Commit in the code repo **only**: `context/context.json`, `.gitignore` (bridge rules), and CI/config pins that stay nested. Do **not** commit the bridge symlinks.
7. Confirm bridges are ignored; re-run `agentized env-check` and `agentized index` (task rows live in the external `tasks/INDEX.md`).

See also [`AGENT_ENVIRONMENT.md`](AGENT_ENVIRONMENT.md), [`connect-contract.md`](connect-contract.md).
