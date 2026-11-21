# Autopilot + board metrics (AGE-30)

WIP next-task + board metrics (dashboard **data**). HTML = AGE-37 — not this module.

## Subcommands

```bash
agentized autopilot show                 # print board.json
agentized autopilot set-wip 2            # wip_limit → 2
agentized autopilot next [--json]        # oldest pick_from under WIP, or reason
agentized autopilot metrics [--refresh]  # read/refresh metrics.json
agentized autopilot refresh [--json]     # recompute → board/metrics.json
```

`agentized index` creates `board.json` and writes metrics. `--context DIR` (default `context`).

## `board.json`

| Key | Default | Invalid → exit 1 |
|-----|---------|------------------|
| `wip_limit` | `3` | not JSON int ≥ 1 (`true`/`"3"`/`2.9`) |
| `autopilot.enabled` | `true` | not JSON bool |
| `autopilot.pick_from` | `["queue","open"]` | empty / non-canonical |
| `autopilot.count_as_wip` | `["in-progress","self-review"]` | empty / non-canonical |
| `metrics` | object | non-object (`"x"`) |
| `metrics.throughput_window_days` | `7` (max 3650) | not JSON int 1…3650 |
| `metrics.output` | `"board/metrics.json"` | non-string / abs / `..` |

Aliases: `dropped`→`canceled`, `queued`→`queue`. Metrics: `wip`/`counts`/`throughput`/`cycle_time`/`queue_age`/`blocked_age`/`next_task`/`autopilot`/`timing_source=progress_status_arrows`. **Limitation:** Progress `статус → X` only. `metrics.json` gitignored. Helpers: `context_paths.py`.
