# Orbit import (`agentized import-orbit`)

```bash
./bin/agentized import-orbit --source path/to/fixtures
./bin/agentized import-orbit --source path/to/fixtures --write
```

Sources: only `T-*.md`. Other `*.md` → WARN. Zero `T-*.md` → exit 1.
Already-imported skips → exit 0 (dry-run and `--write`). Default dry-run; `--write` rebuilds INDEX.
Exit 0 iff `report.errors` empty.
Orbit `review`/`in-review`/`blocked` → `open` (original in body: `Orbit status: …`). `done`/`canceled` → not imported
(`skipped: closed in Orbit (N)`, exit 0). `depends_on`/`superseded_by` pointing at a closed task → error (nothing
written). Any other status (e.g. `dropped`, `wip`) → error.
