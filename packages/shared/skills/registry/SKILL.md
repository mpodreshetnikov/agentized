---
name: registry
description: Create, claim, and update Agentized tasks with human confirmation, status fields, append-only Progress, and live INDEX regeneration.
---

# Registry (Agentized)

## When to use

- Creating a task or one-level subtask
- Claiming work before code edits
- Writing Progress / Decision Log entries
- Changing task status

## Instructions

1. **Create** with human confirmation by default:
   - `python3 runtime/agentized_cli.py new --title "…"`
   - Do **not** pass `--yes` in normal human sessions (autotests only).
2. Task status is a field at the start of the task file (`статус:`). **Do not move files** when status changes.
3. Lifecycle: `idea → open → in-progress → blocked → done | dropped`.
4. **Claim before code**:
   - `python3 runtime/agentized_cli.py claim T-… --owner <human>`
5. Subtasks: separate files, one nesting level, `родитель:` set to parent id. Claim/board/leases operate on children.
6. Progress and Decision Log are **append-only**:
   - `python3 runtime/agentized_cli.py progress T-… --text "…"`
7. After create/claim/status changes, regenerate the live board:
   - `python3 runtime/agentized_cli.py index`
8. Do not invent backlog. Tasks appear during real work, not as pre-seeded examples.
