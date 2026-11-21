# Changelog

## Unreleased

### Fixed

- External `agentized connect`: empty external git clone is seeded (NAV + tasks/leases indexes); bridge conflicts preflighted; bridges installed before connect so local skeleton no-ops (no CLI temp-NAV dodge). Honest `connect.py` external skip waits AGE-68 A-final (mut surface).

### Changed

- `agentized check`: missing `context/process-control.json` is a **hard error** (required code-repo config). Documented in `docs/connect-contract.md` and README.
