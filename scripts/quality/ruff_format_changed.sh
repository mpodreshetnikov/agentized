#!/usr/bin/env bash
# Hard ruff format --check on Python files changed vs BASE (AGE-48).
# Fail-closed: missing/invalid BASE or git diff errors exit 1.
set -euo pipefail

BASE="${1:-}"
if [[ -z "${BASE}" ]]; then
  echo "usage: $0 <base-sha-or-ref>" >&2
  exit 1
fi

git cat-file -e "${BASE}^{commit}" || {
  echo "invalid base commit: ${BASE}" >&2
  exit 1
}

if ! command -v ruff >/dev/null 2>&1; then
  echo "ruff not on PATH — install from requirements-dev.txt" >&2
  exit 1
fi

mapfile -t FILES < <(git diff --name-only --diff-filter=ACMR "${BASE}"...HEAD -- '*.py')
if ((${#FILES[@]} == 0)); then
  echo "no changed Python files — skip ruff format"
  exit 0
fi

echo "ruff format --check (${#FILES[@]} file(s) vs ${BASE})"
printf '  %s\n' "${FILES[@]}"
ruff format --check -- "${FILES[@]}"
