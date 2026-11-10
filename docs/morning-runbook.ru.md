# Утренний прогон §9.4 (dogfooding)

Цель: к утру 2026-11-11 (Asia/Krasnoyarsk) человек может прогнать сценарий из `docs/target-architecture.md` §9.4 на **этом** репозитории и вложенном `context/`.

Два участника (люди или две агентные сессии): **A** и **B**.  
Основной путь утра: **Cursor**. Claude Code и Codex — рабочие локальные connect через их официальные средства.

---

## 0. Подготовка (один раз)

```bash
git clone https://github.com/mpodreshetnikov/agentized.git
cd agentized
git checkout <ветка-PR-или-main-после-мержа>   # владелец ещё не мержит за вас
python3 --version   # ≥ 3.10
```

Не создавайте второй git-репозиторий. Не копируйте содержимое Orbit/ProjectStore. Не сидите задачи заранее в `context/tasks/` — они появляются в сценарии.

---

## 1. Connect (A, затем B)

```bash
./bin/agentized connect
# эквивалент: python3 runtime/agentized_cli.py connect
./bin/agentized check
```

### Что произошло автоматически

- Дописан/обновлён блок Project Context в `AGENTS.md`
- Если уже был `CLAUDE.md` — указатель и туда
- Pinned skills → `context/skills/`
- Pinned hooks → `context/hooks/scripts/`
- Wiring:
  - Cursor: `.cursor/skills`, `.cursor/hooks.json`
  - Claude Code: `.claude/skills`, `.claude/settings.json` hooks
  - Codex: `.agents/skills`, `.codex/hooks.json`, `.agents/plugins/marketplace.json`

### Cursor (primary)

1. Откройте этот репозиторий в Cursor.
2. Перезагрузите окно при необходимости (чтобы подхватить `.cursor/hooks.json` / skills).
3. Опционально local plugin:  
   `cp -R packages/agentized-cursor ~/.cursor/plugins/local/agentized`
4. Новая Agent-сессия **A**: в контексте должен быть reminder про `context/NAV.md` (sessionStart hook). Прочитайте `context/NAV.md` и `context/tasks/INDEX.md`.

### Claude Code

```bash
claude --plugin-dir packages/agentized-claude
# project hooks из connect уже в .claude/settings.json
```

### Codex

```bash
# project hooks уже в .codex/hooks.json после connect — этого достаточно для теста
# опционально официальный local marketplace:
codex plugin marketplace add .
# затем install agentized@agentized-local в UI/CLI; hooks плагина могут спросить trust
```

**Зазор Codex (один раз):** нет стабильного `--plugin-dir`; опираемся на project `.codex/hooks.json` + `.agents/skills` после connect. См. `docs/connect-contract.md`.

Повторный `./bin/agentized connect` безопасен (идемпотентен).

---

## 2. Сценарий §9.4

Рабочая директория — корень репозитория. Команды ниже — механическая часть; skills направляют поведение агента в сессии.

### 2.1. A видит NAV / INDEX

В сессии A:

1. Открыть `context/NAV.md`.
2. Открыть `context/tasks/INDEX.md` (пусто до первой задачи — так и должно быть).
3. `./bin/agentized sync-status`

### 2.2. A создаёт задачу + claim + lease

**Создание требует подтверждения человека** (не передавайте `--yes` вручную в утреннем прогоне):

```bash
./bin/agentized new --title "Утренний dogfood §9.4"
# ответьте y
```

Запомните id (`T-YYMMDD-xxxx`). При необходимости подзадача:

```bash
./bin/agentized new --title "Подзадача: правка runtime" --parent T-YYMMDD-xxxx
```

Claim + lease на пересекаемый путь (пример — сам runtime):

```bash
./bin/agentized claim T-YYMMDD-xxxx --owner A
./bin/agentized lease acquire T-YYMMDD-xxxx runtime --owner A
./bin/agentized index
./bin/agentized sync-status
```

A может начать писать Progress:

```bash
./bin/agentized progress T-YYMMDD-xxxx --text "старт утреннего прогона"
```

### 2.3. B connect → видит claim/lease → warn на overlap

В **второй** сессии (B), том же checkout или свежем clone той же ветки с закоммиченными/синхронизированными файлами Context:

```bash
./bin/agentized connect
./bin/agentized sync-status
./bin/agentized lease check runtime
```

Ожидание: текст **LEASE WARN** (warn-only). Запись **не** блокируется.

Проверка hook-пути (без блокировки):

```bash
# эмуляция stdin для Cursor/общего скрипта
printf '%s' '{"tool_input":{"file_path":"runtime/agentized_cli.py"}}' \
  | python3 context/hooks/scripts/lease_warn.py
```

Должны увидеть JSON с `"permission": "allow"` и текстом WARN.

B может легитимно писать в тот же путь (merge ожидается) — в v1 это норма.

### 2.4. A: Progress + закрытие lease + digest

```bash
./bin/agentized progress T-YYMMDD-xxxx --text "закрываю lease, пишу digest"
./bin/agentized lease release T-YYMMDD-xxxx
./bin/agentized digest --type development --notes "A: утренний dogfood, lease снят"
./bin/agentized digest --type management --notes "Статус: сценарий §9.4 в процессе"
./bin/agentized sync-status
```

### 2.5. B продолжает с актуальным контекстом

B читает:

- `context/tasks/INDEX.md` / файл задачи A
- `context/leases/INDEX.md`
- свежие файлы в `context/digests/development/` и/или `management/`

```bash
./bin/agentized sync-status
./bin/agentized check
```

Опциональный второй code-репо в том же Context **не требуется**.

---

## 3. Что автоматически / что руками

| Шаг | Автоматически (CLI/hooks) | Вручную / модель |
|-----|---------------------------|------------------|
| Connect layout, pinned skills/hooks | CLI `connect` | Перезапуск сессии harness |
| Reminder про NAV | session-start hook | Модель должна прочитать NAV |
| Создание задачи | CLI (+ prompt y/N) | Человек подтверждает |
| Claim / lease / index / digest | CLI | Агент инициирует по skills |
| Warn при overlap | CLI `lease check/acquire` + hook | Модель учитывает warn |
| Блокировка записи при overlap | **нет** (и не должна появиться в v1) | — |
| Подчинение skills | не гарантируется тестами | Наблюдается в сессии |

---

## 4. Автопроверки (механика)

```bash
./tests/test_mechanical.sh
```

Покрывает: connect layout, формат файла задачи, живой index, warn-only leases, идемпотентность connect.  
Не утверждает, что модель всегда слушается skills.

---

## 5. Честные зазоры

1. **Модель ≠ hook:** session-start и skills повышают шанс правильного поведения; 100% compliance не обещаем.
2. **Cursor cloud agents:** project `sessionStart` может быть deferred/ограничен в read-only окружении — для утра предпочтителен обычный Cursor Agent на локальном/VM checkout.
3. **Codex:** нет стабильного `--plugin-dir`; plugin hooks требуют trust; тестовый путь = project `.codex/hooks.json` после connect.
4. **Claude Code:** project `.claude/settings.json` hooks работают после connect; `--plugin-dir` — доп. путь без publish.
5. Файлы `.cursor/`, `.claude/`, `.codex/` после connect локальные (gitignore); pinned SoT — `context/skills`, `context/hooks`.
6. Шаг §9.7 (жёсткие hooks / goals UI / fail-closed leases) **не** делается.
