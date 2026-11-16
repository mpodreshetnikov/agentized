# Dashboard V1 — static task board (AGE-37)

Harness-independent kanban from `context/tasks/*.md`. One self-contained HTML file. **No server, no auth, no deploy target in Agentized.**

- **Renderer:** `runtime/agentized/board_html.py` (+ `board_html_io.py`, `board_html_ui.py`)
- **CLI:** `agentized board` = render only
- **Autopilot / metrics / WIP:** `agentized autopilot` (AGE-30 / #19) — not this command
- **Status gates:** AGE-22 · **status_guard:** AGE-38
- **Reviewers:** `context/merge_policy.json` → `human_participants` (for-review note)

## Generate

```bash
./bin/agentized board                 # → ./board.html (lang=ru by default)
./bin/agentized board --lang en -o dist/board.html
./bin/agentized board --stamp
```

Fail-loud: bad UTF-8, empty file, header id ≠ stem, duplicate id/field, missing/unknown status, bad/future Progress stamp → non-zero exit `path: reason`. Fields only from header (before first `##`). Age = last Progress stamp with `→ <current status>` (optional `статус`/`status`/`task`); no match → unknown age → queue/self-review overdue.

Columns follow `status_gates.COLUMN_FOR_STATUS` (#25 @ f44e46e): Открыто (idea+open) · Очередь (queue + self-review; overdue &gt;12ч) · В работе · На ревью (только &lt;reviewer&gt;) · Заблокировано · Готово · Отменено.

Status vocabulary: import `CANONICAL_STATUSES` / `STATUS_ALIASES` / `COLUMN_FOR_STATUS` / `normalize_status` from `status_gates` (#25) — board does not keep a local list.

## CI dogfood

Board step must fail on bad tasks (no soft `|| echo`). Upload `task-board` stays `if: always()`.
