# Changelog

## Unreleased

### AGE-96 — branch-history Progress/Decision Log prefix gate

- `tasks-validate` (hard, CI + pre-push) also checks every non-merge commit pair in `base..HEAD`: each touched `context/tasks/T-*.md` must keep Progress and Decision Log as an exact prefix of its parent version, so a mid-branch deletion cannot be hidden by later appends (task files that are not on `main` included).
- A file deleted and re-added is compared with its last existing version. Merge commits are not pair endpoints (conflict resolution may reorder concurrent appends); the next commit is compared with the merge.
- Unreadable blobs (git error, non-UTF-8) fail closed. A force-push rewrite to a clean history passes: only the final branch history is judged.

### AGE-76 — PR tip hygiene gate

- Hard `tasks-validate` tip hygiene: INDEX freshness; PR-linked tasks must be `self-review`/`done` with claim `_(пусто)_` or empty; template `родитель` placeholder held; every PR needs a matching `pr:` task.
- In CI `pull_request`, `GITHUB_REF` wins; env/`--pr` overrides must agree.
- `agentized ready`: `in-progress` → self-review + claim release; self-review is a no-op; other statuses refused.
- Wired in **dogfood** CI + `.githooks/pre-push` only. Template `templates/quality/{ci.yml,pre-push}` tip-hygiene wiring waits for AGE-68 connect INDEX seeds (REJECT r3 choice b).
- `agentized new` requires `--value` (writes `Ценность:`) and defaults `родитель` to `_(пусто)_` (not the TEMPLATE placeholder).
- `connect` INDEX seed → `rebuild_task_index` remains AGE-68.

### Fixed

- External `agentized connect`: preflight bridge conflicts before seeding empty registry (NAV + tasks/leases indexes + decisions/goals/digests dirs); atomic UTF-8 writes; bridges before connect with rollback on connect failure; `under_context` allows tasks/leases/… bridge escapes so `agentized index` / write_metrics work. Empty external INDEX seed uses `rebuild_task_index` / `rebuild_lease_index` (coord Lead REJECT #55 MINIMAL_* delete). Honest `connect.py` external skip waits AGE-68 A-final.

### Changed

- `agentized check`: missing `context/process-control.json` is a **hard error** (required code-repo config). Documented in `docs/connect-contract.md` and README.
- External Context: **local→external migration is manual** — copy registry into the external clone, set `context.json`, then `git rm -r --ignore-unmatch context/tasks context/leases context/decisions context/goals context/digests context/NAV.md` (missing pathspecs OK; not `--cached` alone), then `connect`. Living local dirs block bridges. See `docs/external-context.md`.
