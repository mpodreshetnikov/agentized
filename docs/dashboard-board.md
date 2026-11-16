# Dashboard V1 — static task board (AGE-37)

Harness-independent kanban from `context/tasks/*.md`. One self-contained HTML file. **No server, no auth, no deploy target in Agentized.** Delivery/hosting is the user’s own CI/CD.

Module: `runtime/agentized/board_html.py` (HTML only). Status-transition gates stay with AGE-22; harness `status_guard` with AGE-38.

## Generate locally

```bash
./bin/agentized board                 # → ./board.html (deterministic)
./bin/agentized board -o dist/board.html
./bin/agentized board --stamp         # optional generated-at UTC stamp
```

Same inputs → same bytes (unless `--stamp`). Task text is HTML-escaped. Columns: Open/Queue, In Progress, Self-Review, For Review, Blocked, Done, Canceled.

Display statuses: `idea`, `open`, `queue`, `in-progress`, `self-review`, `for-review`, `blocked`, `done`, `canceled` (aliases: `queued`→`queue`, `dropped`→`canceled`). `idea` / `open` / `queue` share the Open / Queue column.

## Deliver via your CI/CD (examples only — nothing enabled by default)

Agentized does **not** publish Pages or open a host for you. Wire one of these in **your** pipeline if you want a shared URL.

### GitHub Actions — upload artifact

```yaml
- name: Generate board
  run: ./bin/agentized board -o board.html
- uses: actions/upload-artifact@v4
  with:
    name: task-board
    path: board.html
```

### GitHub Pages (your workflow)

```yaml
- run: ./bin/agentized board -o public/index.html
- uses: peaceiris/actions-gh-pages@v4
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    publish_dir: ./public
```

### Generic rsync / scp behind your auth

```bash
./bin/agentized board -o board.html
rsync -av board.html user@your-server:/var/www/internal/board.html
```

## Dogfood (this repo)

CI generates `board.html` and uploads it as the `task-board` artifact. No Pages deploy is turned on by default.
