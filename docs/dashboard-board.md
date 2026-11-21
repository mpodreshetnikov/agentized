# Dashboard V1 — static board (AGE-37)

## What `agentized board` shows

Renders a static HTML kanban from `context/tasks/*.md` (seven columns: Open, Queue, In Progress, For Review, Blocked, Done, Canceled). Self-review cards sit in Queue. Card text prefers the first real `## Цель` line, then a `Ценность:` line. Reviewers on For Review come from `context/merge_policy.json` → `human_participants` (all names joined). Vocab/columns: `status_gates` (AGE-22 / #25).

## Overdue (12h)

For `queue` and `self-review` only: age is the last Progress stamp whose line has `→ <current status>` (optional `статус` / `status` / `task` before the arrow). If that stamp is missing, the card is treated as overdue. Overdue when age **> 12** hours (`OVERDUE_HOURS`). A later Progress note without that arrow does not reset the clock.

## Fail-loud

Malformed task files raise `BoardError` as `path: reason` (bad header, stem≠id, dup fields/ids, bad UTF-8, bad/future Progress stamps, unknown status). The CLI exits **1** and prints `board FAIL: …`. In a connected repo, the CI **Generate task board** step hard-fails on that exit (no `|| echo`); upload stays `if: always()`.

## Publish examples

```bash
./bin/agentized board [--lang en] [-o path] [--stamp]
```

- **CI artifact:** workflow writes `board.html` and uploads it with the quality-reports artifact (see `.github/workflows/ci.yml`).
- **GitHub Pages (generic):** build `board.html` in CI, then deploy the file (or a `site/` folder that contains it) with `actions/upload-pages-artifact` + `actions/deploy-pages`, or copy into `docs/` / `gh-pages` the same way you publish any static HTML.

Render-only: metrics/WIP stay `agentized autopilot` (AGE-30 / #19).
