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

## TodoWrite policy (CRITICAL — read first if executing review/test/build)

The "stuck UI tail" symptom (3 items hanging in "Baking…" / "Hullaballooing…" status box across runs) is caused by **TodoWrite items not being marked completed** when the previous run interrupted. Echo narration (`narrate_phase`, etc.) does NOT cause this — only TodoWrite does.

**If you use TodoWrite to track progress through `/vg:review`, `/vg:test`, or `/vg:build`:**

1. **FIRST TodoWrite call** must contain the FULL step list for this run. TodoWrite **replaces** the entire list (it doesn't merge), so this displaces any stale items left over from a previous interrupted session. Even if you don't track every step, the first call should overwrite at least 1 item to clear the tail.

2. **As each step completes** → TodoWrite update marking it `completed` immediately. Don't batch.

3. **At session end (success path)** → all items should already be `completed` from step 2. If any still `pending`/`in_progress`, mark them completed before returning.

4. **At session end (error path)** → before exiting/raising, mark remaining items completed (or use a final TodoWrite with single `completed` item like "review-aborted-at-step-X"). Do NOT leave `in_progress` items behind.

5. **On Ctrl+C / EXIT trap** → bash trap can't call TodoWrite (model-only tool). The session_exit_banner emits an `━━━ EXITED at step=X ━━━` line which displaces narration tail, but TodoWrite items persist. Solution: keep TodoWrite list minimal and always mark complete in main flow.

**Recommended pattern**: prefer `narrate_phase`/echo for granular per-step progress (no kẹt risk). Reserve TodoWrite for top-level milestones that cross many tool calls and warrant user-visible checkboxes — typically 3-7 items max for the entire run.

**Anti-pattern (causes stuck tail)**: TodoWrite "Start pnpm dev", "Phase 2b-1", "Phase 2b-2" then run agent that takes 30 min → user interrupts → those 3 items hang forever in tail until user manually clears or session restart.

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
  # Clear trap to avoid recursion if something in banner fails
  trap - EXIT INT TERM
  exit $rc
}

# Call at start — detect + sweep leftover state from previous interrupted run
# Path convention: .planning/phases/{phase}/.{cmd}-state.json
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
source .claude/commands/vg/_shared/session-lifecycle.md   # conceptual — inline in practice

PHASE_NUMBER="..."  # resolved from args
PHASE_DIR=".planning/phases/${PHASE_NUMBER}..."

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
