# Dashboard V1 — static board (AGE-37)

`agentized board` → 7-column HTML from `context/tasks` (self-review → Queue). Prefer `## Цель`, else `Ценность:`. For Review joins all `merge_policy.human_participants`. Vocab: `status_gates`.

**Overdue:** queue/self-review age = last Progress `→ <current status>`; missing → overdue; **>12h** overdue. Fail-loud `BoardError` / CLI exit 1; CI board hard-fails (`if: always()` upload).
```bash
./bin/agentized board [--lang en] [-o path] [--stamp]
```
CI artifact `board.html`; Pages = deploy static file. Metrics: `agentized autopilot` (#19).
