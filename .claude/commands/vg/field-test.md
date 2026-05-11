---
name: vg:field-test
description: User-driven field test capture — AI opens MCP Playwright browser with floating Start/Stop/Mark overlay; human roams manually; AI silently captures browser console + network + clicks + nav + per-Mark notes + correlated API server log tails. On Stop, analyzer subagent produces FIELD-REPORT.md + appends entries to .vg/KNOWN-ISSUES.json. Distinct from AI-driven /vg:roam.
argument-hint: "[--phase=N] [--base-url=<url>] [--redact=<regex>] [--allow-zero-marks]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - AskUserQuestion
  - TodoWrite
  - mcp__playwright1__browser_navigate
  - mcp__playwright1__browser_evaluate
  - mcp__playwright1__browser_console_messages
  - mcp__playwright1__browser_take_screenshot
  - mcp__playwright1__browser_snapshot
  - mcp__playwright1__browser_close
runtime_contract:
  must_write:
    - ".vg/field-test/${SID}/session.json"
    - ".vg/field-test/${SID}/manifest.json"
    - ".vg/field-test/${SID}/FIELD-REPORT.md"
  must_touch_markers:
    - "0_preflight"
    - "1_resolve_config"
    - "2_launch_browser"
    - "3_inject_overlay"
    - "4_wait_start"
    - "5_capture_loop"
    - "6_stop_finalize"
    - "7_analyze"
    - "complete"
  must_emit_telemetry:
    - event_type: "field_test.session_started"
    - event_type: "field_test.session_stopped"
    - event_type: "field_test.analysis_completed"
    - event_type: "field_test.mark_recorded"
      required_unless_flag: "--allow-zero-marks"
---

<HARD-GATE>
This skill captures live user behavior. Default redaction applies to
console, network, API log streams, and user notes. Screenshots are NOT redacted.

⚠ Do NOT navigate to password/payment/credentials views during this session
  unless that is the explicit test target. Screenshots embed pixel content as-is.

Atomic lock at `.vg/field-test/.active` prevents concurrent sessions.
On crash, manual cleanup: `rm -rf .vg/field-test/.active`
(or run `python scripts/field-test/release-lock.py --root .`).

v1 does NOT support `--resume`. A browser crash mid-session leaves raw
streams under `.vg/field-test/<sid>/` for manual triage; rerun
`build-bundle.py` + `analyze.py` manually if needed.
</HARD-GATE>

## Overview

`/vg:field-test` is a USER-driven exploratory capture skill. Distinct from `/vg:roam`:
- `/vg:roam` = AI-driven. Spawns executors that auto-replay lenses against discovered surfaces.
- `/vg:field-test` = USER-driven. Human roams manually; AI is a silent recorder.

On Stop, an analyzer subagent produces `FIELD-REPORT.md` and appends entries to `.vg/KNOWN-ISSUES.json`. Downstream consumers (`/vg:test-spec`, `/vg:review`) read those entries to enrich lifecycle context.

## Step 0: Preflight (`0_preflight`)

```bash
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# v2.1 §3: atomic lock via mkdir (NOT echo > file — TOCTOU race).
mkdir -p "${REPO_ROOT}/.vg/field-test" 2>/dev/null
if ! mkdir "${REPO_ROOT}/.vg/field-test/.active" 2>/dev/null; then
  ACTIVE_OWNER=$(cat "${REPO_ROOT}/.vg/field-test/.active/owner" 2>/dev/null || echo "unknown")
  echo "⛔ field-test session active (sid=${ACTIVE_OWNER})" >&2
  echo "   Run: python scripts/field-test/release-lock.py --root \"${REPO_ROOT}\"" >&2
  echo "   to clear a stuck lock (PID-aware)." >&2
  exit 1
fi

# Build session id: ft-<ts> (or ft-p<N>-<ts> when --phase=N supplied).
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
PHASE_TAG=""
case " $ARGUMENTS " in *" --phase="*)
  PHASE_NUMBER=$(echo "$ARGUMENTS" | sed -n 's/.*--phase=\([^ ]*\).*/\1/p')
  PHASE_TAG="-p${PHASE_NUMBER}"
  ;;
esac
SID="ft${PHASE_TAG}-${TS}"
SESSION_DIR="${REPO_ROOT}/.vg/field-test/${SID}"
mkdir -p "${SESSION_DIR}/marks"

# Record owner PID for release-lock.py liveness check.
printf '%s' "$SID" > "${REPO_ROOT}/.vg/field-test/.active/owner"
printf '%s' "$$" > "${REPO_ROOT}/.vg/field-test/.active/pid"
trap 'rm -rf "${REPO_ROOT}/.vg/field-test/.active"' EXIT
```

## Step 1: Resolve config (`1_resolve_config`)

Use `AskUserQuestion` to confirm:
- **Redaction regex** — precedence order:
  1. If `--redact=<regex>` was passed in `$ARGUMENTS`, use it directly (skip the question).
  2. Else if `vg.config.md` has `field_test.default_redaction`, prompt with it as default.
  3. Else prompt with hard-coded multi-form default (`password|token|secret|api[_-]?key|email|phone`).
- **API log sources** — precedence:
  1. If `vg.config.md` has `field_test.api_log_sources`, prompt to confirm/edit.
  2. Else prompt user for at least one source.
- **Base URL** — precedence:
  1. `--base-url=<url>` flag from `$ARGUMENTS`.
  2. `vg.config.md` `field_test.default_base_url`.
  3. Prompt user.

Write `${SESSION_DIR}/session.json` matching `schemas/field-test-session.v1.json`.

## Step 2: Launch browser (`2_launch_browser`)

```
mcp__playwright1__browser_navigate({ url: "<base_url>" })
```

## Step 3: Inject overlay (`3_inject_overlay`)

```bash
OVERLAY_PATH="${REPO_ROOT}/scripts/field-test/overlay.js"
OVERLAY_JS=$(cat "$OVERLAY_PATH")
```

Then call:
```
mcp__playwright1__browser_evaluate({
  function: "() => { ${OVERLAY_JS} }"
})
```

Verify injection:
```
mcp__playwright1__browser_evaluate({
  function: "() => typeof window.__VG_FT_INIT === 'function'"
})
```

## Step 4: Wait for Start (`4_wait_start`)

Poll `mcp__playwright1__browser_console_messages` with offset tracking for `[VG_FT] start` edge event.

On hit:
```bash
# Spawn per-source tails (each pipes through redact-stream.py at capture).
for src_label in $(${PYTHON_BIN} -c "import json,sys; [print(s['label']) for s in json.load(open(sys.argv[1]))['sources']]" "${SESSION_DIR}/session.json"); do
  SRC_TYPE=$(${PYTHON_BIN} -c "import json,sys; s=[x for x in json.load(open(sys.argv[1]))['sources'] if x['label']==sys.argv[2]][0]; print(s['type'])" "${SESSION_DIR}/session.json" "$src_label")
  SRC_TARGET=$(${PYTHON_BIN} -c "import json,sys; s=[x for x in json.load(open(sys.argv[1]))['sources'] if x['label']==sys.argv[2]][0]; print(s['target'])" "${SESSION_DIR}/session.json" "$src_label")
  REDACT=$(${PYTHON_BIN} -c "import json,sys; print(json.load(open(sys.argv[1])).get('redaction') or 'default')" "${SESSION_DIR}/session.json")
  bash "${REPO_ROOT}/scripts/field-test/tail-source.sh" \
    --type "$SRC_TYPE" --target "$SRC_TARGET" \
    --out "${SESSION_DIR}/api-${src_label}.log" \
    --redact "$REDACT" &
  echo "$!" >> "${SESSION_DIR}/.tail-pids"
done

${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-orchestrator" emit-event \
  field_test.session_started --payload "{\"sid\":\"$SID\"}"
```

## Step 5: Capture loop (`5_capture_loop`)

v2.1 §1 + MUST-4: poll overlay state directly (NOT console_messages — that is a snapshot reader that replays the buffer and would duplicate marks). On SPA full-reload, the browser wipes `window.__VG_FT_STATE` and the next re-inject restarts `reload_epoch=0` — detect via `epoch < last_epoch` (K→0 transition) and reset `last_consumed=0`.

```bash
last_consumed=0
last_epoch=0

while true; do
  # AI tool call:
  #   mcp__playwright1__browser_evaluate({
  #     function: "() => window.__VG_FT_STATE ? ({ len: window.__VG_FT_STATE.marks.length, status: window.__VG_FT_STATE.status, epoch: window.__VG_FT_STATE.reload_epoch }) : null"
  #   })
  #
  # If null returned (full reload erased state): re-inject overlay.js, set last_consumed=0.
  # Else if returned.epoch < last_epoch: full reload — re-inject + last_consumed=0.
  # Else if returned.len > last_consumed:
  #   mcp__playwright1__browser_evaluate({
  #     function: "() => window.__VG_FT_STATE.marks.slice(N, M)"  # N=last_consumed, M=returned.len
  #   })
  #   For each new mark <n,...>:
  #     mcp__playwright1__browser_take_screenshot({ filename: "${SESSION_DIR}/marks/<n>.png" })
  #     mcp__playwright1__browser_snapshot({ filename: "${SESSION_DIR}/marks/<n>.snapshot.yml" })
  #     append entry to ${SESSION_DIR}/marks.raw.jsonl
  #     emit field_test.mark_recorded with payload {"sid": "$SID", "n": <n>}
  #   last_consumed = returned.len
  #
  # If returned.status == "stopped": break and proceed to Step 6.

  # v2.1 MUST-2: enforce size + wall-clock caps each iter.
  if ! ${PYTHON_BIN} "${REPO_ROOT}/scripts/field-test/check-quota.py" --session-dir "${SESSION_DIR}"; then
    echo "⛔ quota exceeded — forcing Stop" >&2
    break
  fi

  sleep 2
done
```

## Step 6: Stop + bundle (`6_stop_finalize`)

```bash
# Kill tails: TERM → 5s grace → KILL.
if [ -f "${SESSION_DIR}/.tail-pids" ]; then
  while read -r tpid; do
    kill -TERM "$tpid" 2>/dev/null || true
  done < "${SESSION_DIR}/.tail-pids"
  sleep 5
  while read -r tpid; do
    kill -KILL "$tpid" 2>/dev/null || true
  done < "${SESSION_DIR}/.tail-pids"
fi

# Dump any remaining overlay buffers via browser_evaluate.
# (AI emits: mcp__playwright1__browser_evaluate({function: "() => JSON.stringify(window.__VG_FT_STATE.buffer)"})
#  and writes result to ${SESSION_DIR}/buffer.dump.json)

# Build bundle.
${PYTHON_BIN} "${REPO_ROOT}/scripts/field-test/build-bundle.py" \
  --session-dir "${SESSION_DIR}" \
  --mark-window-sec "${MARK_WINDOW_SEC:-30}"

# v2.1 / #175: emit evidence-manifest entries for the bundle artifacts.
EMIT_MANIFEST="${REPO_ROOT}/.claude/scripts/emit-evidence-manifest.py"
[ -f "$EMIT_MANIFEST" ] || EMIT_MANIFEST="${REPO_ROOT}/scripts/emit-evidence-manifest.py"
if [ -f "$EMIT_MANIFEST" ]; then
  ${PYTHON_BIN} "$EMIT_MANIFEST" \
    --path "${SESSION_DIR}/manifest.json" \
    --producer "vg:field-test 6_stop_finalize" \
    --source-inputs "${SESSION_DIR}/session.json,${SESSION_DIR}/marks.raw.jsonl" \
    --quiet || true
fi

${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-orchestrator" emit-event \
  field_test.session_stopped --payload "{\"sid\":\"$SID\"}"
```

## Step 7: Analyze (`7_analyze`)

Spawn the `vg-field-test-analyzer` subagent (see `agents/vg-field-test-analyzer/SKILL.md`). Subagent runs `analyze.py` deterministically, then optionally augments `FIELD-REPORT.md` with LLM narrative on HIGH/MEDIUM marks.

```bash
${PYTHON_BIN} "${REPO_ROOT}/scripts/field-test/analyze.py" \
  --session-dir "${SESSION_DIR}" \
  --known-issues "${REPO_ROOT}/.vg/KNOWN-ISSUES.json"

# v2.1 / #175: emit evidence-manifest for FIELD-REPORT.md.
# Re-resolve EMIT_MANIFEST in case Step 7 runs in a fresh subshell separated
# from Step 6 (Agent dispatch, etc.).
EMIT_MANIFEST="${REPO_ROOT}/.claude/scripts/emit-evidence-manifest.py"
[ -f "$EMIT_MANIFEST" ] || EMIT_MANIFEST="${REPO_ROOT}/scripts/emit-evidence-manifest.py"
if [ -f "$EMIT_MANIFEST" ] && [ -f "${SESSION_DIR}/FIELD-REPORT.md" ]; then
  ${PYTHON_BIN} "$EMIT_MANIFEST" \
    --path "${SESSION_DIR}/FIELD-REPORT.md" \
    --producer "vg:field-test 7_analyze" \
    --source-inputs "${SESSION_DIR}/manifest.json,${SESSION_DIR}/marks.jsonl" \
    --quiet || true
fi

${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-orchestrator" emit-event \
  field_test.analysis_completed --payload "{\"sid\":\"$SID\"}"
```

## Step 8: Complete (`complete`)

Auto-emit `field_test.session_completed` via MARKER_TO_AUTO_EVENT (Task 7d wiring). Remove lock directory (`trap EXIT` handles this).

```bash
${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-orchestrator" mark-step field-test complete
```

## Outputs

- `.vg/field-test/<sid>/manifest.json` — bundle manifest (8 fields).
- `.vg/field-test/<sid>/marks.jsonl` — per-Mark bundle entries.
- `.vg/field-test/<sid>/FIELD-REPORT.md` — human-readable report with severity per Mark.
- `.vg/field-test/<sid>/errors.jsonl` — naive timestamps + truncated lines (NEVER silent drops).
- `.vg/KNOWN-ISSUES.json` — appended entries, deduped by (source=field-test, sid, n).

## Scope (v1 — deferred to v2)

- No `--resume` (implementation absent; plan v2 dropped it).
- No `quick`/`deep` presets (single `standard` profile only).
- No phase-snapshot mirror under versioned directories (committed-or-ignored policy unresolved).
- No `--non-interactive` (user-driven skill has no useful headless mode).
- No auto-recovered crash bundle (manual triage on browser crash).
