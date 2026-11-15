# Agent environment (Agentized)

What a cloud environment that runs agents on Agentized must carry, why, and how a session proves it.

An agent session that fails `./bin/agentized env-check` with **REFUSED** must change nothing in the repository until the owner fixes the environment.

Supported recipes: **Claude Code**, **Cursor**, **Codex**. Unknown agent harnesses are fail-closed. Agents must not edit the Cursor Dashboard / `environment.json` — the environment owner applies the recipes below.

## New developer checklist

| Surface | Out of the box after connect | Manual once |
| --- | --- | --- |
| Claude / Cursor / Codex **local** | Project hooks from connect (`.cursor/hooks.json`, `.claude/settings.json`, `.codex/hooks.json`) | `connect` sets `core.hooksPath=.githooks` when unset |
| Cursor Cloud | Project `.cursor/hooks.json` loads automatically | **Owner** adds the Install & Start line below |
| Claude cloud / Codex cloud | Project hooks when the session starts in the checkout; otherwise paste the user-layer recipe below | Owner Dashboard / Setup script |
| Any other agent | — | **Not supported** — `env-check` refuses |

Prove any agent/cloud session:

```bash
./bin/agentized env-check
# or: python3 runtime/agentized_cli.py env-check
```

## Self-healing `.githooks` bind (all harnesses)

After `connect`, project hooks call `ensure_agent_hooks.py` before git commit/push:

| Harness | Hook |
| --- | --- |
| Cursor | `.cursor/hooks.json` → `beforeShellExecution` |
| Claude | `.claude/settings.json` → `PreToolUse` / `Bash` |
| Codex | `.codex/hooks.json` → `PreToolUse` / `Bash` |

Behavior (idempotent, never blocks the shell):

- Local / Claude / Codex: set `core.hooksPath=.githooks` when unset (preserves user paths and Cursor `agent-hooks`).
- Cursor Cloud: when `~/.cursor/agent-hooks/<id>/` + `.dispatcher` exist, wire the chain to this repo’s `.githooks`.

## Cursor Cloud setup (owner Dashboard + self-heal)

Cursor Cloud owns each checkout's `core.hooksPath` → `~/.cursor/agent-hooks/<id>/`. Until that dispatcher chains this repo's `.githooks`, pre-push quality gates never run.

**Preferred:** keep this **exact** line in the environment **Install** and **Start** scripts (Cursor Dashboard → Cloud Agents → this environment → Install / Start / `environment.json`), after Cursor has created `~/.cursor/agent-hooks/<id>/`:

```sh
bash /agent/repos/agentized/scripts/cloud/configure-cursor-agent-hooks.sh
```

**Fallback:** `beforeShellExecution` / Claude·Codex `PreToolUse` self-heal on the first `git commit`/`git push` in-session. Still paste the Install line for sessions that skip hooks.

Then start a **new** session. Do not rewrite `~/.cursor/agent-hooks` by hand from an agent session.

### Rollout safety (`cloud_git_hooks`)

[`context/env-check.json`](../context/env-check.json) defaults to `"cloud_git_hooks": "warn"`.

**Why:** On this Project's live workers today, Cursor agent-hooks exist but `pre-push` is missing and `.cursor-original-hooks-path` still points at `.git/hooks`. Enabling hard refuse **before** the Dashboard paste would REFUSE every Agentized cloud worker (including PR agents) and deadlock the stack.

| Mode | Behavior |
| --- | --- |
| `warn` (default) | Cursor Cloud prints WARN + the Install line; exit 0 if project hooks OK |
| `refuse` | Cursor Cloud REFUSED + exit 1 when the git chain is unwired |

**Owner action before flipping to `refuse`:** paste the Install & Start line above into Agentized’s Cursor Cloud Environment, verify `./bin/agentized env-check` passes with the chain wired, then set `"cloud_git_hooks": "refuse"` (PR or direct edit).

## Claude Code cloud (optional user bridge)

When a multi-repo Claude cloud session starts above the clone, project `.claude/settings.json` may not load. Paste a Setup-script block that routes events through a small command that runs Agentized session hooks from the checkout (path adjust if the clone is elsewhere):

```sh
mkdir -p ~/.claude
# Minimal: SessionStart runs Agentized session_start when the checkout exists.
cat > ~/.claude/settings.json <<'JSON'
{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"f=/agent/repos/agentized/.claude/hooks/session_start.py; [ -f \"$f\" ] && exec python3 \"$f\"; exit 0"}]}]}}
JSON
```

Prefer starting the session inside the agentized checkout after `connect` so project settings apply directly.

## Codex

Trust project `.codex/hooks.json` after connect, or paste an equivalent user `~/.codex/hooks.json` that runs `.codex/hooks/session_start.py` from the checkout.

## Enforcement

- `AGENTS.md` / `CLAUDE.md` (connect pointer): run `env-check` before the first change in agent/cloud sessions.
- CLI: `./bin/agentized env-check` (exit 1 on REFUSED).
- Session-start hook appends an env-check reminder when the session is an agent harness.

Process-control (claim / PR size): see [`process-control.md`](./process-control.md).
