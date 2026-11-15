# Batch release (reviewed PRs + shared CI)

Orbit / Maxim practice for connected projects:

1. Already-reviewed PRs may ship together behind **one shared CI** run (batch).
2. Do **not** weaken branch protection “require branches to be up to date before merging”.
3. Ordinary PRs target **`main`** only — no stacks unless the owner explicitly asks.
4. Agents open PRs and leave them for human merge; do not self-merge.

Agentized dogfood: same rules. Implementation is process + branch protection, not a runtime gate.
