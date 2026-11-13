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
