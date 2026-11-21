# Changelog

## Unreleased

### Fixed

- External `agentized connect`: do not create local `context/tasks` (and other bridge paths) when `placement: external` — bridges replace those paths after a successful connect (avoids `ERR_BRIDGE_CONFLICT` on fresh repos).

### Changed

- `agentized check`: missing `context/process-control.json` is a **hard error** (required code-repo config). Documented in `docs/connect-contract.md` and README.
