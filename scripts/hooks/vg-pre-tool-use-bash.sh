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
  cat >&2 <<MSG
═══════════════════════════════════════════
DIAGNOSTIC REQUIRED — Gate: PreToolUse-tasklist
═══════════════════════════════════════════

CAUSE:
  ${cause}

REQUIRED FIX:
  1. Read .vg/runs/${run_id}/tasklist-contract.json
  2. Call TodoWrite with each checklist group as one todo item
  3. Verify PostToolUse hook wrote signed evidence file
  4. Retry the blocked vg-orchestrator step-active call

YOU MUST DO ALL THREE BEFORE CONTINUING:
  A) Tell user (in session language) using template:
     "[VG diagnostic] Bước <step> đang bị chặn. Lý do: chưa gọi TodoWrite.
      Đang xử lý: project tasklist-contract. Sẽ tiếp tục sau khi xong."
  B) Bash: vg-orchestrator emit-event vg.block.handled \\
            --gate PreToolUse-tasklist \\
            --resolution "TodoWrite called, evidence regenerated"
  C) Retry the original tool call.

If this gate has blocked ≥3 times this run, you MUST call AskUserQuestion
instead of retrying.
═══════════════════════════════════════════
MSG
  if command -v vg-orchestrator >/dev/null 2>&1; then
    vg-orchestrator emit-event vg.block.fired \
      --gate PreToolUse-tasklist --cause "$cause" >/dev/null 2>&1 || true
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
