#!/usr/bin/env bash
# test-answer-challenger-trivial.sh — regression test for v2.6 anti-lazy fix
# in answer-challenger.sh.
#
# Pre-v2.6 bug: when user typed "approve all" / "ok", challenger_is_trivial
# returned true → 8-lens check skipped → AI's recommend-first draft never
# challenged. Phase 7.14 + 7.15 DISCUSSION-LOG documented this bypass.
#
# Post-v2.6 fix:
#   1. challenger_extract_ai_draft() — extracts AI's draft from accumulated
#      text via 4 patterns (XML tag, **Recommended:**, ## Recommendation,
#      "AI suggests:"). Returns empty when no draft.
#   2. challenge_answer() — when answer is trivial AND draft exists, swap
#      answer text with draft + flag _user_confirmed_draft=true → challenger
#      reviews DRAFT instead of empty confirmation.
#   3. Trivial pattern expanded: "approve|approveall|approve_all|approved|
#      sounds_good|soundsgood|allgood|alright" added (covers AI-friendly
#      lazy-skip patterns).
#
# Run from repo root: bash .claude/scripts/validators/test-answer-challenger-trivial.sh

set -e

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
HELPER="${REPO_ROOT}/.claude/commands/vg/_shared/lib/answer-challenger.sh"

if [ ! -f "$HELPER" ]; then
  echo "⛔ helper not found: $HELPER"
  exit 1
fi

# shellcheck source=/dev/null
source "$HELPER"
export PYTHON_BIN="${PYTHON_BIN:-python3}"

PASS=0
FAIL=0
fail() { echo "  ✗ FAIL: $*"; FAIL=$((FAIL + 1)); }
pass() { echo "  ✓ pass: $*"; PASS=$((PASS + 1)); }

echo "═══ Test 1: trivial detection — confirmations should be trivial ═══"
for input in "ok" "OK" "yes" "Yes" "approve" "approve all" "Approve All" "approveall" "approve_all" "approved" "confirm" "confirmed" "sounds good" "Sounds Good" "all good" "alright" "next" "proceed" "continue"; do
  if challenger_is_trivial "$input"; then
    pass "\"$input\" → trivial"
  else
    fail "\"$input\" should be trivial but isn't"
  fi
done

echo ""
echo "═══ Test 2: trivial detection — denials should be trivial ═══"
for input in "no" "No" "không" "skip" "cancel" "abort" "stop" "huỷ"; do
  if challenger_is_trivial "$input"; then
    pass "\"$input\" → trivial"
  else
    fail "\"$input\" should be trivial but isn't"
  fi
done

echo ""
echo "═══ Test 3: trivial detection — substantive answers should NOT be trivial ═══"
SUBSTANTIVE=(
  "Use bcrypt with work factor 12 because GDPR audit needs reversible failure logs"
  "Tôi nghĩ nên dùng JWT với RS256 thay vì HS256 để tránh shared-secret weakness"
  "Add rate-limiting at 10 req/min per IP for /login endpoint, lockout after 5 fails"
)
for input in "${SUBSTANTIVE[@]}"; do
  if challenger_is_trivial "$input"; then
    fail "\"${input:0:50}...\" should NOT be trivial"
  else
    pass "\"${input:0:50}...\" → challengeable"
  fi
done

echo ""
echo "═══ Test 4: extract draft — **Recommended:** marker ═══"
ACC1='**Recommended:** Use JWT with RS256 algorithm, 15min access token TTL, 7d refresh token rotation, blacklist on logout via Redis SET. SameSite=Strict cookie + HttpOnly + Secure flags.'
DRAFT1=$(challenger_extract_ai_draft "$ACC1")
if [ ${#DRAFT1} -ge 50 ] && echo "$DRAFT1" | grep -q "JWT"; then
  pass "extract from **Recommended:** marker (${#DRAFT1} chars)"
else
  fail "should extract draft from **Recommended:** marker; got '${DRAFT1:0:80}'"
fi

echo ""
echo "═══ Test 5: extract draft — XML <ai-draft> tag ═══"
ACC2='<ai-draft>Backend: Fastify with Zod schemas. DB: MongoDB + native driver. Auth: JWT short-lived + refresh token rotation.</ai-draft>'
DRAFT2=$(challenger_extract_ai_draft "$ACC2")
if [ ${#DRAFT2} -ge 50 ] && echo "$DRAFT2" | grep -q "Fastify"; then
  pass "extract from <ai-draft> tag (${#DRAFT2} chars)"
else
  fail "should extract draft from <ai-draft> tag; got '${DRAFT2:0:80}'"
fi

echo ""
echo "═══ Test 6: extract draft — Vietnamese **Đề xuất:** ═══"
ACC3='**Đề xuất:** Authenticate via session cookie với HttpOnly + Secure + SameSite=Strict. Session TTL 24 giờ, sliding window refresh. Redis SET cho blacklist khi logout.'
DRAFT3=$(challenger_extract_ai_draft "$ACC3")
if [ ${#DRAFT3} -ge 50 ] && echo "$DRAFT3" | grep -qi "session"; then
  pass "extract from **Đề xuất:** marker (${#DRAFT3} chars)"
else
  fail "should extract draft from **Đề xuất:** marker; got '${DRAFT3:0:80}'"
fi

echo ""
echo "═══ Test 7: extract draft — empty when no marker ═══"
ACC4='just some context without any AI draft pattern at all'
DRAFT4=$(challenger_extract_ai_draft "$ACC4")
if [ -z "$DRAFT4" ]; then
  pass "no draft marker → empty result"
else
  fail "should return empty for no draft; got '${DRAFT4:0:80}'"
fi

echo ""
echo "═══ Test 8: extract draft — too-short text rejected (<50 chars) ═══"
ACC5='**Recommended:** Use X.'
DRAFT5=$(challenger_extract_ai_draft "$ACC5")
if [ -z "$DRAFT5" ]; then
  pass "short draft (${#ACC5} chars input) rejected"
else
  fail "should reject too-short draft; got '${DRAFT5:0:80}'"
fi

echo ""
echo "═══ Test 9: option-pick patterns trivial detection (v2.6.1) ═══"
for input in "a" "A" "(a)" "[a]" "1" "(1)" "[2]" "option a" "option 1" "Option A" "chọn a" "chọn 1" "đáp án a" "pick 2" "select a" "(theo Recommended)" "theo Recommended" "theo a" "(Recommended)" "as proposed" "as_is" "default" "(theo Đề xuất)"; do
  if challenger_is_trivial "$input"; then
    pass "\"$input\" → trivial (option pick)"
  else
    fail "\"$input\" should be trivial option pick"
  fi
done

echo ""
echo "═══ Test 10: normalize_pick — extract canonical token ═══"
declare -A NORM_CASES=(
  ["a"]="a"
  ["(a)"]="a"
  ["A"]="a"
  ["[B]"]="b"
  ["1"]="1"
  ["(1)"]="1"
  ["option a"]="a"
  ["option 2"]="2"
  ["chọn b"]="b"
  ["pick 3"]="3"
  ["(theo Recommended)"]="_recommended_"
  ["recommended"]="_recommended_"
  ["as proposed"]="_recommended_"
  ["default"]="_recommended_"
)
for input in "${!NORM_CASES[@]}"; do
  expected="${NORM_CASES[$input]}"
  actual=$(challenger_normalize_pick "$input")
  if [ "$actual" = "$expected" ]; then
    pass "normalize \"$input\" → \"$expected\""
  else
    fail "normalize \"$input\" → expected \"$expected\" got \"$actual\""
  fi
done

echo ""
echo "═══ Test 11: extract_option — parse option (a) body from accumulated ═══"
ACC_OPT='Đề xuất các options:
- (a) JWT short-lived 15min access + 7d refresh rotation, blacklist trên Redis SET
- (b) Session cookie HttpOnly + Secure + SameSite=Strict, TTL 24h
- (c) OAuth 2.0 với PKCE S256 cho public clients (SPA), state + nonce verify

**Recommended:** (a)'
OPT_A=$(challenger_extract_option "$ACC_OPT" "a")
if [ ${#OPT_A} -ge 30 ] && echo "$OPT_A" | grep -q "JWT"; then
  pass "extract option (a) (${#OPT_A} chars)"
else
  fail "should extract (a) JWT body; got '${OPT_A:0:80}'"
fi
OPT_B=$(challenger_extract_option "$ACC_OPT" "b")
if [ ${#OPT_B} -ge 30 ] && echo "$OPT_B" | grep -q "Session"; then
  pass "extract option (b) (${#OPT_B} chars)"
else
  fail "should extract (b) Session body; got '${OPT_B:0:80}'"
fi
OPT_C=$(challenger_extract_option "$ACC_OPT" "c")
if [ ${#OPT_C} -ge 30 ] && echo "$OPT_C" | grep -q "OAuth"; then
  pass "extract option (c) (${#OPT_C} chars)"
else
  fail "should extract (c) OAuth body; got '${OPT_C:0:80}'"
fi
OPT_Z=$(challenger_extract_option "$ACC_OPT" "z")
if [ -z "$OPT_Z" ]; then
  pass "missing option (z) → empty"
else
  fail "should return empty for missing option z; got '${OPT_Z:0:80}'"
fi

echo ""
echo "═══ Test 12: extract_option — numeric list 1./2./3. ═══"
ACC_NUM='Choose authentication strategy:
1. JWT with short-lived access token plus refresh rotation
2. Session cookie with server-side store
3. OAuth 2.0 with PKCE for SPA clients

Pick one.'
OPT_1=$(challenger_extract_option "$ACC_NUM" "1")
if [ ${#OPT_1} -ge 30 ] && echo "$OPT_1" | grep -q "JWT"; then
  pass "extract numeric option 1 (${#OPT_1} chars)"
else
  fail "should extract option 1 (JWT); got '${OPT_1:0:80}'"
fi

echo ""
echo "════════════════════════════════════════════"
echo "PASS: $PASS"
echo "FAIL: $FAIL"
echo "════════════════════════════════════════════"

[ "$FAIL" -eq 0 ]
