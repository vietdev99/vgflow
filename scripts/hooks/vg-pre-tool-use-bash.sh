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
  {
    echo "# Block diagnostic — ${gate_id}"
    echo ""
    echo "## Cause"
    echo "${cause}"
    echo ""
    echo "## Required fix"
    echo ""
    echo "Before any \`vg-orchestrator step-active\` call, you MUST:"
    echo ""
    echo "1. Read \`${contract_path}\` (parse \`checklists[]\`)."
    echo "2. Call the \`TodoWrite\` tool with one entry per \`items[]\` row."
    echo "3. Run:"
    echo "   \`\`\`bash"
    echo "   python3 .claude/scripts/vg-orchestrator tasklist-projected --adapter claude"
    echo "   \`\`\`"
    echo "   This writes \`.tasklist-projected.evidence.json\` so subsequent"
    echo "   step-active calls pass this hook."
    echo ""
    echo "Do NOT just emit \`vg.block.handled\` — the evidence file must exist."
    echo "See \`commands/vg/_shared/lib/tasklist-projection-instruction.md\` for full instructions."
    echo ""
    echo "## Narration template (use session language)"
    echo "[VG diagnostic] Bước <step> đang bị chặn. Lý do: chưa gọi TodoWrite."
    echo "Đang xử lý: project tasklist-contract. Sẽ tiếp tục sau khi xong."
    echo ""
    echo "## After fix"
    echo "\`\`\`"
    echo "vg-orchestrator emit-event vg.block.handled \\"
    echo "  --gate ${gate_id} \\"
    echo "  --resolution \"TodoWrite called, evidence regenerated\""
    echo "\`\`\`"
    echo ""
    echo "If this gate blocked ≥3 times this run, MUST call AskUserQuestion instead of retrying."
  } > "$block_file"

  # Compact stderr — 3 lines max.
  # Title color: error → orange (\033[38;5;208m); warn → yellow (\033[33m). Reset: \033[0m. Color applies ONLY to the first line (title); follow-up lines plain.
  printf "\033[38;5;208m%s: %s\033[0m\n→ Read %s for fix\n→ After fix: vg-orchestrator emit-event vg.block.handled --gate %s\n" \
    "$gate_id" "$cause" "$block_file" "$gate_id" >&2

  if command -v vg-orchestrator >/dev/null 2>&1; then
    vg-orchestrator emit-event vg.block.fired \
      --gate "$gate_id" --cause "$cause" >/dev/null 2>&1 || true
  fi

  # Per-command telemetry — gate-stats can graph bypass attempts.
  command_from_run="$(python3 -c '
import json,sys
try: print(json.load(open(sys.argv[1]))["command"])
except: print("")
' "$run_file" 2>/dev/null || echo "")"

  if [ -n "$command_from_run" ]; then
    event_type="${command_from_run/vg:/}.tasklist_projection_skipped"
    # Attempt via orchestrator (production path — has active run + FK).
    # On failure (no active run or FK violation in test env), fall back to
    # a direct sqlite write so the event is always recorded.
    if ! CLAUDE_SESSION_ID="${session_id}" python3 .claude/scripts/vg-orchestrator emit-event "$event_type" \
        --actor hook \
        --outcome WARN \
        --payload "{\"run_id\":\"${run_id}\",\"contract_path\":\"${contract_path}\"}" \
        >/dev/null 2>&1; then
      VG_EVENT_TYPE="$event_type" VG_RUN_ID="$run_id" VG_CONTRACT_PATH="$contract_path" \
      python3 -c '
import sqlite3, json, datetime, os
from pathlib import Path
repo = Path(os.environ.get("VG_REPO_ROOT", ".")).resolve()
db_path = repo / ".vg" / "events.db"
if db_path.exists():
    event_type = os.environ["VG_EVENT_TYPE"]
    run_id = os.environ["VG_RUN_ID"]
    contract_path = os.environ["VG_CONTRACT_PATH"]
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, run_id TEXT, command TEXT, event_type TEXT,
        ts TEXT, payload_json TEXT, actor TEXT, outcome TEXT)""")
    conn.execute(
        "INSERT INTO events(run_id, event_type, ts, payload_json, actor, outcome) VALUES (?,?,?,?,?,?)",
        (run_id, event_type,
         datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
         json.dumps({"run_id": run_id, "contract_path": contract_path}),
         "hook", "WARN"))
    conn.commit()
    conn.close()
' 2>/dev/null || true
    fi
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
