#!/usr/bin/env bash
# Tests for block-resolver L2 architect → spawn-diagnostic-l2 wiring (stub-3 fix).
# Validates: spawn invoked when script available, fallback to placeholder when
# disabled, JSON shape preserved, dry-run mode plumbing.

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

# ─── Test 1: dry-run path emits diagnostic-l2 proposal type ─────────
TMP=$(mktemp -d)
PHASE_DIR="$TMP/phase"
mkdir -p "$PHASE_DIR"

VG_DIAGNOSTIC_L2_DRY_RUN=1 OUT=$(_block_resolve_l2_architect \
  "missing-evidence" \
  "G-10 step 2 missing evidence.source" \
  '{"goal":"G-10","step_idx":2}' \
  "$PHASE_DIR" 2>/dev/null)

TYPE=$(echo "$OUT" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('type',''))" 2>/dev/null)
if [ "$TYPE" = "diagnostic-l2" ]; then
  pass "dry-run path emits type=diagnostic-l2"
else
  fail "expected type=diagnostic-l2, got '$TYPE' (output: $OUT)"
fi

# Should include proposal_id
PID=$(echo "$OUT" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('proposal_id',''))" 2>/dev/null)
if [[ "$PID" =~ ^l2- ]]; then
  pass "proposal_id in response"
else
  fail "proposal_id missing or malformed: $PID"
fi

# Proposal should be persisted on disk
if [ -f "$PHASE_DIR/.l2-proposals/$PID.json" ]; then
  pass "proposal persisted to .l2-proposals/$PID.json"
else
  fail "proposal file missing"
fi

# ─── Test 2: VG_DIAGNOSTIC_L2_DISABLE=1 falls back to placeholder ───
VG_DIAGNOSTIC_L2_DISABLE=1 OUT2=$(_block_resolve_l2_architect \
  "g" "ctx" '{}' "$PHASE_DIR" 2>/dev/null)

TYPE2=$(echo "$OUT2" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('type',''))" 2>/dev/null)
if [ "$TYPE2" = "config-change" ]; then
  pass "VG_DIAGNOSTIC_L2_DISABLE=1 returns placeholder"
else
  fail "DISABLE=1 should fall back, got type='$TYPE2'"
fi

# ─── Test 3: missing phase_dir falls back to placeholder ────────────
OUT3=$(_block_resolve_l2_architect "g" "ctx" '{}' "" 2>/dev/null)
TYPE3=$(echo "$OUT3" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('type',''))" 2>/dev/null)
if [ "$TYPE3" = "config-change" ]; then
  pass "missing phase_dir returns placeholder"
else
  fail "no phase_dir should fall back, got '$TYPE3'"
fi

# ─── Cleanup ────────────────────────────────────────────────────────
rm -rf "$TMP"

echo ""
echo "PASSED: $PASSED"
echo "FAILED: $FAILED"
[ "$FAILED" -eq 0 ]
