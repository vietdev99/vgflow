#!/usr/bin/env bash
# Tests for block_resolve_l3_single_advisory (RFC v9 D26).
# Validates: confidence-gated single-advisory rendering, fallback to
# 3-option flow on low confidence, JSON shape.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB="${REPO_ROOT}/commands/vg/_shared/lib/block-resolver.sh"

# shellcheck disable=SC1090
source "$LIB"

PASSED=0
FAILED=0
fail() { echo "  ✗ $1" >&2; FAILED=$((FAILED + 1)); }
pass() { echo "  ✓ $1"; PASSED=$((PASSED + 1)); }

# ─── Test 1: high-confidence emits single-advisory ──────────────────
TMP=$(mktemp -d)
PHASE_DIR="$TMP"
cat > "$PHASE_DIR/.block-resolver-l2-brief.md" <<EOF
- **Type:** missing-evidence
- **Summary:** Re-run scanner for G-10
- **Rationale:** Restores trustworthy provenance per D10
EOF

OUT=$(block_resolve_l3_single_advisory "test-gate" "$PHASE_DIR" "0.9" 2>/dev/null)
if echo "$OUT" | grep -q "BLOCK_RESOLVER_L3_PROMPT_SINGLE_ADVISORY"; then
  pass "high-confidence emits single-advisory marker"
else
  fail "high-confidence did not emit single-advisory marker. Got: $OUT"
fi

if echo "$OUT" | grep -q '"confidence": 0.9'; then
  pass "confidence preserved in JSON"
else
  fail "confidence not preserved in JSON output"
fi

# Should have exactly 2 options (Yes / No-show-details), NOT 3
OPT_COUNT=$(echo "$OUT" | grep -c '"label":')
if [ "$OPT_COUNT" -eq 2 ]; then
  pass "single-advisory has exactly 2 options (Yes + details)"
else
  fail "single-advisory has $OPT_COUNT options, expected 2"
fi

# ─── Test 2: low-confidence falls back to 3-option ──────────────────
OUT_LOW=$(block_resolve_l3_single_advisory "test-gate" "$PHASE_DIR" "0.3" 2>/dev/null)
if echo "$OUT_LOW" | grep -q "BLOCK_RESOLVER_L3_PROMPT_SINGLE_ADVISORY"; then
  fail "low-confidence wrongly emitted single-advisory marker"
else
  pass "low-confidence does NOT emit single-advisory (falls through)"
fi

# Fallback should produce 3-option output (Apply / Override / Abort)
if echo "$OUT_LOW" | grep -q "BLOCK_RESOLVER_L3_PROMPT"; then
  pass "low-confidence falls back to 3-option L3 output"
else
  fail "low-confidence did not fall back to 3-option output"
fi

# ─── Test 3: missing brief → graceful error ─────────────────────────
EMPTY=$(mktemp -d)
if block_resolve_l3_single_advisory "test-gate" "$EMPTY" "0.9" 2>/dev/null; then
  fail "missing brief should return non-zero"
else
  pass "missing brief returns non-zero exit"
fi

# ─── Test 4: threshold env override ─────────────────────────────────
CONFIG_REVIEW_L3_SINGLE_ADVISORY_MIN_CONFIDENCE="0.99"
OUT_HIGH_THR=$(block_resolve_l3_single_advisory "test-gate" "$PHASE_DIR" "0.85" 2>/dev/null)
unset CONFIG_REVIEW_L3_SINGLE_ADVISORY_MIN_CONFIDENCE
if echo "$OUT_HIGH_THR" | grep -q "BLOCK_RESOLVER_L3_PROMPT_SINGLE_ADVISORY"; then
  fail "threshold override 0.99 should reject confidence=0.85 → fallback expected"
else
  pass "threshold override gates single-advisory correctly"
fi

# ─── Cleanup ────────────────────────────────────────────────────────
rm -rf "$TMP" "$EMPTY"

echo ""
echo "PASSED: $PASSED"
echo "FAILED: $FAILED"
[ "$FAILED" -eq 0 ]
