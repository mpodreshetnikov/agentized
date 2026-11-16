---
name: registry
description: Create, claim, and update Agentized tasks with confirmation, append-only Progress, INDEX, and hard status gates.
---

# Registry (Agentized)

1. Create: `python3 runtime/agentized_cli.py new --title "…" --value "…"` (no `--yes` except tests).
2. Status field only — never move task files. Lifecycle: `idea→open|queue→in-progress→self-review|for-review|blocked→done|canceled` (`dropped`→canceled).
3. Hard gates (CLI/pre-commit/CI): transitions vs PR base; empty статус refuse; blocked needs reason+deadline; review needs note or real pr; done needs acceptance_note; new tasks need Ценность.
4. Status: `… status T-… --status …` (+ gate flags). Claim: `… claim T-… --owner <human>`. Progress append-only. Then `… index` and `… tasks-validate`.
5. Subtasks: one nest level via `родитель:`. Do not invent backlog.
