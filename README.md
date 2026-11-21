# agentized

Слой координации агентной команды поверх git (dogfooding в этом репозитории).

## Быстрый старт

```bash
./bin/agentized connect
./bin/agentized check
./tests/test_mechanical.sh
pip install -r requirements-dev.txt
./bin/agentized quality check
# optional dogfood wrappers still under scripts/quality/
```

Утренний сценарий §9.4: [`docs/morning-runbook.ru.md`](docs/morning-runbook.ru.md).  
Контракт connect: [`docs/connect-contract.md`](docs/connect-contract.md).  
Quality gates: [`docs/QUALITY.md`](docs/QUALITY.md).  
Канон: [`docs/target-architecture.md`](docs/target-architecture.md).

Project Context: [`context/NAV.md`](context/NAV.md). Coverage defaults live in [`context/quality.json`](context/quality.json) (80% lines/branches; `connect --coverage <pct>`).

`context/process-control.json` is **required**: `agentized check` fails hard if it is missing (fail-closed). See [`docs/connect-contract.md`](docs/connect-contract.md).

### Tip hygiene (AGE-76)

Before opening a PR for Lead review:

```bash
./bin/agentized ready <TASK_ID> --review-note "…" --pr '#N'
./bin/agentized tasks-validate
```

CI/`tasks-validate` hard-fails when INDEX is stale, or (on a pull request) when no task links `pr:` to this PR / status is not `self-review|done` / claim is not released. Details: [`docs/process-control.md`](docs/process-control.md) (Tip hygiene).
