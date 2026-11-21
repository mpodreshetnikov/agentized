---
name: registry
description: Create, claim, and update Agentized tasks with human confirmation, status fields, append-only Progress, live INDEX, and hard status gates.
---

# Registry (Agentized)

## When to use

- Creating a task or one-level subtask
- Claiming work before code edits
- Writing Progress / Decision Log entries
- Changing task status

## Instructions

1. **Create** with human confirmation by default:
   - `python3 runtime/agentized_cli.py new --title "…" --value "…"`
   - Do **not** pass `--yes` in normal human sessions (autotests only).
2. Task status is a field at the start of the task file (`статус:`). **Do not move files** when status changes.
3. Lifecycle: `idea → open|queue → in-progress → self-review|for-review|blocked → done | canceled` (`dropped` → canceled).
4. Hard gates (CLI/CI): transitions vs PR base; empty статус refuse; blocked needs reason+deadline; review needs note or real pr; done needs acceptance_note; every task needs `Ценность:`; run `tasks-validate`.
5. **Claim before code**:
   - `python3 runtime/agentized_cli.py claim T-… --owner <human>`
6. Status: `… status T-… --status …` (+ gate flags). Subtasks: one nest level via `родитель:`.
7. Progress and Decision Log are **append-only**; then `index`.
8. Do not invent backlog. Tasks appear during real work, not as pre-seeded examples.
