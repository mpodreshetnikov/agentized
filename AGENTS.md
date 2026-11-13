# Agentized

<!-- AGENTIZED:BEGIN -->
## Project Context (Agentized)

- Путь к Project Context: [`context/`](context/).
- В начале сессии прочитай [`context/NAV.md`](context/NAV.md).
- Дальше иди **только** по ссылкам из `NAV.md` (не обходи каталоги Context наугад).
- Живой индекс задач: [`context/tasks/INDEX.md`](context/tasks/INDEX.md).
- Path leases (warn-only): [`context/leases/INDEX.md`](context/leases/INDEX.md).
- Runtime: `./bin/agentized` · `python3 runtime/agentized_cli.py` · или `agentized` на PATH.
- Перед первой правкой в agent/cloud сессии: `agentized env-check` (REFUSED → стоп; см. `docs/AGENT_ENVIRONMENT.md`).
- Claim перед правками кода: `agentized claim <TASK_ID> --owner <you>` (см. `docs/process-control.md`).
- **No GitHub Stacked PRs:** every PR targets `main` (or the repo default), never another feature/PR branch. Sequence merges, or ship one PR.
- **Caveman `ultracave`:** working agents — max compression (no fluff/greetings/recaps). Keep facts, numbers, negations (`no`/`not`/`never`/`only`), decisions. Clear prose only for irreversible confirms, risk warnings, step sequences/test plans. **Exception:** the `reviewer` agent never uses caveman.
- Handoff: `acceptance-artifacts` skill + `context/reporting.json` (`short` default / `technical`).
<!-- AGENTIZED:END -->
