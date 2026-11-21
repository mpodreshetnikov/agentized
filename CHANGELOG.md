# Changelog

## Unreleased

### Fixed

- External `agentized connect`: empty external git clone is seeded (NAV + tasks/leases indexes); local skeleton skips bridge paths; bridge conflicts preflighted before connect writes (no CLI temp-NAV dodge).

### Changed

- `agentized check`: missing `context/process-control.json` is a **hard error** (required code-repo config). Documented in `docs/connect-contract.md` and README.
