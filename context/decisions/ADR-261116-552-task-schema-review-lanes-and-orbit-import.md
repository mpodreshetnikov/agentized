# ADR-261116-552 — Task schema review lanes and Orbit import

- Status: accepted
- Date: 2026-11-16
- Tasks: T-261116-96ff

## Context

Agentized tasks need one status vocabulary (including review lanes and `canceled`), safe Orbit fixture import, and ADR titles that work in Cyrillic. PR size force-split import safety (#26) from ADR authoring (this PR).

## Decision

1. Canonical statuses + aliases live in `status_gates` / schema; Orbit `dropped`→`canceled`, `review`→`for-review`.
2. Orbit import refuses path escape, overwrite, unknown status, and non-UTF-8 per file; short ids convert with `orbit_id` preserved.
3. ADR slugs transliterate Cyrillic; `--status` limited to proposed|accepted|superseded|deprecated.

## Consequences

- #26 ships import/schema; this PR ships `adr` CLI + slug/status tests.
- After #25 merges, schema re-exports from `status_gates` (rebase, no stack).
