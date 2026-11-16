# Dashboard V1 — static task board (AGE-37)

Harness-independent kanban from `context/tasks/*.md`. One self-contained HTML file. **No server, no auth, no deploy target in Agentized.**

- **Renderer:** `runtime/agentized/board_html.py` (+ `board_html_io.py`, `board_html_ui.py`)
- **CLI:** `agentized board` = render only
- **Autopilot / metrics / WIP:** `agentized autopilot` (AGE-30 / #19) — not this command
- **Status gates:** AGE-22 · **status_guard:** AGE-38

## Generate

```bash
./bin/agentized board                 # → ./board.html (lang=ru by default)
./bin/agentized board --lang en -o dist/board.html
./bin/agentized board --stamp
```

Fail-loud: missing `context/tasks`, empty file, missing/unknown status, or bad `# T-… — title` header → non-zero exit with `path: reason`. (`agentized board` = render only; metrics/WIP → `agentized autopilot` / #19.)

Columns (RU): Открыто · Очередь (queue + self-review; overdue &gt;12h) · В работе · На ревью («только Maxim») · Заблокировано · Готово · Отменено.

Description on cards: short `## Цель` line, else `Ценность:`.

## CI dogfood

Generate + upload `task-board` artifact runs with `if: always()` (even if quality fails).
