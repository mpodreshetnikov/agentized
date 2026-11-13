#!/usr/bin/env bash
# Wire Cursor Cloud agent-hooks to each checkout's .githooks (AGE-8).
# Call from the environment Install AND Start scripts after Cursor has created
# ~/.cursor/agent-hooks/<id>/. Safe when agentized is missing or the dispatcher is not ready yet.
set -euo pipefail

find_agentized_root() {
  local candidate
  for candidate in \
    "${AGENTIZED_ROOT:-}" \
    "${PWD}" \
    "${PWD}/repos/agentized" \
    /agent/repos/agentized \
    /workspace/repos/agentized \
    /workspace \
    /home/user/agentized
  do
    if [[ -n "${candidate}" && -f "${candidate}/runtime/agentized/cursor_agent_git_hooks.py" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

ROOT="$(find_agentized_root || true)"
if [[ -z "${ROOT}" ]]; then
  echo "configure-cursor-agent-hooks: agentized checkout not found; skipping" >&2
  exit 0
fi

python3 "${ROOT}/runtime/agentized/cursor_agent_git_hooks.py" "${ROOT}" || true
