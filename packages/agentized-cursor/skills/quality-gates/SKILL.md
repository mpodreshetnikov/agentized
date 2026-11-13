---
name: quality-gates
description: Run Agentized coverage and mutation hard gates via the CLI.
---

# Quality gates

- Config: `context/quality.json` (default coverage 80% lines & branches).
- Primary command: `./bin/agentized quality check` (or `python3 runtime/agentized_cli.py quality check`).
- Optional: `./tests/test_mechanical.sh` when present in the repo.
- Connect installs pre-push/CI templates that call `quality check`; mechanical and `requirements-dev.txt` run only if those files exist.
- Do not bypass a failing coverage or mutation hard gate.
