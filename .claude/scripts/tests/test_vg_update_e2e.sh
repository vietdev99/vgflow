#!/bin/bash
# Integration test: merge scenarios for vg_update.py
# Explicit error handling — don't use set -e because cmd_merge returns exit 1
# on conflict (intentional, for shell scripts that key off exit code), and
# command substitution would trigger set -e exit.

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VG_UPDATE="${REPO_ROOT}/scripts/vg_update.py"
[ -f "$VG_UPDATE" ] || VG_UPDATE="${REPO_ROOT}/.claude/scripts/vg_update.py"

[ -f "$VG_UPDATE" ] || { echo "FAIL: vg_update.py missing at $VG_UPDATE"; exit 2; }

TMP="$(mktemp -d)"
trap "rm -rf $TMP" EXIT

cd "$TMP" || exit 2
mkdir -p ancestor current upstream output

FAILED=0

run_merge() {
  python3 "$VG_UPDATE" merge \
    --ancestor "$1" --current "$2" --upstream "$3" --output "$4" 2>&1
  # Return the actual exit code for caller (but via stdout we captured status)
}

# ─── Scenario 1: Clean merge (upstream change, user untouched) ───
cat > ancestor/build.md <<'EOF'
# Build command v1.0
line A
line B
EOF
cp ancestor/build.md current/build.md
cat > upstream/build.md <<'EOF'
# Build command v1.0 UPDATED
line A
line B
EOF

STATUS=$(run_merge ancestor/build.md current/build.md upstream/build.md output/clean.md)

if [ "$STATUS" = "clean" ] && grep -q "UPDATED" output/clean.md; then
  echo "[1/4] clean merge: PASS"
else
  echo "[1/4] clean merge: FAIL (status=$STATUS)"
  cat output/clean.md
  FAILED=$((FAILED + 1))
fi

# ─── Scenario 2: Conflict (both user + upstream changed same line) ───
cat > ancestor/build.md <<'EOF'
config: A
EOF
cat > current/build.md <<'EOF'
config: USER_EDIT
EOF
cat > upstream/build.md <<'EOF'
config: UPSTREAM_EDIT
EOF

STATUS=$(run_merge ancestor/build.md current/build.md upstream/build.md output/conflict.md)

if [ "$STATUS" = "conflict" ] \
   && grep -q "<<<<<<<" output/conflict.md \
   && grep -q ">>>>>>>" output/conflict.md \
   && grep -q "USER_EDIT" output/conflict.md \
   && grep -q "UPSTREAM_EDIT" output/conflict.md; then
  echo "[2/4] conflict merge: PASS"
else
  echo "[2/4] conflict merge: FAIL (status=$STATUS)"
  cat output/conflict.md
  FAILED=$((FAILED + 1))
fi

# ─── Scenario 3: No upstream change (preserve user) ───
cat > ancestor/build.md <<'EOF'
v1
EOF
cat > current/build.md <<'EOF'
v1 USER
EOF
cat > upstream/build.md <<'EOF'
v1
EOF

STATUS=$(run_merge ancestor/build.md current/build.md upstream/build.md output/preserve.md)

if [ "$STATUS" = "clean" ] && grep -q "USER" output/preserve.md; then
  echo "[3/4] preserve user: PASS"
else
  echo "[3/4] preserve user: FAIL (status=$STATUS)"
  cat output/preserve.md
  FAILED=$((FAILED + 1))
fi

# ─── Scenario 4: Missing ancestor (self-rescue path) ───
cat > current/self.md <<'EOF'
old updater
EOF
cat > upstream/self.md <<'EOF'
new updater
EOF
rm -f ancestor/missing-self.md

STATUS=$(run_merge ancestor/missing-self.md current/self.md upstream/self.md output/self.md)

if [ "$STATUS" = "force-upstream" ] && grep -q "new updater" output/self.md; then
  echo "[4/4] missing ancestor force-upstream: PASS"
else
  echo "[4/4] missing ancestor force-upstream: FAIL (status=$STATUS)"
  cat output/self.md
  FAILED=$((FAILED + 1))
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "All 4 integration scenarios passed."
  exit 0
else
  echo "FAIL: ${FAILED} scenario(s) failed."
  exit 1
fi
