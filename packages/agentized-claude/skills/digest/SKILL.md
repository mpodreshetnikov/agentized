---
name: digest
description: Publish regular development or management digests into Project Context digests/ folders.
---

# Digest (Agentized)

## When to use

- End of a working session that moved shared context
- Daily development or management summary
- After Progress updates that other humans/agents need compressed

## Instructions

1. Prefer regular digests (including daily), two types: development and management.
2. Create with runtime:
   - `python3 runtime/agentized_cli.py digest --type development --notes "…"`
   - `python3 runtime/agentized_cli.py digest --type management --notes "…"`
3. Files land in `{context}/digests/development/` or `{context}/digests/management/`.
4. Digests are human-readable knowledge sharing — not a second progress ledger. Source of truth for live work remains tasks INDEX + task files.
5. Do not rewrite history; add a new dated digest if needed.
