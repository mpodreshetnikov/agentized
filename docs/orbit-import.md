# Orbit import (`agentized import-orbit`)

```bash
./bin/agentized import-orbit --source path/to/fixtures
./bin/agentized import-orbit --source path/to/fixtures --write
```

Sources: only `T-*.md`. Other `*.md` → WARN. Zero `T-*.md` → exit 1.
Already-imported skips → exit 0 (dry-run and `--write`). Default dry-run; `--write` rebuilds INDEX.
Exit 0 iff `report.errors` empty.
Orbit `review`/`blocked` → `open` (original in body: `Orbit status: …`); `idea`/`open`/`in-progress` unchanged.
`done`/`dropped` → not imported (`skipped: closed in Orbit (N)`, exit 0). `depends_on`/`superseded_by` pointing at a
closed task is dropped from the front matter and kept as a body note under `## Imported body`:
`depends_on Orbit <id>: closed in Orbit, not imported` (same wording for `superseded_by`). The report adds
`closed edges noted in body: N` (JSON `closed_edges`), exit 0. An edge to an id that is neither imported, already
imported (`orbit_id`) nor closed in the same source → error (nothing written). Any other status (e.g. `canceled`,
`in-review`, `wip`) → error.
Orbit `owner` and `blocked_by` are optional after mapping (`review`/`blocked` become `open`, which needs neither).
