---
name: acceptance-artifacts
description: Single handoff/reporting skill for Agentized — short (default human 5-block) or technical (engineering). Use before every owner-facing delivery. Do not create competing reporting skills.
---

# Acceptance artifacts (reporting)

**One skill for both levels.** Config: `{context}/reporting.json` → `level` = `short` (default) | `technical`. Override: `agentized reporting set --level short|technical`.

## Two levels

| Level | Audience | Depth |
|-------|----------|-------|
| `short` (default) | Human owner / business | Business meaning only — the 5 blocks below |
| `technical` | Agents, reviewer, CI | Full engineering depth (paths, SHAs, gates, residual risks) |

Inside work (agents ↔ reviewer ↔ CI) stays engineering-complete. Outward to a human stays business meaning only. Put engineering detail in `technical` / internal notes — never mix it into the human report unless the owner asked for tech.

## Caveman / ultracave — **does not apply to human reports**

Working agents still use **caveman `ultracave`** for mid-flight agent↔agent notes and internal engineering chatter: max compression; no fluff, greetings, recaps, or padding grammar.

**Exceptions (never caveman):**

1. The `reviewer` agent — always expanded findings.
2. **Any human-facing acceptance report** (`short` default, digests/status/blockers to the owner) — clear prose, full sentences. Telegraph compression is forbidden here.

## `short` (default) — human report = **5 short blocks**

Write so a non-engineer understands without code, GitHub, or the tracker. Make the ask of them clear.

1. **What the task was** — problem/need, 1 sentence.
2. **What was done** — plain words, 1–2 sentences.
3. **Product result** — what is different now for user/business.
4. **Side effects, consequences, risks** — what was touched, what was left out, what could go wrong; if none, say so.
5. **Acceptance test plan** — concrete steps for the human to verify (or why manual check is not needed), and what decision is needed from them.

### Visual

- UI changed → before/after screenshots (captions in plain language).
- Logic / process / architecture changed → simple mermaid with **user-language** labels (no function or config names).
- Digest / status / blocker → same logic, shorter: product delta, ask of human, risk. Blocker form: what’s stuck, why, what’s needed, by when.

### Forbidden in the human report

- Bare task/PR numbers, commit hashes, branch names, file paths, function/config names, CLI commands, internal ids, jargon
- Asking to “open/review the PR” instead of a ready artifact
- Telegraph compression / caveman
- Process recap (“first I claimed… then I ran…”)

A PR link is OK **at the end**, with a plain-language why, only if needed. Tech details only on request.

**Self-check:** Would a non-engineer understand this without code/GitHub/tracker, and is the ask of them clear?

## `technical` — engineering handoff

For agents, reviewer, and CI — not the default owner message. Include:

- PR URL, head SHA, gates (tests / coverage / mutation) as numbers
- Key paths / decisions / residual risks
- How the human 5-block report maps to evidence (screenshot paths under `.artifacts/`, mermaid source)

Working-agent `technical` notes may use ultracave; never ship ultracave as the owner-facing `short` report.

## Screenshots

- Store under `.artifacts/review-screenshots/` (gitignored). Never commit binaries.
- Capture blocked → `blocked: <external reason>` — do not drop the line.
- In the human report, refer to screenshots by plain caption, not by path.

## Reviewer contract

Owner judges from the human report + artifacts without re-running the session. Never invent a second reporting skill.
