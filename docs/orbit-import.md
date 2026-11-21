# Orbit import (`agentized import-orbit`)

```bash
./bin/agentized import-orbit --source path/to/fixtures
./bin/agentized import-orbit --source path/to/fixtures --write
```

- Sources: only `T-*.md` (file or recursive dir).
- Other `*.md`: WARN listed; not imported.
- Zero `T-*.md` → exit **1**.
- Already-imported (orbit_id or dest exists): skip, exit **0** (dry-run and `--write`).
- Default dry-run; `--write` writes tasks + rebuilds `INDEX.md`.
- Exit 0 iff `report.errors` empty; else 1.
