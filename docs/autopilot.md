# Autopilot + board metrics (AGE-30)

`agentized autopilot` (`show`/`set-wip`/`next`/`metrics`/`refresh`). Config `context/board.json`; metrics gitignored.

`enabled` must be a JSON boolean. `pick_from`/`count_as_wip` must be non-empty canonical lists (typos fail closed). HTML board = AGE-37. Cycle/blocked ages need Progress `статус → done|blocked` from `agentized status`; else `*.samples` stay 0 while `counts` still show. Metrics set `timing_source: progress_status_arrows`. Context confinement helpers: `runtime/agentized/context_paths.py` (public; not `paths.py` whole-file mutmut).
