# Agentized

<!-- AGENTIZED:BEGIN -->
## Agentized Project Context

- Context path: `context/`
- Session start: read `context/NAV.md`, then follow only its links.
- Live task board: `context/tasks/INDEX.md`
- Leases (warn-only): `context/leases/INDEX.md`
- CLI: `./bin/agentized` · `python3 runtime/agentized_cli.py` · or `agentized` on PATH.
- Before the first change in an agent/cloud session: `agentized env-check` (REFUSED → stop; see `docs/AGENT_ENVIRONMENT.md`).
- Claim before code edits: `agentized claim <TASK_ID> --owner <you>` (see `docs/process-control.md`).
- **No GitHub Stacked PRs:** every PR targets `main` (repo default), never another feature/PR branch.
- **Caveman `ultracave`:** working agents — max compression; no fluff. **Exception:** `reviewer` never uses caveman.
- Handoff: `acceptance-artifacts` + `context/reporting.json` (`short` / `technical`).
<!-- AGENTIZED:END -->
