---
name: acceptance-artifacts
description: Single handoff/reporting skill for Agentized — short (default) or technical level, caveman-compressed for working agents. Use before every owner-facing delivery. Do not create competing reporting skills.
---

# Acceptance artifacts (reporting)

**One skill for both levels.** Config: `{context}/reporting.json` → `level` = `short` (default) | `technical`. Override: `agentized reporting set --level short|technical`.

Working agents write in **caveman `ultracave`**: max compression; no fluff, greetings, recaps, or padding grammar. Keep facts, numbers, negations (`no`/`not`/`never`/`only`), decisions. Clear prose **only** for irreversible confirms, risk warnings, and step sequences / test plans.

**Exception:** the `reviewer` agent never uses caveman — always expanded findings.

Never hand over a bare PR number. Never invent a second reporting skill.

## `short` (default) — business-readable, compressed

- No code, no SHAs, no file paths unless the owner must click them.
- Max compression; still readable by a non-engineer owner.
- Required blocks (tight):

1. **What changed** — ≤2 short sentences.
2. **What to verify** — ≤2 concrete checks.
3. **Evidence** — UI: before/after captions; else exactly `screenshots: none — <reason>`.
4. **Diagram** — Mermaid only when control flow / architecture / multi-module wiring changed.

## `technical` — compressed engineering handoff

Same required blocks, plus:

- PR URL, head SHA, gates (tests / coverage / mutation) as numbers.
- Key paths / decisions / residual risks.
- Still ultracave: no padding, no recap of the assignment.

## Screenshots

- Store under `.artifacts/review-screenshots/` (gitignored). Never commit binaries.
- Capture blocked → `blocked: <external reason>` — do not drop the line.

## Reviewer contract

Owner judges from message + artifacts without re-running the session.
