---
name: acceptance-artifacts
description: Mandatory handoff evidence for Agentized PRs and finished tasks — short what-changed + what-to-verify, screenshots or explicit none-reason, Mermaid for logic/architecture changes. Use before every owner-facing delivery.
---

# Acceptance artifacts

Never hand over a bare PR number.

## Required in every finish message

1. **What changed** — 1–2 sentences.
2. **What to verify** — 1–2 concrete checks for the reviewer.
3. **Evidence**
   - UI / visible surface: before/after screenshots (or recording), with captions.
   - No visible surface: exactly one line  
     `screenshots: none — <reason>`  
     Silence is not allowed.
4. **Diagram** — when control flow, architecture, or multi-module wiring changed, include a short Mermaid (or equivalent) sketch.

## Screenshots (adapted mechanism; stack-agnostic)

- Capture the affected surface after the change; before/after when fixing existing UI and cheap to do.
- Store under `.artifacts/review-screenshots/` (gitignored). Never commit binary screenshots to source trees.
- If capture is blocked, say `blocked: <external reason>` — do not drop the line.

## Reviewer contract

The owner must be able to judge the result from the message + artifacts without re-running the whole session.
