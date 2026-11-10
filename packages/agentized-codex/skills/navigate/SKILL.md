---
name: navigate
description: Navigate Agentized Project Context via NAV.md and live indexes. Use at session start and whenever locating tasks, leases, decisions, goals, or digests.
---

# Navigate (Agentized)

## When to use

- Session start after connect
- Finding active work, leases, digests, decisions, or goals
- Before creating or claiming work

## Instructions

1. Read the Project Context pointer in root `AGENTS.md` (and `CLAUDE.md` if present).
2. Open `{context}/NAV.md` next. Follow **only** links from NAV.
3. For tasks, open `{context}/tasks/INDEX.md` (active statuses only: open / in-progress / blocked).
4. Use grep for id, title, or tags when INDEX is not enough.
5. **Never** list or walk the entire `{context}/tasks/` directory as the search strategy.
6. Leases live at `{context}/leases/INDEX.md`. Decisions and goals are siblings of `tasks/`, not nested under it.
7. Prefer `python3 runtime/agentized_cli.py sync-status` for a compact live snapshot.
