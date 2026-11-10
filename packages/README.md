# Harness packages (local install only)

Pinned skill/hook **source** lives in `shared/`. Connect copies into `context/` and wires official project paths.

| Package | Official manifest | Local load (no marketplace publish) |
|---------|-------------------|-------------------------------------|
| `agentized-cursor/` | `.cursor-plugin/plugin.json` | `~/.cursor/plugins/local/agentized` or `cursor-agent --plugin-dir packages/agentized-cursor` |
| `agentized-claude/` | `.claude-plugin/plugin.json` | `claude --plugin-dir packages/agentized-claude` |
| `agentized-codex/` | `.codex-plugin/plugin.json` | project `.codex/hooks.json` via connect; optional `codex plugin marketplace add .` |

Do not publish these to public marketplaces as part of V1 morning verification.
