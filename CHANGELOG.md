# Changelog

## Unreleased

### Fixed

- External `agentized connect` (CLI): suppress local skeleton registry dirs before bridging so fresh external Context no longer hits `ERR_BRIDGE_CONFLICT`.

### Changed

- `agentized check`: missing `context/process-control.json` is a **hard error** (required code-repo config). Documented in `docs/connect-contract.md` and README.
