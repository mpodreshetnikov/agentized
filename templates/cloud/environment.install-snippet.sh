#!/usr/bin/env bash
# Paste into Cursor Cloud Environment Install + Start (environment.json / Dashboard).
# Self-heal also runs via beforeShellExecution / Claude·Codex PreToolUse Bash.
# AGENTIZED:CLOUD-GIT-HOOKS
set -euo pipefail
bash /agent/repos/agentized/scripts/cloud/configure-cursor-agent-hooks.sh
