---
name: lease-sync
description: Publish warn-only path leases before overlapping code edits; check sync-status; never treat leases as write locks.
---

# Lease Sync (Agentized)

## When to use

- Before editing files that others might touch
- When another session may hold overlapping paths
- After finishing a claimed unit of work

## Instructions

1. Have a claimed task first (`registry` skill).
2. Acquire a lease on paths you intend to write:
   - `python3 runtime/agentized_cli.py lease acquire T-… path/or/dir --owner <human>`
3. If the CLI or a harness hook prints **LEASE WARN**, continue only with awareness. Writes are **not** blocked; merges are expected.
4. Check overlaps without acquiring:
   - `python3 runtime/agentized_cli.py lease check path/or/dir`
5. On completion / handoff, release:
   - `python3 runtime/agentized_cli.py lease release T-…`
6. Refresh awareness:
   - `python3 runtime/agentized_cli.py sync-status`
7. Never implement fail-closed locking in v1. Warn only.
