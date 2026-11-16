---
name: registry
description: Create, claim, and update Agentized tasks with human confirmation, status fields, append-only Progress, and live INDEX.
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
   - `--value` becomes the required plain-language `Ценность:` line.
   - Do **not** pass `--yes` in normal human sessions (autotests only).
2. Task status is a field at the start of the task file (`статус:`). **Do not move files** when status changes.
3. Lifecycle: `idea → open|queue → in-progress → self-review|for-review|blocked → done | canceled` (`dropped` alias → canceled).
4. **Hard status gates** (CLI, git pre-commit, CI) — invalid → blocking failure:
   - Allowed transitions only (checked vs PR base, not PR HEAD)
   - Missing/empty `статус` → refuse
   - `blocked` → `blocked_reason` + `blocked_deadline` (YYYY-MM-DD)
   - `self-review` / `for-review` → `review_note` or real `pr` (`#N` / `PR #N` / github pull URL)
   - `done` → real `acceptance_note` field (body "merged" alone is not enough)
   - New tasks → `Ценность:` line required
5. Status change via CLI (preferred):
   - `python3 runtime/agentized_cli.py status T-… --status blocked --blocked-reason "…" --blocked-deadline YYYY-MM-DD`
   - `… --status self-review --review-note "…" --pr "#12"`
   - `… --status done --acceptance-note "owner accepted on call"`
6. **Claim before code**:
   - `python3 runtime/agentized_cli.py claim T-… --owner <human>`
7. Subtasks: separate files, one nesting level, `родитель:` set to parent id. Claim/leases operate on children.
8. Progress and Decision Log are **append-only**:
   - `python3 runtime/agentized_cli.py progress T-… --text "…"`
9. After create/claim/status changes, regenerate the live markdown index:
   - `python3 runtime/agentized_cli.py index`
10. Validate gates: `python3 runtime/agentized_cli.py tasks-validate`
11. Do not invent backlog. Tasks appear during real work, not as pre-seeded examples.
