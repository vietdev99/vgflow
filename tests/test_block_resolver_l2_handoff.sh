#!/usr/bin/env bash
# Tests for block_resolve_l2_handoff (Codex-R7 fix).
# Validates: handoff brief extracts recommendations from BOTH legacy
# `proposal.suggested_actions` shape AND diagnostic-L2
# `proposal.decision_questions[0].recommendation` shape.

set -euo pipefail

REPO_ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LIB="${REPO_ROOT_DIR}/commands/vg/_shared/lib/block-resolver.sh"

# shellcheck disable=SC1090
REPO_ROOT="$REPO_ROOT_DIR" source "$LIB"
export REPO_ROOT="$REPO_ROOT_DIR"

PASSED=0
FAILED=0
fail() { echo "  ✗ $1" >&2; FAILED=$((FAILED + 1)); }
pass() { echo "  ✓ $1"; PASSED=$((PASSED + 1)); }

# ─── Test 1: legacy shape — suggested_actions list ──────────────────
TMP=$(mktemp -d)
PHASE_DIR="$TMP"
LEGACY_RESULT=$(cat <<'JSON'
{"level":"L2","action":"proposal","proposal":{
  "type":"refactor","summary":"split into sub-phases",
  "confidence":0.85,
  "rationale":"too many tasks in one phase",
  "suggested_actions":["create sub-phase 7.1.1","move task A","move task B"]
}}
JSON
)

block_resolve_l2_handoff "test-gate" "$LEGACY_RESULT" "$PHASE_DIR" >/dev/null 2>&1 || true

BRIEF="$PHASE_DIR/.block-resolver-l2-brief.md"
if [ -f "$BRIEF" ]; then
  pass "brief written"
else
  fail "brief not written"
fi

if grep -q 'create sub-phase 7.1.1' "$BRIEF"; then
  pass "legacy suggested_actions appear in brief"
else
  fail "legacy suggested_actions missing from brief: $(cat "$BRIEF")"
fi

if grep -q 'too many tasks' "$BRIEF"; then
  pass "rationale present"
else
  fail "rationale missing"
fi

# ─── Test 2: diagnostic-L2 shape — decision_questions[0].recommendation ─
TMP2=$(mktemp -d)
PHASE_DIR="$TMP2"
DL2_RESULT=$(cat <<'JSON'
{"level":"L2","action":"proposal","proposal":{
  "type":"diagnostic-l2",
  "summary":"G-10 step 2 missing evidence.source",
  "confidence":0.9,
  "decision_questions":[{
    "q":"Apply proposed fix?",
    "recommendation":"Re-run scanner: /vg:review --re-scan-goals=G-10",
    "rationale":"L2 audit trail: l2-12345-abc; confidence 0.90"
  }],
  "proposal_id":"l2-12345-abc"
}}
JSON
)

block_resolve_l2_handoff "missing-evidence" "$DL2_RESULT" "$PHASE_DIR" >/dev/null 2>&1 || true
BRIEF2="$PHASE_DIR/.block-resolver-l2-brief.md"

if grep -q 'Re-run scanner' "$BRIEF2"; then
  pass "diagnostic-L2 recommendation appears in brief"
else
  fail "diagnostic-L2 recommendation missing — Codex-R7 regression. Brief: $(cat "$BRIEF2")"
fi

if grep -q 'L2 audit trail' "$BRIEF2"; then
  pass "diagnostic-L2 rationale appears in brief"
else
  fail "diagnostic-L2 rationale missing"
fi

# Should NOT show the "did not provide explicit actions" placeholder
if grep -q 'did not provide explicit actions' "$BRIEF2"; then
  fail "brief says 'did not provide actions' — extraction broken"
else
  pass "brief does not show the no-actions placeholder"
fi

# ─── Cleanup ────────────────────────────────────────────────────────
rm -rf "$TMP" "$TMP2"

echo ""
echo "PASSED: $PASSED"
echo "FAILED: $FAILED"
[ "$FAILED" -eq 0 ]
