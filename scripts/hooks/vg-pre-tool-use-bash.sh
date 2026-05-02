#!/usr/bin/env bash
# PreToolUse on Bash — gate before vg-orchestrator step-active.
# Verifies signed tasklist evidence file exists + HMAC valid + checksum matches contract.
# Uses hmac.compare_digest (constant-time) to prevent timing side-channel attacks.

set -euo pipefail

input="$(cat)"
cmd_text="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null || true)"

# Only gate when bash invokes vg-orchestrator step-active.
if [[ ! "$cmd_text" =~ vg-orchestrator[[:space:]]+step-active ]]; then
  exit 0
fi

session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"
if [ ! -f "$run_file" ]; then
  exit 0  # no active run; nothing to gate.
fi

run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$run_file")"
evidence_path=".vg/runs/${run_id}/.tasklist-projected.evidence.json"
contract_path=".vg/runs/${run_id}/tasklist-contract.json"
key_path="${VG_EVIDENCE_KEY_PATH:-.vg/.evidence-key}"

emit_block() {
  local cause="$1"
  local gate_id="PreToolUse-tasklist"
  local block_dir=".vg/blocks/${run_id}"
  local block_file="${block_dir}/${gate_id}.md"

  # Full diagnostic written to file (AI reads on demand, not pasted to chat).
  mkdir -p "$block_dir" 2>/dev/null
  cat > "$block_file" <<EOF
# Block diagnostic — ${gate_id}

## Cause
${cause}

## Required fix
1. Read \`.vg/runs/${run_id}/tasklist-contract.json\`
2. Call TodoWrite with each \`projection_items[]\` entry as one todo
   (32 items for vg:blueprint web-fullstack: 6 group headers + 26 sub-steps)
3. PostToolUse hook auto-writes signed evidence file
4. Retry the blocked \`vg-orchestrator step-active\` call

## Narration template (use session language)
[VG diagnostic] Bước <step> đang bị chặn. Lý do: chưa gọi TodoWrite.
Đang xử lý: project tasklist-contract. Sẽ tiếp tục sau khi xong.

## After fix
\`\`\`
vg-orchestrator emit-event vg.block.handled \\
  --gate ${gate_id} \\
  --resolution "TodoWrite called, evidence regenerated"
\`\`\`

If this gate blocked ≥3 times this run, MUST call AskUserQuestion instead of retrying.
EOF

  # Compact stderr — 3 lines max.
  printf "⛔ %s: %s\n→ Read %s for fix\n→ After fix: vg-orchestrator emit-event vg.block.handled --gate %s\n" \
    "$gate_id" "$cause" "$block_file" "$gate_id" >&2

  if command -v vg-orchestrator >/dev/null 2>&1; then
    vg-orchestrator emit-event vg.block.fired \
      --gate "$gate_id" --cause "$cause" >/dev/null 2>&1 || true
  fi
  exit 2
}

if [ ! -f "$evidence_path" ]; then
  emit_block "evidence file missing at ${evidence_path}; TodoWrite has not been called for run ${run_id}"
fi

if [ ! -f "$key_path" ]; then
  emit_block "evidence key missing at ${key_path}; cannot verify HMAC"
fi

verify_result="$(python3 - "$evidence_path" "$key_path" "$contract_path" <<'PY'
"""HMAC + checksum verifier for tasklist evidence.

SECURITY: uses hmac.compare_digest (constant-time) to prevent timing attacks.
"""
import hashlib, hmac, json, sys
ev_path, key_path, contract_path = sys.argv[1:]
ev = json.loads(open(ev_path).read())
key = open(key_path, 'rb').read().strip()
canonical = json.dumps(ev["payload"], sort_keys=True).encode()
expected = hmac.new(key, canonical, hashlib.sha256).hexdigest()
actual = ev.get("hmac_sha256", "")
# Constant-time comparison to prevent timing side-channel leak of signature.
if not hmac.compare_digest(expected, actual):
    print("hmac_invalid", end="")
    sys.exit(0)
contract_sha = ev["payload"].get("contract_sha256", "")
if contract_path:
    actual_contract = hashlib.sha256(open(contract_path, 'rb').read()).hexdigest()
    if not hmac.compare_digest(contract_sha, actual_contract):
        print("contract_mismatch", end="")
        sys.exit(0)
print("ok", end="")
PY
)"

case "$verify_result" in
  ok) exit 0 ;;
  hmac_invalid) emit_block "evidence file HMAC invalid (signature does not match key)" ;;
  contract_mismatch) emit_block "evidence contract checksum does not match current tasklist-contract.json" ;;
  *) emit_block "evidence verification failed: ${verify_result}" ;;
esac
