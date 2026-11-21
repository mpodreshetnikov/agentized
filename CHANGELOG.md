# Changelog

## Unreleased

### Fixed

- External `agentized connect`: preflight bridge conflicts before seeding empty registry (NAV + tasks/leases indexes + decisions/goals/digests dirs); atomic UTF-8 writes; bridges before connect with rollback on connect failure; `under_context` allows tasks/leases/… bridge escapes so `agentized index` / write_metrics work. Empty external INDEX seed uses `rebuild_task_index` / `rebuild_lease_index` (coord Lead REJECT #55 MINIMAL_* delete). Honest `connect.py` external skip waits AGE-68 A-final.

### Changed

- `agentized check`: missing `context/process-control.json` is a **hard error** (required code-repo config). Documented in `docs/connect-contract.md` and README.
- External Context: **local→external migration is manual** — copy registry into the external clone, set `context.json`, then `git rm -r --ignore-unmatch context/tasks context/leases context/decisions context/goals context/digests context/NAV.md` (missing pathspecs OK; not `--cached` alone), then `connect`. Living local dirs block bridges. See `docs/external-context.md`.
