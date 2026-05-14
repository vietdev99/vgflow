#!/usr/bin/env bash
# vg-deploy-contract-guard.sh — Batch 20 PreToolUse Bash hook
#
# Detects deploy-like commands and validates them against
# .vg/DEPLOY-CONTRACT.json fingerprint_pattern. BLOCKs on drift.
#
# Hook protocol: reads JSON from stdin, exit 0 to allow, exit non-zero
# OR emit {"decision":"block"} JSON to stdout to block.

set -uo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
CONTRACT="${PROJECT_DIR}/.vg/DEPLOY-CONTRACT.json"

# Read tool payload into temp file (avoid heredoc expansion issues)
TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT
cat > "$TMPFILE"

# Detect python binary
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  PY="${PYTHON_BIN:-python3}"
fi

# Extract command via Python (jq may not exist on Windows)
EXTRACT_SCRIPT='
import json, sys
try:
    d = json.loads(open(sys.argv[1]).read())
    if d.get("tool_name") != "Bash":
        print("__SKIP__")
    else:
        print(d.get("tool_input", {}).get("command", ""))
except Exception:
    print("__SKIP__")
'
CMD=$($PY -c "$EXTRACT_SCRIPT" "$TMPFILE" 2>/dev/null || echo "__SKIP__")

# Skip if not a Bash tool call
[ "$CMD" = "__SKIP__" ] && exit 0
[ -z "$CMD" ] && exit 0

# Deploy-like pattern detection (broad — covers common deploy tools)
DEPLOY_PATTERNS='(ansible(-playbook)?|pm2 (start|restart|reload|stop)|docker compose|kubectl (apply|rollout|delete)|helm (install|upgrade|rollback)|terraform (apply|destroy)|sudo systemctl (restart|reload|start|stop)|systemctl (restart|reload|start|stop)|cap deploy|bundle exec cap|fab deploy)'

if ! echo "$CMD" | grep -qE "$DEPLOY_PATTERNS"; then
  # Not a deploy command — pass through
  exit 0
fi

# Deploy command detected — check contract
if [ ! -f "$CONTRACT" ]; then
  printf '{"decision":"block","reason":"Deploy command detected but .vg/DEPLOY-CONTRACT.json missing. Bootstrap: python scripts/deploy-contract-init.py --method ansible --build ... --restart ... --health ... OR /vg:deploy --init"}\n'
  exit 0
fi

# Read fingerprint_pattern via Python
FINGERPRINT=$($PY -c "
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
    print(d.get('fingerprint_pattern', ''))
except Exception:
    print('')
" "$CONTRACT" 2>/dev/null || echo "")

if [ -z "$FINGERPRINT" ]; then
  exit 0  # malformed contract — let other validators catch
fi

# Match command against fingerprint
if echo "$CMD" | grep -qE "$FINGERPRINT"; then
  exit 0
fi

# Drift detected — read method for error message
METHOD=$($PY -c "
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
    print(d.get('method', 'unknown'))
except Exception:
    print('unknown')
" "$CONTRACT" 2>/dev/null || echo "unknown")

TRUNCATED_CMD="${CMD:0:120}"

printf '{"decision":"block","reason":"Deploy command drift detected. Project locked to method=%s. Command does not match fingerprint. Use locked method per .vg/DEPLOY-CONTRACT.json OR: /vg:override-resolve --deploy-method=<new_method> --reason=<why>"}\n' \
  "$METHOD"
exit 0
