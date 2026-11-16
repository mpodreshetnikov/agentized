# Hooks (pinned copy)

Скрипты в `scripts/` — закреплённая копия из `packages/shared/hooks/scripts/`.

| Скрипт | Назначение |
|--------|------------|
| `session_start.py` | Reminder: читать `NAV.md` по указателю из `AGENTS.md` |
| `process_guard.py` | Claim-before-edits; may deny Write/Edit |
| `status_guard.py` | Hard status gates on `context/tasks/T-*.md` (fail-closed; source `packages/shared/hooks/scripts/`) |
| `lease_warn.py` | Warn-only overlap check; `permission: allow` всегда |

Harness wiring после `agentized connect`: `.cursor/hooks.json`, `.claude/settings.json`, `.codex/hooks.json`.
