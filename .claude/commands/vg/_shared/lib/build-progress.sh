#!/bin/bash
# build-progress.sh — compact-safe progress persistence for /vg:build.
#
# Problem:
#   Long builds (5+ min, multiple waves) span Claude Code context compacts.
#   After compact, orchestrator loses track of:
#     - Which tasks committed (and their commit SHAs)
#     - Which tasks are in flight (agent IDs, start times)
#     - Which tasks failed/were killed
#     - Current wave, expected task count
#   Result: orchestrator either re-spawns completed work or abandons in-flight
#   work silently. User sees "nothing happened" with no diagnostic.
#
# Solution:
#   .vg/phases/{phase}/.build-progress.json — single source of truth that
#   survives compacts. Read it at any time (including after compact) to
#   answer "where are we?"
#
# JSON schema:
#   {
#     "phase": "10",
#     "wave_started_at": "2026-04-19T14:00:00Z",
#     "current_wave": 5,
#     "wave_tag": "vg-build-10-wave-5-start",
#     "tasks_expected": [15, 16, 17, 18, 19],
#     "tasks_committed": [
#       {"task": 15, "commit": "abc1234", "at": "..."}
#     ],
#     "tasks_in_flight": [
#       {"task": 16, "agent_id": "a1b2c3", "started_at": "...", "mutex_acquired_at": null}
#     ],
#     "tasks_failed": [
#       {"task": 18, "reason": "OOM", "at": "..."}
#     ],
#     "last_updated": "..."
#   }
#
# Usage from orchestrator or executor:
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/build-progress.sh"
#   vg_build_progress_init "${PHASE_DIR}" 5 "${WAVE_TAG}" 15 16 17 18 19
#   vg_build_progress_start_task "${PHASE_DIR}" 15 "agent-abc"
#   vg_build_progress_commit_task "${PHASE_DIR}" 15 "abc1234"
#   vg_build_progress_fail_task "${PHASE_DIR}" 18 "OOM"
#   vg_build_progress_status "${PHASE_DIR}"    # pretty-print

set -u

_vg_progress_file() {
  echo "$1/.build-progress.json"
}

_vg_progress_now() {
  date -u +%FT%TZ
}

# Init or reset progress file for a new wave.
# Args: phase_dir, wave_num, wave_tag, task_numbers...
vg_build_progress_init() {
  local phase_dir="$1"
  local wave_num="$2"
  local wave_tag="$3"
  shift 3
  local tasks_json="[$(printf '%s,' "$@" | sed 's/,$//')]"
  local file
  file=$(_vg_progress_file "$phase_dir")
  local now
  now=$(_vg_progress_now)

  cat > "$file" <<EOF
{
  "phase": "$(basename "$phase_dir" | grep -oE '^[0-9]+(\.[0-9]+)*')",
  "current_wave": $wave_num,
  "wave_tag": "$wave_tag",
  "wave_started_at": "$now",
  "tasks_expected": $tasks_json,
  "tasks_committed": [],
  "tasks_in_flight": [],
  "tasks_failed": [],
  "last_updated": "$now"
}
EOF
  echo "progress: wave $wave_num init — expected tasks $tasks_json"
}

# Record a task as started (agent spawned).
# Args: phase_dir, task_num, agent_id (optional)
vg_build_progress_start_task() {
  local phase_dir="$1"
  local task_num="$2"
  local agent_id="${3:-unknown}"
  local file
  file=$(_vg_progress_file "$phase_dir")
  [ ! -f "$file" ] && return 1

  ${PYTHON_BIN:-python3} - "$file" "$task_num" "$agent_id" "$(_vg_progress_now)" <<'PY'
import json, sys
f, task, agent, now = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
d = json.load(open(f, encoding='utf-8'))
# Remove from failed if retrying
d['tasks_failed'] = [x for x in d['tasks_failed'] if x['task'] != task]
# Append to in_flight if not already there
d['tasks_in_flight'] = [x for x in d['tasks_in_flight'] if x['task'] != task]
d['tasks_in_flight'].append({
    'task': task, 'agent_id': agent,
    'started_at': now, 'mutex_acquired_at': None,
})
d['last_updated'] = now
json.dump(d, open(f, 'w', encoding='utf-8'), indent=2)
PY
}

# Mark task as having acquired the commit mutex (inside critical section).
# Called by the mutex helper on successful acquire.
vg_build_progress_mutex_acquired() {
  local phase_dir="$1"
  local task_num="$2"
  local file
  file=$(_vg_progress_file "$phase_dir")
  [ ! -f "$file" ] && return 0

  ${PYTHON_BIN:-python3} - "$file" "$task_num" "$(_vg_progress_now)" <<'PY' 2>/dev/null || true
import json, sys
f, task, now = sys.argv[1], int(sys.argv[2]), sys.argv[3]
d = json.load(open(f, encoding='utf-8'))
for x in d['tasks_in_flight']:
    if x['task'] == task:
        x['mutex_acquired_at'] = now
d['last_updated'] = now
json.dump(d, open(f, 'w', encoding='utf-8'), indent=2)
PY
}

# Record a task as committed. Moves from in_flight → committed.
# Args: phase_dir, task_num, commit_sha
vg_build_progress_commit_task() {
  local phase_dir="$1"
  local task_num="$2"
  local commit_sha="$3"
  # Phase F v2.5: optional verification fields — when passed, /vg:recover
  # can skip tasks with full verification record (no re-run after compact)
  local typecheck_status="${4:-}"     # "PASS" | "FAIL" | "" (empty = not recorded)
  local test_summary="${5:-}"         # JSON like {"passed":12,"failed":0} or ""
  local wave_verify_status="${6:-}"   # "PASS" | "FAIL" | "SKIP" | ""
  local run_id="${7:-}"               # UUID for run identity ancestry check
  local file
  file=$(_vg_progress_file "$phase_dir")
  [ ! -f "$file" ] && return 0

  ${PYTHON_BIN:-python3} - "$file" "$task_num" "$commit_sha" "$(_vg_progress_now)" \
    "$typecheck_status" "$test_summary" "$wave_verify_status" "$run_id" <<'PY' 2>/dev/null || true
import json, sys
args = sys.argv[1:]
f, task, sha, now = args[0], int(args[1]), args[2], args[3]
typecheck = args[4] if len(args) > 4 else ""
test_summary_raw = args[5] if len(args) > 5 else ""
wave_verify = args[6] if len(args) > 6 else ""
run_id = args[7] if len(args) > 7 else ""

d = json.load(open(f, encoding='utf-8'))
# Clear from in_flight + failed (task may have been retried after prior fail)
d['tasks_in_flight'] = [x for x in d['tasks_in_flight'] if x['task'] != task]
d['tasks_failed']    = [x for x in d['tasks_failed']    if x['task'] != task]
d['tasks_committed'] = [x for x in d['tasks_committed'] if x['task'] != task]

entry = {'task': task, 'commit': sha, 'at': now}
# Phase F v2.5 verification fields (omit if not supplied to keep JSON clean)
if typecheck:
    entry['typecheck'] = typecheck
if test_summary_raw:
    try:
        entry['test_summary'] = json.loads(test_summary_raw)
    except Exception:
        entry['test_summary'] = {'raw': test_summary_raw}
if wave_verify:
    entry['wave_verify'] = wave_verify
if run_id:
    entry['run_id'] = run_id

d['tasks_committed'].append(entry)
d['last_updated'] = now
json.dump(d, open(f, 'w', encoding='utf-8'), indent=2)
PY
}

# Phase F v2.5: check if task has full verification record so /vg:recover can skip.
# Args: phase_dir, task_num
# Stdout: "yes" if fully verified (typecheck=PASS + wave_verify=PASS), else "no"
vg_build_progress_is_task_fully_verified() {
  local phase_dir="$1"
  local task_num="$2"
  local file
  file=$(_vg_progress_file "$phase_dir")
  [ ! -f "$file" ] && { echo "no"; return 0; }

  ${PYTHON_BIN:-python3} - "$file" "$task_num" <<'PY' 2>/dev/null || echo "no"
import json, sys
f, task = sys.argv[1], int(sys.argv[2])
d = json.load(open(f, encoding='utf-8'))
for t in d.get('tasks_committed', []):
    if t.get('task') == task:
        tc = t.get('typecheck', '')
        wv = t.get('wave_verify', '')
        if tc == 'PASS' and wv in ('PASS', 'SKIP'):
            print('yes')
            sys.exit(0)
print('no')
PY
}

# Record a task as failed. Moves from in_flight → failed.
vg_build_progress_fail_task() {
  local phase_dir="$1"
  local task_num="$2"
  local reason="$3"
  local file
  file=$(_vg_progress_file "$phase_dir")
  [ ! -f "$file" ] && return 0

  ${PYTHON_BIN:-python3} - "$file" "$task_num" "$reason" "$(_vg_progress_now)" <<'PY' 2>/dev/null || true
import json, sys
f, task, reason, now = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
d = json.load(open(f, encoding='utf-8'))
d['tasks_in_flight'] = [x for x in d['tasks_in_flight'] if x['task'] != task]
d['tasks_failed'] = [x for x in d['tasks_failed'] if x['task'] != task]
d['tasks_failed'].append({'task': task, 'reason': reason, 'at': now})
d['last_updated'] = now
json.dump(d, open(f, 'w', encoding='utf-8'), indent=2)
PY
}

# Check for stuck agents — tasks that acquired the mutex long ago but never
# committed. Returns:
#   0 = all healthy
#   1 = stuck tasks detected (prints list to stderr, stuck task numbers to stdout)
#   2 = no progress file
# Args: phase_dir [stuck_threshold_secs=600]
vg_build_progress_check_stuck() {
  local phase_dir="$1"
  local threshold="${2:-600}"
  local file
  file=$(_vg_progress_file "$phase_dir")
  [ ! -f "$file" ] && return 2

  ${PYTHON_BIN:-python3} - "$file" "$threshold" <<'PY'
import json, sys
from datetime import datetime, timezone
f, thr = sys.argv[1], int(sys.argv[2])
try:
    d = json.load(open(f, encoding='utf-8'))
except Exception:
    sys.exit(2)

now = datetime.now(timezone.utc)
stuck_tasks = []
age_in_cs = []  # tasks that acquired mutex but still in critical section too long

for x in d.get('tasks_in_flight', []):
    try:
        started = datetime.fromisoformat(x['started_at'].replace('Z', '+00:00'))
        age = int((now - started).total_seconds())
    except Exception:
        continue
    if age > thr:
        stuck_tasks.append((x['task'], age, x.get('agent_id', '?')))
    m = x.get('mutex_acquired_at')
    if m:
        try:
            ma = datetime.fromisoformat(m.replace('Z', '+00:00'))
            csec = int((now - ma).total_seconds())
            if csec > 120:  # critical section > 2 min = very suspicious
                age_in_cs.append((x['task'], csec))
        except Exception:
            pass

if not stuck_tasks and not age_in_cs:
    sys.exit(0)

if stuck_tasks:
    print(f"⚠ {len(stuck_tasks)} task(s) in-flight > {thr}s:", file=sys.stderr)
    for t, age, aid in stuck_tasks:
        print(f"  Task {t}: age={age}s agent={aid}", file=sys.stderr)
        print(t)

if age_in_cs:
    print(f"⚠ {len(age_in_cs)} task(s) holding commit mutex > 120s:", file=sys.stderr)
    for t, csec in age_in_cs:
        print(f"  Task {t}: {csec}s in critical section", file=sys.stderr)
        # Also emit to stdout if not already from stuck_tasks
        if not any(s[0] == t for s in stuck_tasks):
            print(t)

sys.exit(1)
PY
}

# Pretty-print current progress state. Safe to call anytime.
# Compact-safe: reads persisted file, doesn't rely on in-memory state.
vg_build_progress_status() {
  local phase_dir="$1"
  local file
  file=$(_vg_progress_file "$phase_dir")
  if [ ! -f "$file" ]; then
    echo "progress: no .build-progress.json at $file"
    return 1
  fi

  ${PYTHON_BIN:-python3} - "$file" <<'PY'
import json, sys
from datetime import datetime, timezone

f = sys.argv[1]
d = json.load(open(f, encoding='utf-8'))

expected = d.get('tasks_expected', [])
committed = d.get('tasks_committed', [])
in_flight = d.get('tasks_in_flight', [])
failed = d.get('tasks_failed', [])

committed_nums = sorted(x['task'] for x in committed)
in_flight_nums = sorted(x['task'] for x in in_flight)
failed_nums = sorted(x['task'] for x in failed)
not_started = sorted(set(expected) - set(committed_nums) - set(in_flight_nums) - set(failed_nums))

print(f"━━━ Wave {d.get('current_wave')} progress ━━━")
print(f"Phase:       {d.get('phase')}")
print(f"Started:     {d.get('wave_started_at')}")
print(f"Expected:    {expected}")
print(f"Committed:   {committed_nums}  ({len(committed_nums)}/{len(expected)})")
print(f"In-flight:   {in_flight_nums}")
print(f"Failed:      {failed_nums}")
print(f"Not started: {not_started}")

if in_flight:
    now = datetime.now(timezone.utc)
    print("\nIn-flight detail:")
    for x in sorted(in_flight, key=lambda t: t['task']):
        started = datetime.fromisoformat(x['started_at'].replace('Z', '+00:00'))
        age = int((now - started).total_seconds())
        mutex = x.get('mutex_acquired_at')
        mstr = ''
        if mutex:
            m = datetime.fromisoformat(mutex.replace('Z', '+00:00'))
            mstr = f' | in critical section for {int((now - m).total_seconds())}s'
        print(f"  Task {x['task']}: agent={x.get('agent_id','?')} age={age}s{mstr}")

if committed:
    print("\nCommitted detail:")
    for x in sorted(committed, key=lambda t: t['task']):
        print(f"  Task {x['task']}: commit={x['commit'][:8]} at={x['at']}")

if failed:
    print("\nFailed detail:")
    for x in sorted(failed, key=lambda t: t['task']):
        print(f"  Task {x['task']}: reason={x['reason']} at={x['at']}")

# Resume hint
if not_started or in_flight:
    print("\nResume hint:")
    if not_started:
        print(f"  Tasks not started: {not_started}")
        print(f"  Re-spawn via: /vg:build {d.get('phase')} --wave {d.get('current_wave')} --only {','.join(str(n) for n in not_started)}")
    if in_flight:
        stuck = []
        for x in in_flight:
            started = datetime.fromisoformat(x['started_at'].replace('Z', '+00:00'))
            age = int((now - started).total_seconds())
            if age > 600:  # >10 min = likely stuck
                stuck.append(x['task'])
        if stuck:
            print(f"  Tasks in-flight >10min (likely stuck): {stuck}")
            print(f"  Kill + restart: /vg:build {d.get('phase')} --reset-queue --only {','.join(str(n) for n in stuck)}")
PY
}
