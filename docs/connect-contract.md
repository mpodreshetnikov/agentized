# Контракт connect (V1)

Дата: 2026-11-10.  
Канон: [`target-architecture.md`](./target-architecture.md) §3, §6, §11.15–16.  
Установка плагинов — **локально из этого репозитория**. Marketplace publish и свой updater — вне scope.

---

## 1. Что делает connect

Команда:

```bash
./bin/agentized connect
# or: python3 runtime/agentized_cli.py connect
# or (external repo with Agentized on PATH): agentized connect
./bin/agentized connect --coverage 85   # optional threshold pin
```

Идемпотентна. Повторный запуск дополняет/обновляет те же маркеры, не плодит дубликаты.

### Обязательные эффекты

| Артефакт | Поведение |
|----------|-----------|
| Корневой `AGENTS.md` | Блок между `<!-- AGENTIZED:BEGIN -->` … `<!-- AGENTIZED:END -->`: путь к Context, читать `NAV.md`, дальше только его ссылки |
| `CLAUDE.md` | Если файл **уже есть** — тот же указатель; если нет — connect его **не создаёт** |
| `{context}/skills/` | Pinned: `navigate`, `registry`, `lease-sync`, `digest`, `quality-gates`, `communication-autonomy`, `acceptance-artifacts`, `strong-reviewer` |
| `{context}/agents/` | Pinned readonly `reviewer.md` (model from `quality.json` → `reviewer.model`) |
| `.cursor/agents/`, `.claude/agents/`, `.codex/agents/` | Same reviewer agent for harness subagents |
| `{context}/hooks/scripts/` | `session_start.py`, `process_guard.py`, `lease_warn.py`, `_bootstrap.py` |
| `{context}/quality.json` | Пороги coverage (default 80%) · modules · mutation hard gate; `connect --coverage <pct>` |
| `{context}/process-control.json` | Claim before edits · reviewable PR size (default 1500 / warn 75%) |
| `.githooks/pre-push` | Шаблон → `agentized quality check` (+ process size warn); CLI: `./bin/agentized` → `runtime/` → `command -v agentized`; mechanical / `requirements-dev.txt` — только если есть в целевом репо |
| `.github/workflows/ci.yml` | То же для CI workflow |
| `core.hooksPath` | Локально → `.githooks`, если ещё не задан; чужой путь и Cursor `agent-hooks` не перезаписываются |
| `{context}/env-check.json` | `cloud_git_hooks` warn\|refuse; connect создаёт default без clobber |
| `scripts/cloud/configure-cursor-agent-hooks.sh` | 1-line Dashboard Install & Start (см. [`AGENT_ENVIRONMENT.md`](./AGENT_ENVIRONMENT.md)) |
| Session-start hook | Context/`NAV.md` reminder + env-check; safe if local `runtime/` missing |
| Process-guard hook | Claim required before Write/Edit (agent=refuse, local=warn) |
| Lease-overlap hook | **Warn-only**: пересечение write-paths, **не** блокирует запись |
| External connect | Нет локальных `packages/` / `templates/quality` → берёт их из **installed Agentized root** |
| `.agentized/connect.json` | Локальный маркер состояния (в `.gitignore`) |

По умолчанию Context = вложенный каталог `context/` в этом репозитории.

---

## 2. Какие файлы появляются в workspace по harness

Источник skills/hooks: `packages/shared/` → pinned в `context/` → wiring в официальные project-пути harness.

### Cursor (основной утренний путь)

Официальные поверхности ([Skills](https://cursor.com/docs/skills), [Hooks](https://cursor.com/docs/hooks), [Plugins](https://cursor.com/docs/reference/plugins)):

| Путь | Назначение |
|------|------------|
| `.cursor/skills/*/SKILL.md` | Project skills |
| `.cursor/hooks.json` | `sessionStart`, `preToolUse`, `afterFileEdit` |
| `.cursor/hooks/*.py` | Скрипты hooks |

Опционально официальный local plugin (без marketplace):

```bash
mkdir -p ~/.cursor/plugins/local
rm -rf ~/.cursor/plugins/local/agentized
cp -R packages/agentized-cursor ~/.cursor/plugins/local/agentized
# или CLI: cursor-agent --plugin-dir packages/agentized-cursor
```

Манифест: `packages/agentized-cursor/.cursor-plugin/plugin.json`.

### Claude Code

Официальные поверхности ([`.claude` directory](https://code.claude.com/docs/en/claude-directory), [hooks](https://code.claude.com/docs/en/hooks), [plugins](https://code.claude.com/docs/en/plugins/overview)):

| Путь | Назначение |
|------|------------|
| `.claude/skills/*/SKILL.md` | Project skills |
| `.claude/settings.json` → `hooks` | `SessionStart`, `PreToolUse` |
| `.claude/hooks/*.py` | Скрипты |

Опционально session plugin без публикации:

```bash
claude --plugin-dir packages/agentized-claude
```

Манифест: `packages/agentized-claude/.claude-plugin/plugin.json`.

### Codex

Официальные поверхности ([AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [hooks](https://learn.chatgpt.com/docs/hooks.md), [plugins](https://developers.openai.com/plugins/build/plugins)):

| Путь | Назначение |
|------|------------|
| `.agents/skills/*/SKILL.md` | Project skills (Codex также читает совместимые каталоги skills) |
| `.codex/hooks.json` | Project hooks: `SessionStart`, `PreToolUse` |
| `.codex/hooks/*.py` | Скрипты |
| `.agents/plugins/marketplace.json` | Локальный marketplace → `packages/agentized-codex` |

```bash
# после connect:
codex plugin marketplace add .
# затем установка agentized@agentized-local через UI/CLI Codex
```

**Зазор:** у Codex нет стабильного `codex --plugin-dir` (feature request upstream). Connect поэтому обязательно пишет **project** `.codex/hooks.json` + skills — это тестовый путь без marketplace publish. Plugin-bundled hooks могут требовать user trust.

Манифест: `packages/agentized-codex/.codex-plugin/plugin.json`.

---

## 3. Какое поведение обязано включиться

После connect агент **должен**:

1. В начале сессии опереться на `AGENTS.md` → `NAV.md` (hook напоминает; модель не гарантирована на 100%).
2. Искать работу через живой `tasks/INDEX.md` + grep, **не** обходя весь `tasks/`.
3. Создавать задачи с human confirmation; claim **до** правок кода.
4. Публиковать path lease перед пересекающимися правками; при overlap — принять **warn**, не lock.
5. Писать append-only Progress; участвовать в регулярном digest (development и/или management).
6. Не перемещать файлы задач при смене статуса.

Гарантия runtime/hooks: layout, индексы, warn-only leases, идемпотентность connect.  
**Не** гарантия: что модель всегда подчинится skills.

---

## 4. Runtime CLI (минимум сценария §9.4)

```text
connect | new | claim | progress | status | index | check
lease acquire|release|list|check | sync-status | digest
```

Подробный утренний сценарий: [`morning-runbook.ru.md`](./morning-runbook.ru.md).
