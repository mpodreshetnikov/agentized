# Autopilot + board metrics (AGE-30)

CLI: `agentized autopilot` (`show` / `set-wip` / `next` / `metrics` / `refresh`).
Config `{context}/board.json`; metrics `{context}/board/metrics.json` (gitignored).

- `enabled` must be a JSON boolean (strings like `"false"` → exit 1).
- `pick_from` / `count_as_wip` must be non-empty canonical status lists (typos fail closed).
- HTML board render is AGE-37 (`agentized board`), not this command.
- Cycle/blocked ages need Progress stamps from `agentized status` (`статус → done|blocked`). Without stamps, `*.samples` stay 0 while `counts` still reflect statuses. Metrics set `timing_source: progress_status_arrows`.
