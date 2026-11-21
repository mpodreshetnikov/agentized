---
id: ADR-261116-552
title: "ADR authoring format and status"
status: proposed
date: 2026-11-16
tasks: [T-261121-0766]
---

# ADR authoring format and status

## Context

Agentized needs one ADR authoring format (YAML front matter, Cyrillic-safe slugs, validated status/task ids) and a clear default that new ADRs stay `proposed` until a human confirms them (target-architecture § human-confirm for heavy artifacts).

## Decision

1. ADRs live under `context/decisions/` as `ADR-YYMMDD-xxx-<slug>.md` with YAML front matter produced by `agentized adr` (`id`, quoted `title`, `status`, `date`, `tasks`).
2. Default `--status` is `proposed`; allowed values are exactly `ADR_STATUSES` (proposed|accepted|superseded|deprecated). Title must be non-empty and free of C0/C1 controls and Unicode line/paragraph separators; each `--tasks` id must match `TASK_ID_RE`.
3. Slugs transliterate Cyrillic and drop a trailing hyphen after the 48-character cut.

## Consequences

- New ADRs are created as `proposed`; humans promote status after review.
- This ADR ships with AGE-44 / PR #35 and may merge independently of import/schema work.
- Callers use `agentized adr --title …` (optional `--status`, `--tasks`) rather than hand-rolled bullet headers.
