#!/usr/bin/env bash
# Mechanical checks for Agentized V1 (connect layout, task format, index, warn-only leases, idempotency).
# Does NOT claim that models obey skills.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI=(python3 "$ROOT/runtime/agentized_cli.py")
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

pass=0
fail=0
assert() {
  local name="$1"
  shift
  if "$@"; then
    echo "PASS: $name"
    pass=$((pass + 1))
  else
    echo "FAIL: $name"
    fail=$((fail + 1))
  fi
}

echo "== Agentized mechanical tests =="
echo "workspace: $TMP"

# Isolated fake repo with nested context skeleton
mkdir -p "$TMP/repo/context/tasks" "$TMP/repo/context/leases" \
  "$TMP/repo/context/digests/development" "$TMP/repo/context/digests/management" \
  "$TMP/repo/context/decisions" "$TMP/repo/context/goals" \
  "$TMP/repo/runtime" "$TMP/repo/packages"
cp -R "$ROOT/runtime/." "$TMP/repo/runtime/"
cp -R "$ROOT/packages/." "$TMP/repo/packages/"
mkdir -p "$TMP/repo/templates/quality"
cp -R "$ROOT/templates/quality/." "$TMP/repo/templates/quality/" 2>/dev/null || true
cp "$ROOT/context/NAV.md" "$TMP/repo/context/NAV.md"
cp "$ROOT/context/tasks/TEMPLATE.md" "$TMP/repo/context/tasks/TEMPLATE.md"
cp "$ROOT/context/tasks/INDEX.md" "$TMP/repo/context/tasks/INDEX.md"
cp "$ROOT/context/leases/INDEX.md" "$TMP/repo/context/leases/INDEX.md"
if [[ -f "$ROOT/context/quality.json" ]]; then
  cp "$ROOT/context/quality.json" "$TMP/repo/context/quality.json"
fi
printf '%s\n' '# Agentized' '' '## Existing notes' '' '- keep me' > "$TMP/repo/AGENTS.md"
printf '%s\n' '# Claude notes' '' 'Keep existing CLAUDE.md' > "$TMP/repo/CLAUDE.md"
# minimal git marker so find_repo_root stabilizes
mkdir -p "$TMP/repo/.git"

cd "$TMP/repo"

echo "-- connect --"
"${CLI[@]}" connect >/tmp/agentized-connect-out.txt
assert "AGENTS.md has NAV pointer" grep -q 'NAV.md' AGENTS.md
assert "AGENTS.md keeps prior content" grep -q 'keep me' AGENTS.md
assert "CLAUDE.md got pointer" grep -q 'NAV.md' CLAUDE.md
assert "pinned navigate skill" test -f context/skills/navigate/SKILL.md
assert "pinned registry skill" test -f context/skills/registry/SKILL.md
assert "pinned lease-sync skill" test -f context/skills/lease-sync/SKILL.md
assert "pinned digest skill" test -f context/skills/digest/SKILL.md
assert "pinned quality-gates skill" test -f context/skills/quality-gates/SKILL.md
assert "pinned session_start hook" test -f context/hooks/scripts/session_start.py
assert "pinned lease_warn hook" test -f context/hooks/scripts/lease_warn.py
assert "quality.json created" test -f context/quality.json
assert "cursor hooks.json" test -f .cursor/hooks.json
assert "claude settings hooks" grep -q 'SessionStart' .claude/settings.json
assert "codex hooks.json" test -f .codex/hooks.json
assert "check OK after connect" "${CLI[@]}" check

echo "-- connect coverage threshold --"
"${CLI[@]}" connect --coverage 82 >/tmp/agentized-connect-cov.txt
assert "coverage threshold applied" grep -Eq '"lines": 82(\.0)?' context/quality.json
assert "pre-push template pinned" test -f .githooks/pre-push
assert "ci workflow pinned" test -f .github/workflows/ci.yml

echo "-- connect idempotency --"
cp AGENTS.md /tmp/agents-before.md
cp CLAUDE.md /tmp/claude-before.md
"${CLI[@]}" connect >/tmp/agentized-connect2.txt
assert "AGENTS.md unchanged on 2nd connect" cmp -s AGENTS.md /tmp/agents-before.md
assert "CLAUDE.md unchanged on 2nd connect" cmp -s CLAUDE.md /tmp/claude-before.md
count_begin="$(grep -c 'AGENTIZED:BEGIN' AGENTS.md || true)"
assert "single AGENTIZED marker block" test "$count_begin" -eq 1

echo "-- task format + live index --"
"${CLI[@]}" new --title "Mechanical task" --yes >/tmp/new-out.txt
tid="$(grep -E '^id: T-' /tmp/new-out.txt | awk '{print $2}')"
assert "task id allocated" test -n "$tid"
assert "task file exists" test -f "context/tasks/${tid}.md"
assert "status field at start" grep -q '^статус: open' "context/tasks/${tid}.md"
assert "task listed in INDEX open" grep -q "$tid" context/tasks/INDEX.md
"${CLI[@]}" claim "$tid" --owner tester >/tmp/claim-out.txt
assert "status in-progress after claim" grep -q '^статус: in-progress' "context/tasks/${tid}.md"
assert "file not moved on status change" test -f "context/tasks/${tid}.md"
index_progress="$(awk '/^## in-progress/{flag=1;next}/^## /{flag=0}flag' context/tasks/INDEX.md)"
assert "INDEX shows in-progress" grep -q "$tid" <<<"$index_progress"
# no pre-seeded example tasks besides the one we just created
extras="$(find context/tasks -name 'T-*.md' ! -name "${tid}.md" | wc -l | tr -d ' ')"
assert "no extra precommitted tasks in fixture" test "$extras" -eq 0

echo "-- warn-only leases --"
"${CLI[@]}" lease acquire "$tid" runtime --owner A >/tmp/lease-a.txt
# second overlapping lease should warn but still succeed
"${CLI[@]}" new --title "Overlap peer" --yes >/tmp/new2.txt
tid2="$(grep -E '^id: T-' /tmp/new2.txt | awk '{print $2}')"
"${CLI[@]}" claim "$tid2" --owner B >/dev/null
out_lease="$("${CLI[@]}" lease acquire "$tid2" runtime/agentized_cli.py --owner B 2>&1 || true)"
assert "overlap warn text" grep -qi 'LEASE WARN' <<<"$out_lease"
assert "second lease file written (not blocked)" test -f "context/leases/${tid2}.md"
check_out="$("${CLI[@]}" lease check runtime 2>&1 || true)"
assert "lease check warns" grep -qi 'LEASE WARN' <<<"$check_out"
hook_out="$(printf '%s' '{"tool_input":{"file_path":"runtime/agentized_cli.py"}}' | python3 context/hooks/scripts/lease_warn.py)"
assert "hook allows write" grep -q '"permission": "allow"' <<<"$hook_out"
assert "hook carries warn" grep -qi 'LEASE WARN' <<<"$hook_out"

"${CLI[@]}" lease release "$tid" >/dev/null
# A released; B still active — INDEX must not list A's lease path as active for tid
"${CLI[@]}" index >/dev/null
assert "released lease absent from INDEX" bash -c "! grep -q \"$tid\" context/leases/INDEX.md"
assert "index command ok" test -f context/tasks/INDEX.md

echo "-- digest + sync-status --"
"${CLI[@]}" progress "$tid" --text "mechanical progress" >/dev/null
"${CLI[@]}" digest --type development --notes "test" >/dev/null
"${CLI[@]}" digest --type management --notes "test" >/dev/null
dev_digest="$(find context/digests/development -name '*.md' | head -n 1)"
mgmt_digest="$(find context/digests/management -name '*.md' | head -n 1)"
assert "development digest exists" test -n "$dev_digest"
assert "management digest exists" test -n "$mgmt_digest"
"${CLI[@]}" sync-status >/tmp/sync.txt
assert "sync-status runs" grep -q 'sync-status' /tmp/sync.txt

echo
echo "Result: $pass passed, $fail failed"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
exit 0
