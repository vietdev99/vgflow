---
name: vg:_shared:session-lifecycle
description: Session Lifecycle (Shared Reference) — session-start banner, EXIT trap, stale state sweep to keep UI tail clean across runs
---

# Session Lifecycle — Shared Helper

When `/vg:review`, `/vg:test`, `/vg:build` run narration status lines, Claude Code's UI "Baking…" tail displays the most recent lines. If a run is interrupted (compact, error, user cancel), those lines stay visible in the tail until replaced. Next run mixes old + new progress.

This helper fixes that via:
1. **Session-start banner** at entry — clear visual separator
2. **EXIT trap** — emit termination marker on any exit path (normal, error, signal)
3. **Stale state sweep** — detect + clean leftover `.{cmd}-state.json` from previous interrupted runs
4. **Port sweep** — kill orphan dev servers on target port before starting new one

## Tasklist Projection Policy (CRITICAL — read first if executing review/test/build)

**Native tasklist projection is REQUIRED for pipeline commands** when the
runtime exposes a native task UI. The old blanket ban on TodoWrite/TaskCreate
was replaced by a stricter contract-based rule:

- Only project tasks from `.vg/runs/<run_id>/tasklist-contract.json`.
- Do not create ad-hoc todos/tasks.
- Use `replace-on-start`: the first native tasklist projection of a command
  MUST replace the previous native list, not append to it.
- Use `close-on-complete`: on normal completion, mark every current contract
  checklist completed, then clear the native list if the runtime accepts an
  empty list. If the runtime rejects empty lists, replace it with one completed
  sentinel item: `vg:<command> phase <phase> complete`.
- On Claude Code, prefer `TodoWrite` with one todo per checklist group. If the
  runtime exposes `TaskCreate`/`TaskUpdate`, that adapter is also acceptable.
- On Codex, use the native plan/tasklist UI when available; otherwise use the
  fallback adapter.
- Immediately record projection with
  `vg-orchestrator tasklist-projected --adapter <claude|codex|fallback>`.
- At step start/end, update the native task UI and emit
  `vg-orchestrator step-active` / `vg-orchestrator mark-step`.

### Why ad-hoc tasklists remain banned

Uncontracted TodoWrite/TaskCreate items can persist in Claude Code's status tail
box across sessions. The symptom: items like "Phase 2b-1: Navigator" or
"Start pnpm dev + wait health" hang for runs after the original session ended.
Root causes remain real:

1. **Conditional policy gets skipped** — model rationalizes "I won't use tasklist this run" then uses it anyway.
2. **Long Task subagent blocks updates** — parent UI can stay frozen while subagents run.
3. **Bash echo lands in tool result block** — useful for audit, weak for live UI.
4. **EXIT trap is bash-only** — it cannot call model-only task tools after interruption.
5. **Subagent tasklist ≠ parent tasklist** — child conversations do not reliably update parent UI.

The fix is not "no native task UI"; the fix is "native task UI must be a
projection of the harness contract and backed by markers/events." A new
workflow run always owns the full native tasklist; stale items from a prior run
must never be carried forward.

### Use these together

| Need | Tool | Why |
|------|------|-----|
| Checklist/tasklist UI | `TodoWrite` or native Task adapter from `tasklist-contract.json` | Visible progress tied to the harness contract |
| Step header user sees during run | **Markdown `## ━━━ Phase X ━━━` in your text output** between tool calls | Appears in message stream, doesn't persist after session |
| Progress during long Bash (>30s) | **`run_in_background: true` + `BashOutput` polls** | User sees stdout live |
| Long Task subagent (>2 min) | **1-line text BEFORE spawning + 1-line summary AFTER** | Both visible in message stream |
| Audit log (artifact, not UX) | `narrate_phase` echo into log file | Persisted to disk, not shown live |

### Banner is still useful

`session_start` banner + EXIT trap remain — they write to bash stdout which appears in the Bash tool result. Useful for **audit log** (proves the run happened, with timing) but NOT for live UX. Don't rely on them as primary progress signal.

## API

```bash
# Call at TOP of /vg:review, /vg:test, /vg:build (after config load)
session_start() {
  local cmd="$1"        # "review" | "test" | "build"
  local phase="$2"      # "7.12"
  local ts
  ts=$(date -u +%FT%TZ)

  # Distinct visual separator — breaks tail UI continuity with previous run
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  /vg:${cmd} Phase ${phase} — starting ${ts}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  export VG_SESSION_CMD="$cmd"
  export VG_SESSION_PHASE="$phase"
  export VG_SESSION_START_TS="$ts"
  export VG_SESSION_CURRENT_STEP="start"

  # v1.15.2 — register run so Stop hook can verify runtime_contract evidence.
  # vg_run_start writes .vg/current-run.json + emits {cmd}.started telemetry.
  # Sourced by config-loader.md via _shared/lib/vg-run.sh.
  type -t vg_run_start >/dev/null 2>&1 && \
    vg_run_start "vg:${cmd}" "${phase}" "${ARGUMENTS:-}"

  # OHOK Batch 5b (E1): source marker-schema so step bodies can use
  # mark_step for forgery-resistant content markers. Individual touch calls
  # have been rewritten to prefer mark_step when available.
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/marker-schema.sh" 2>/dev/null || true

  # EXIT trap emits termination marker no matter how command ends
  # (normal exit, error, Ctrl+C, SIGTERM from parent)
  trap 'session_exit_banner' EXIT INT TERM
}

# Caller updates this as it moves through steps — trap reads it on exit
session_mark_step() {
  export VG_SESSION_CURRENT_STEP="$1"
}

session_exit_banner() {
  local rc=$?
  local cmd="${VG_SESSION_CMD:-unknown}"
  local phase="${VG_SESSION_PHASE:-?}"
  local step="${VG_SESSION_CURRENT_STEP:-unknown}"
  local verdict
  case "$rc" in
    0) verdict="COMPLETE" ;;
    130) verdict="CANCELLED (Ctrl+C)" ;;
    143) verdict="TERMINATED (SIGTERM)" ;;
    *) verdict="EXITED rc=${rc}" ;;
  esac
  echo ""
  echo "━━━ /vg:${cmd} Phase ${phase} — ${verdict} at step=${step} ━━━"
  echo ""

  # OHOK-3 (2026-04-22): legacy vg_run_complete bash helper removed.
  # Canonical path is `python .claude/scripts/vg-orchestrator run-complete`,
  # invoked at the terminal block of each /vg:* skill (accept, blueprint,
  # build, review, scope, test). If rc=0 and that terminal block already ran,
  # run-complete has already been called — nothing to do here. If rc≠0 the
  # skill exited early; leaving current-run.json lets /vg:recover inspect.
  # One lifecycle path only.

  # Clear trap to avoid recursion if something in banner fails
  trap - EXIT INT TERM
  exit $rc
}

# Call at start — detect + sweep leftover state from previous interrupted run
# Path convention: ${PLANNING_DIR}/phases/{phase}/.{cmd}-state.json
stale_state_sweep() {
  local cmd="$1"
  local phase_dir="$2"
  local state_file="${phase_dir}/.${cmd}-state.json"
  local stale_hours="${CONFIG_SESSION_STALE_HOURS:-1}"

  [ -f "$state_file" ] || return 0

  # Age in hours (portable — Python since find -mmin varies)
  local age_h
  age_h=$(${PYTHON_BIN:-python3} -c "
import os, time
try:
  mtime = os.path.getmtime('$state_file')
  print(int((time.time() - mtime) / 3600))
except Exception:
  print(999)
")

  if [ "$age_h" -gt "$stale_hours" ]; then
    local mtime_str
    mtime_str=$(${PYTHON_BIN:-python3} -c "
import os, datetime
try:
  ts = os.path.getmtime('$state_file')
  print(datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M'))
except Exception:
  print('unknown')
")
    echo "🧹 Cleaning stale ${cmd} state from ${mtime_str} (${age_h}h old)"
    rm -f "$state_file"
    # Also sweep sibling artifacts that might be half-written
    for sibling in "${phase_dir}/.${cmd}-"*.tmp "${phase_dir}/.${cmd}-"*.partial; do
      [ -f "$sibling" ] && rm -f "$sibling"
    done
  fi
}

# Port sweep — kill anything listening on ports the dev stack needs
# Relies on config.dev_process_markers listing expected listeners.
session_port_sweep() {
  local purpose="${1:-pre-flight}"
  [ -n "${CONFIG_DEV_PROCESS_MARKERS:-}" ] || return 0

  # Iterate config.dev_process_markers[].port
  ${PYTHON_BIN:-python3} - "${CONFIG_VG_CONFIG_PATH:-.claude/vg.config.md}" <<'PY' | while IFS= read -r port; do
import sys, re
from pathlib import Path
try:
  text = Path(sys.argv[1]).read_text(encoding='utf-8')
except Exception:
  sys.exit(0)
# Look under dev_process_markers: for port entries
m = re.search(r'^\s*dev_process_markers:\s*$([\s\S]*?)(?=^\S|\Z)', text, re.M)
if not m: sys.exit(0)
for line in m.group(1).splitlines():
  pm = re.search(r'port:\s*(\d+)', line)
  if pm: print(pm.group(1))
PY
    [ -z "$port" ] && continue
    # Cross-platform port kill
    case "$(uname -s)" in
      MINGW*|MSYS*|CYGWIN*)
        # Windows via git-bash
        pids=$(netstat -ano 2>/dev/null | awk -v p=":${port}" '$2 ~ p && /LISTENING/ {print $NF}' | sort -u)
        for pid in $pids; do
          [ -n "$pid" ] && taskkill //PID "$pid" //F 2>/dev/null && echo "🧹 Killed PID ${pid} on port ${port}"
        done
        ;;
      *)
        # Linux/macOS
        pids=$(lsof -ti ":${port}" 2>/dev/null)
        for pid in $pids; do
          kill -9 "$pid" 2>/dev/null && echo "🧹 Killed PID ${pid} on port ${port}"
        done
        ;;
    esac
  done
}
```

## Config (add to vg.config.md)

```yaml
session:
  stale_hours: 1                    # state files older than N hours → auto-sweep
  port_sweep_on_start: true         # kill orphan dev servers before pre-flight
```

## Integration template

At top of `/vg:review`, `/vg:test`, `/vg:build` command files:

```bash
<step name="0_session_start">
# Source shared helpers (already part of config-loader pattern)
source .claude/commands/vg/_shared/lib/session-lifecycle.sh   # .sh when extracted (v1.9.0 T3); functions inline in practice today

# Pre-mutation Codex mirror sync check (lib/premutation-sync-check.sh).
# Runs BEFORE session_start so a drift block fails fast without consuming
# orchestrator run-start budget. No-op if mirrors already in sync.
[ -f "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/premutation-sync-check.sh" ] && \
  source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/premutation-sync-check.sh" && \
  premutation_sync_check "{cmd_name}" 2>&1 || true

PHASE_NUMBER="..."  # resolved from args
PHASE_DIR="${PLANNING_DIR}/phases/${PHASE_NUMBER}..."

session_start "{cmd_name}" "$PHASE_NUMBER"                # emits banner + sets EXIT trap
stale_state_sweep "{cmd_name}" "$PHASE_DIR"               # auto-cleanup old state
[ "${CONFIG_SESSION_PORT_SWEEP_ON_START:-true}" = "true" ] && session_port_sweep "pre-flight"
</step>

<step name="1_...">
session_mark_step "1-load-config"
# actual work
</step>

...
```

Each major step calls `session_mark_step` so EXIT trap knows where interruption happened. Output:
```
━━━ /vg:review Phase 7.12 — COMPLETE at step=5-final-report ━━━
```
or on Ctrl+C:
```
━━━ /vg:review Phase 7.12 — CANCELLED (Ctrl+C) at step=2b-haiku-scan ━━━
```

## Why this solves "UI tail kẹt"

**Before (problem):**
- Run 1: narrates "Phase 2b-1: Navigator", "Phase 2b-2: Haiku scanner"
- Session compact mid-run — tail keeps last 3 narration lines visible forever
- Run 2 starts — tail still shows Run 1's stale lines until new output pushes them out

**After (fix):**
- Run 1 end (any cause): EXIT trap emits `━━━ EXITED at step X ━━━` → tail updates to this clear terminal marker
- Run 2 starts: session_start emits `━━━ starting @ts ━━━` banner → tail replaced with fresh session marker
- Even if Run 1 was killed hard (no trap chance): Run 2's start banner + stale state sweep make new session state unambiguous

## Success criteria

- Every `/vg:review`, `/vg:test`, `/vg:build` emits session-start banner as FIRST output
- Session-end banner always emits (trap on EXIT/INT/TERM), even on error paths
- `.{cmd}-state.json` older than `session.stale_hours` auto-cleaned at start
- Port sweep removes orphan dev servers listening on config-declared ports
- Tail UI shows CURRENT session's most recent step, never previous session's
- Zero cost if session.enabled is false (pure opt-in)
