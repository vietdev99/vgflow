#!/usr/bin/env bash
# PreToolUse on Bash — gate before vg-orchestrator step-active.
# Verifies signed tasklist evidence file exists + HMAC valid + checksum matches contract.
# Uses hmac.compare_digest (constant-time) to prevent timing side-channel attacks.

set -euo pipefail

input="$(cat)"
cmd_text="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null || true)"

session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"
if [ ! -f "$run_file" ] && [ "${VG_RUNTIME:-}" = "codex" ]; then
  ctx_session="$(
    python3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
p = Path(".vg/.session-context.json")
if not p.exists():
    raise SystemExit(0)
try:
    sid = json.loads(p.read_text(encoding="utf-8")).get("session_id") or ""
except Exception:
    sid = ""
safe = "".join(c for c in sid if c.isalnum() or c in "-_")
print(safe)
PY
  )"
  if [ -n "$ctx_session" ] && [ -f ".vg/active-runs/${ctx_session}.json" ]; then
    run_file=".vg/active-runs/${ctx_session}.json"
  elif [ -f ".vg/current-run.json" ]; then
    run_file=".vg/current-run.json"
  fi
fi
if [ -f "$run_file" ]; then
  run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("run_id",""))' "$run_file" 2>/dev/null || true)"
  command_from_run="$(python3 -c '
import json,sys
try: print(json.load(open(sys.argv[1])).get("command",""))
except Exception: print("")
' "$run_file" 2>/dev/null || echo "")"
  run_session_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("session_id",""))' "$run_file" 2>/dev/null || true)"
else
  run_id=""
  command_from_run=""
  run_session_id=""
fi

codex_before_first_step() {
  [ "${VG_RUNTIME:-}" = "codex" ] || return 1
  [ -n "${run_id:-}" ] || return 1
  case "$command_from_run" in
    vg:*) ;;
    *) return 1 ;;
  esac
  if [ -f ".vg/events.db" ] && VG_RUN_ID="${run_id:-}" python3 - <<'PY' 2>/dev/null; then
import os
import sqlite3
import sys
from pathlib import Path

run_id = os.environ.get("VG_RUN_ID") or ""
if not run_id:
    raise SystemExit(1)
db_path = Path(".vg/events.db")
if not db_path.exists():
    raise SystemExit(1)
conn = sqlite3.connect(str(db_path))
try:
    row = conn.execute(
        "SELECT 1 FROM events WHERE run_id = ? AND event_type = 'step.active' LIMIT 1",
        (run_id,),
    ).fetchone()
finally:
    conn.close()
raise SystemExit(0 if row else 1)
PY
    return 1
  fi
  python3 - <<'PY' 2>/dev/null
import json
from pathlib import Path
p = Path(".vg/.session-context.json")
if not p.exists():
    raise SystemExit(1)
try:
    ctx = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if ctx.get("current_step") or ctx.get("step_history"):
    raise SystemExit(1)
raise SystemExit(0)
PY
}

codex_before_tasklist_projection() {
  [ "${VG_RUNTIME:-}" = "codex" ] || return 1
  [ -n "${run_id:-}" ] || return 1
  case "$command_from_run" in
    vg:*) ;;
    *) return 1 ;;
  esac
  [ ! -s ".vg/runs/${run_id}/.tasklist-projected.evidence.json" ] || return 1
  return 0
}

is_broad_codex_prestep_scan() {
  [[ "$cmd_text" == *"rg --files"* ]] && return 0
  [[ "$cmd_text" =~ (^|[[:space:];|&])find[[:space:]]+\./?([[:space:]]|$) ]] && return 0
  [[ "$cmd_text" =~ (^|[[:space:];|&])find[[:space:]]+(\.vg|\.claude|\.codex|commands|scripts)([[:space:]]|$) ]] && return 0
  if [[ "$cmd_text" =~ (^|[[:space:];|&])rg[[:space:]]+.*(\.vg|\.claude/scripts|\.claude/commands|\.claude/agents|\.codex/skills|commands/vg|scripts)([[:space:]]|$) ]]; then
    [[ "$cmd_text" =~ (SKILL\.md|_shared/blueprint/(preflight|design|plan-overview|plan-delegation|contracts-overview|contracts-delegation|verify|close|edge-cases|lens-walk)\.md) ]] && return 1
    return 0
  fi
  return 1
}

emit_codex_prestep_scope_block() {
  local gate_id="PreToolUse-codex-prestep-scope"
  local cause="Codex active VG run has not emitted first step-active; broad workflow scan would consume context and delay required gates"
  local block_dir=".vg/blocks/${run_id:-unknown}"
  local block_file="${block_dir}/${gate_id}.md"
  mkdir -p "$block_dir" 2>/dev/null
  {
    echo "# Block diagnostic — ${gate_id}"
    echo ""
    echo "## Cause"
    echo "$cause"
    echo ""
    echo "## Blocked command"
    echo '```bash'
    echo "$cmd_text"
    echo '```'
    echo ""
    echo "## Required fix"
    echo ""
    echo "Codex is in a VG command before the first step marker. Do not run broad"
    echo "repo/workflow scans here. Read only the exact generated skill and the"
    echo "current command's shared step file, then execute the first bootstrap"
    echo "step with:"
    echo ""
    echo '```bash'
    echo "vg-orchestrator step-active <first_bootstrap_step>"
    echo '```'
    echo ""
    echo "Allowed examples before first step:"
    echo "- sed -n '1,320p' .codex/skills/vg-blueprint/SKILL.md"
    echo "- sed -n '1,360p' .claude/commands/vg/_shared/blueprint/preflight.md"
    echo ""
    echo "Blocked examples before first step:"
    echo "- rg --files"
    echo "- find .claude ..."
    echo "- rg ... .claude/scripts .claude/commands/vg"
    echo ""
    echo "## After fix"
    echo '```bash'
    echo "vg-orchestrator emit-event vg.block.handled \\"
    echo "  --gate ${gate_id} \\"
    echo "  --resolution \"stopped broad pre-step scan; executing bootstrap step\""
    echo '```'
  } > "$block_file"

  printf "\033[38;5;208m%s: %s\033[0m\n→ Read %s for fix\n→ Next: run first bootstrap step-active, not broad rg/find\n" \
    "$gate_id" "$cause" "$block_file" >&2

  if [ -n "${run_id:-}" ] && [ -f ".claude/scripts/vg-orchestrator" ]; then
    VG_RUN_ID="${run_id:-}" CLAUDE_SESSION_ID="${run_session_id:-$session_id}" python3 .claude/scripts/vg-orchestrator emit-event \
      "vg.block.fired" \
      --actor hook \
      --outcome FAIL \
      --payload "$(VG_RUN_ID="${run_id:-}" python3 -c 'import json,os; print(json.dumps({"gate":"PreToolUse-codex-prestep-scope","cause":"broad pre-step workflow scan","run_id":os.environ.get("VG_RUN_ID","")}))')" \
      >/dev/null 2>&1 || true
  fi
  exit 2
}

emit_codex_pretasklist_scope_block() {
  local gate_id="PreToolUse-codex-pretasklist-scope"
  local cause="Codex active VG run has not projected the native tasklist; broad workflow scan would consume context before required gates"
  local block_dir=".vg/blocks/${run_id:-unknown}"
  local block_file="${block_dir}/${gate_id}.md"
  mkdir -p "$block_dir" 2>/dev/null
  {
    echo "# Block diagnostic — ${gate_id}"
    echo ""
    echo "## Cause"
    echo "$cause"
    echo ""
    echo "## Blocked command"
    echo '```bash'
    echo "$cmd_text"
    echo '```'
    echo ""
    echo "## Required fix"
    echo ""
    echo "Codex is in a VG command before native tasklist projection. Do not run"
    echo "broad repo/workflow scans here. Continue the command preflight in order:"
    echo ""
    echo "1. Execute the next bootstrap/preflight step from the current command ref."
    echo "2. Run emit-tasklist.py when the command reaches its tasklist step."
    echo "3. Project the tasklist and write evidence:"
    echo ""
    echo '```bash'
    echo "python3 .claude/scripts/vg-orchestrator tasklist-projected --adapter codex"
    echo '```'
    echo ""
    echo "Allowed before tasklist projection:"
    echo "- exact sed/cat reads of the current command ref"
    echo "- exact sed/cat reads of .claude/vg.config.md, .vg/current-run.json, and current phase artifacts"
    echo "- vg-orchestrator step-active/mark-step/emit-event for the documented preflight steps"
    echo ""
    echo "Blocked before tasklist projection:"
    echo "- rg --files .claude/scripts ..."
    echo "- find .vg ..."
    echo "- rg ... .claude/scripts .claude/commands/vg .vg"
    echo ""
    echo "## After fix"
    echo '```bash'
    echo "vg-orchestrator emit-event vg.block.handled \\"
    echo "  --gate ${gate_id} \\"
    echo "  --resolution \"stopped broad pre-tasklist scan; continuing preflight/tasklist\""
    echo '```'
  } > "$block_file"

  printf "\033[38;5;208m%s: %s\033[0m\n→ Read %s for fix\n→ Next: continue preflight/tasklist, not broad rg/find\n" \
    "$gate_id" "$cause" "$block_file" >&2

  if [ -n "${run_id:-}" ] && [ -f ".claude/scripts/vg-orchestrator" ]; then
    VG_RUN_ID="${run_id:-}" CLAUDE_SESSION_ID="${run_session_id:-$session_id}" python3 .claude/scripts/vg-orchestrator emit-event \
      "vg.block.fired" \
      --actor hook \
      --outcome FAIL \
      --payload "$(VG_RUN_ID="${run_id:-}" python3 -c 'import json,os; print(json.dumps({"gate":"PreToolUse-codex-pretasklist-scope","cause":"broad pre-tasklist workflow scan","run_id":os.environ.get("VG_RUN_ID","")}))')" \
      >/dev/null 2>&1 || true
  fi
  exit 2
}

if [[ ! "$cmd_text" =~ vg-orchestrator[[:space:]]+step-active ]]; then
  if codex_before_first_step && is_broad_codex_prestep_scan; then
    emit_codex_prestep_scope_block
  fi
  if codex_before_tasklist_projection && is_broad_codex_prestep_scan; then
    emit_codex_pretasklist_scope_block
  fi
  exit 0
fi

if [ ! -f "$run_file" ]; then
  exit 0  # no active run; nothing to gate.
fi

evidence_path=".vg/runs/${run_id}/.tasklist-projected.evidence.json"
contract_path=".vg/runs/${run_id}/tasklist-contract.json"
key_path="${VG_EVIDENCE_KEY_PATH:-.vg/.evidence-key}"
step_name=""
if [[ "$cmd_text" =~ vg-orchestrator[[:space:]]+step-active[[:space:]]+([A-Za-z0-9_.:-]+) ]]; then
  step_name="${BASH_REMATCH[1]}"
fi
is_bootstrap_before_tasklist() {
  case "${command_from_run}:${step_name}" in
    vg:blueprint:0_design_discovery|\
    vg:blueprint:0_amendment_preflight|\
    vg:blueprint:1_parse_args|\
    vg:build:0_gate_integrity_precheck|\
    vg:build:0_session_lifecycle|\
    vg:test:00_gate_integrity_precheck|\
    vg:test:00_session_lifecycle|\
    vg:accept:0_gate_integrity_precheck|\
    vg:accept:0_load_config|\
    vg:review:00_gate_integrity_precheck|\
    vg:review:00_session_lifecycle|\
    vg:scope:0_parse_and_validate|\
    vg:roam:0_parse_and_validate|\
    vg:roam:0aa_resume_check|\
    vg:deploy:0_parse_and_validate)
      return 0
      ;;
  esac
  return 1
}

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
    echo "Before any non-bootstrap \`vg-orchestrator step-active\` call, you MUST:"
    echo ""
    echo "1. Ensure \`${contract_path}\` exists. If missing, run the command's"
    echo "   \`emit-tasklist.py\` preflight block first."
    echo "2. Read \`${contract_path}\` (parse \`checklists[]\`)."
    echo "3. Call the \`TodoWrite\` tool with one entry per \`items[]\` row."
    echo "4. Run:"
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

if [ ! -f "$contract_path" ]; then
  if is_bootstrap_before_tasklist; then
    exit 0
  fi
  emit_block "tasklist contract missing at ${contract_path}; run emit-tasklist.py and project the native tasklist before step ${step_name:-unknown}"
fi

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
  ok) ;;
  hmac_invalid) emit_block "evidence file HMAC invalid (signature does not match key)" ;;
  contract_mismatch) emit_block "evidence contract checksum does not match current tasklist-contract.json" ;;
  *) emit_block "evidence verification failed: ${verify_result}" ;;
esac

# Task 44b — Rule V3: depth check. After HMAC + contract SHA pass, parse the
# evidence JSON for `depth_valid` and BLOCK if false. Closes audit P4 (flat
# group-only TodoWrite would otherwise satisfy this hook entirely).
depth_check_result="$(python3 - "$evidence_path" <<'PY'
import json, sys
ev = json.loads(open(sys.argv[1]).read())
payload = ev.get("payload", {}) if isinstance(ev, dict) else {}
# Backward-compat: pre-Task-44b evidence has no `depth_valid` field.
# Treat missing as INVALID — re-projection required (additive, see RFC).
if "depth_valid" not in payload:
    flat = ",".join(payload.get("flat_groups", []) or [])
    print(f"depth_missing|{flat}", end="")
    sys.exit(0)
if payload.get("depth_valid") is True:
    print("ok", end="")
    sys.exit(0)
flat = ",".join(payload.get("flat_groups", []) or [])
print(f"depth_invalid|{flat}", end="")
PY
)"

case "$depth_check_result" in
  ok) ;;
  depth_invalid*)
    flat="${depth_check_result#depth_invalid|}"
    emit_block "tasklist depth=1 (flat); minimum required is 2-layer (group + ↳ sub-items). Flat groups: ${flat:-<all>}. Rewrite TodoWrite with \`↳ sub-step\` items under each group header."
    ;;
  depth_missing*)
    emit_block "evidence missing depth_valid field — pre-Task-44b evidence rejected; re-run TodoWrite + tasklist-projected to refresh signed evidence."
    ;;
  *) emit_block "depth check failed: ${depth_check_result}" ;;
esac

# Task 44b — Rule V1: evidence run_id binding. After depth check, verify the
# run_id baked into the evidence payload matches the run_id of the active run.
# Closes audit P3 (cross-session evidence reuse: prior run's evidence with same
# contract_sha could satisfy a fresh run unless we compare run_id).
run_id_check_result="$(python3 - "$evidence_path" "$run_id" <<'PY'
import json, sys
ev = json.loads(open(sys.argv[1]).read())
expected_run_id = sys.argv[2]
payload = ev.get("payload", {}) if isinstance(ev, dict) else {}
ev_run_id = payload.get("run_id")
if not ev_run_id:
    print("run_id_missing", end="")
    sys.exit(0)
if ev_run_id != expected_run_id:
    print(f"run_id_mismatch|{ev_run_id}", end="")
    sys.exit(0)
print("ok", end="")
PY
)"

emit_run_mismatch_telemetry() {
  local mismatch_kind="$1"
  if [ -n "$command_from_run" ]; then
    local event_type="${command_from_run/vg:/}.tasklist_evidence_run_mismatch"
    if ! CLAUDE_SESSION_ID="${session_id}" python3 .claude/scripts/vg-orchestrator emit-event \
        "$event_type" --actor hook --outcome WARN \
        --payload "{\"run_id\":\"${run_id}\",\"kind\":\"${mismatch_kind}\"}" \
        >/dev/null 2>&1; then
      VG_EVENT_TYPE="$event_type" VG_RUN_ID="$run_id" VG_KIND="$mismatch_kind" \
      python3 -c '
import sqlite3, json, datetime, os
from pathlib import Path
repo = Path(os.environ.get("VG_REPO_ROOT", ".")).resolve()
db_path = repo / ".vg" / "events.db"
if db_path.exists():
    event_type = os.environ["VG_EVENT_TYPE"]
    run_id = os.environ["VG_RUN_ID"]
    kind = os.environ["VG_KIND"]
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, run_id TEXT, command TEXT, event_type TEXT,
        ts TEXT, payload_json TEXT, actor TEXT, outcome TEXT)""")
    conn.execute(
        "INSERT INTO events(run_id, event_type, ts, payload_json, actor, outcome) VALUES (?,?,?,?,?,?)",
        (run_id, event_type,
         datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
         json.dumps({"run_id": run_id, "kind": kind}),
         "hook", "WARN"))
    conn.commit()
    conn.close()
' 2>/dev/null || true
    fi
  fi
}

case "$run_id_check_result" in
  ok) ;;
  run_id_mismatch*)
    other="${run_id_check_result#run_id_mismatch|}"
    emit_run_mismatch_telemetry "mismatch"
    emit_block "evidence run_id mismatch (cross-session reuse detected): evidence belongs to run '${other}' but active run is '${run_id}'. Re-run TodoWrite + tasklist-projected for the current run."
    ;;
  run_id_missing)
    emit_run_mismatch_telemetry "missing"
    emit_block "evidence missing run_id field — re-run TodoWrite + tasklist-projected to refresh signed evidence (additive Task 44b field)."
    ;;
  *) emit_block "run_id check failed: ${run_id_check_result}" ;;
esac

# Task 44b — Rule V4: block.handled counter-check. Closes audit P1 (15+ PV3
# bypass instances): AI emits vg.block.handled without performing TodoWrite +
# tasklist-projected. We require evidence mtime > most recent block.handled
# for gate=PreToolUse-tasklist on this run. Any handled-without-refresh
# pattern HARD BLOCKS here.
events_db_path=".vg/events.db"
handled_check_result="ok"
if [ -f "$events_db_path" ]; then
  handled_check_result="$(VG_RUN_ID="${run_id}" VG_EV_PATH="$evidence_path" VG_DB_PATH="$events_db_path" python3 - <<'PY'
import os, sqlite3, sys, json
from pathlib import Path
from datetime import datetime, timezone

run_id = os.environ["VG_RUN_ID"]
ev_path = Path(os.environ["VG_EV_PATH"])
db_path = Path(os.environ["VG_DB_PATH"])
gate_id = "PreToolUse-tasklist"

if not ev_path.exists() or not db_path.exists():
    print("ok", end="")
    sys.exit(0)

conn = sqlite3.connect(str(db_path))
try:
    rows = conn.execute(
        "SELECT ts, payload_json FROM events "
        "WHERE run_id = ? AND event_type = 'vg.block.handled' "
        "ORDER BY id DESC LIMIT 50",
        (run_id,),
    ).fetchall()
finally:
    conn.close()

# Find most recent vg.block.handled whose payload references gate PreToolUse-tasklist.
last_handled_ts = None
for ts, payload_json in rows:
    try:
        payload = json.loads(payload_json or "{}")
    except Exception:
        payload = {}
    if payload.get("gate") == gate_id:
        last_handled_ts = ts
        break

if last_handled_ts is None:
    print("ok", end="")
    sys.exit(0)

# Parse handled ts (ISO 8601 UTC) → epoch.
try:
    if last_handled_ts.endswith("Z"):
        dt = datetime.strptime(last_handled_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    else:
        dt = datetime.fromisoformat(last_handled_ts)
    handled_epoch = dt.timestamp()
except Exception:
    # Codex round-4 I-3 fix: unparseable ts → fail CLOSED (was: fail-open
    # downgraded V4 to no-op when emitter wrote bad timestamps).
    print(f"unresolved|{last_handled_ts}", end="")
    sys.exit(0)

ev_mtime = ev_path.stat().st_mtime
# Codex round-4 I-1 fix: drop 1s slack — was inverting safety direction
# (created 2s bypass window when AI emitted handled then raced to write
# evidence). Strict ev_mtime > handled_epoch instead.
if ev_mtime <= handled_epoch:
    print(f"unresolved|{last_handled_ts}", end="")
    sys.exit(0)
print("ok", end="")
PY
)"
fi

emit_handled_unresolved_telemetry() {
  if [ -n "$command_from_run" ]; then
    local event_type="${command_from_run/vg:/}.tasklist_block_handled_unresolved"
    if ! CLAUDE_SESSION_ID="${session_id}" python3 .claude/scripts/vg-orchestrator emit-event \
        "$event_type" --actor hook --outcome WARN \
        --payload "{\"run_id\":\"${run_id}\",\"gate\":\"PreToolUse-tasklist\"}" \
        >/dev/null 2>&1; then
      VG_EVENT_TYPE="$event_type" VG_RUN_ID="$run_id" python3 -c '
import sqlite3, json, datetime, os
from pathlib import Path
repo = Path(os.environ.get("VG_REPO_ROOT", ".")).resolve()
db_path = repo / ".vg" / "events.db"
if db_path.exists():
    event_type = os.environ["VG_EVENT_TYPE"]
    run_id = os.environ["VG_RUN_ID"]
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, run_id TEXT, command TEXT, event_type TEXT,
        ts TEXT, payload_json TEXT, actor TEXT, outcome TEXT)""")
    conn.execute(
        "INSERT INTO events(run_id, event_type, ts, payload_json, actor, outcome) VALUES (?,?,?,?,?,?)",
        (run_id, event_type,
         datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
         json.dumps({"run_id": run_id, "gate": "PreToolUse-tasklist"}),
         "hook", "WARN"))
    conn.commit()
    conn.close()
' 2>/dev/null || true
    fi
  fi
}

case "$handled_check_result" in
  ok) exit 0 ;;
  unresolved*)
    emit_handled_unresolved_telemetry
    handled_ts="${handled_check_result#unresolved|}"
    emit_block "block.handled emitted but evidence not refreshed since (handled at ${handled_ts}, evidence older). AI must re-run TodoWrite + tasklist-projected — emitting vg.block.handled alone does NOT satisfy the gate."
    ;;
  # Codex round-4 I-2 fix: catch-all was `exit 0` (fail OPEN) inconsistent
  # with V1/V2/V3 fail-CLOSED. Now mirror sibling gates — block on unknown.
  *) emit_block "handled check failed: ${handled_check_result}" ;;
esac
