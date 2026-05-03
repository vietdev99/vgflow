<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 31: Cross-session block awareness in SessionStart hook (Diagnostic-v2)

**Why:** Codex GPT-5.5 round 6 missing-proposal #5: today `scripts/hooks/vg-session-start.sh` only reinjects open diagnostics for the SAME session that fires the SessionStart event. If session A leaves a block unhandled and crashes/quits, then session B starts (different `CLAUDE_HOOK_SESSION_ID`), session B has no idea there's a stuck block from A. Operator must `cd` and grep `.vg/blocks/` manually.

**Fix:** SessionStart hook queries unhandled blocks across ALL `.vg/active-runs/*.json` (not just current session), labels each with `owner_session`, and reinjects with a clear "previous session left this stuck" prefix.

**Files:**
- Modify: `scripts/hooks/vg-session-start.sh`
- Create: `tests/test_session_start_cross_session.py`

- [ ] **Step 1: Inspect existing SessionStart hook**

Read `scripts/hooks/vg-session-start.sh` end-to-end first. The relevant block (around lines 29-45 per Codex review) currently does:

```bash
# Pseudocode of CURRENT behavior:
session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
run_file=".vg/active-runs/${session_id}.json"
if [ -f "$run_file" ]; then
  run_id="$(jq -r .run_id "$run_file")"
  fired="$(sqlite3 "$EVENTS_DB" "SELECT payload_json FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'" ...)"
  # reinject open diagnostics for THIS run only
fi
```

This task EXTENDS, not replaces. Same-session blocks still get reinjected (priority 1); cross-session blocks added below them (priority 2).

- [ ] **Step 2: Update SessionStart hook**

Replace the block enumeration logic with cross-session aware version. Approximate target shape (adapt to existing variable names):

```bash
# Step 1 — Same-session blocks (existing behavior, KEEP)
session_id="${CLAUDE_HOOK_SESSION_ID:-default}"
own_run_file=".vg/active-runs/${session_id}.json"
own_run_id=""
if [ -f "$own_run_file" ]; then
  own_run_id="$(jq -r .run_id "$own_run_file" 2>/dev/null || echo '')"
fi

emit_open_diagnostics() {
  local run_id="$1"
  local owner_label="$2"   # "this session" OR "session ${prefix}..."
  [ -z "$run_id" ] && return

  # After Task 28 dedupe + Task 29 severity, query for distinct gates with
  # NO matching handled, severity error|critical only:
  local unhandled_gates="$(sqlite3 "$EVENTS_DB" "
    SELECT DISTINCT json_extract(payload_json, '\$.gate'),
           json_extract(payload_json, '\$.cause'),
           json_extract(payload_json, '\$.block_file'),
           json_extract(payload_json, '\$.severity'),
           json_extract(payload_json, '\$.skill_path')
    FROM events
    WHERE run_id='$run_id' AND event_type IN ('vg.block.fired', 'vg.block.refired')
    AND COALESCE(json_extract(payload_json, '\$.severity'), 'error') IN ('error', 'critical')
    AND json_extract(payload_json, '\$.gate') NOT IN (
      SELECT json_extract(payload_json, '\$.gate')
      FROM events
      WHERE run_id='$run_id' AND event_type='vg.block.handled'
    )
  " 2>/dev/null)"

  if [ -z "$unhandled_gates" ]; then
    return
  fi

  echo "## OPEN DIAGNOSTICS — ${owner_label}"
  echo "$unhandled_gates" | while IFS='|' read -r gate cause block_file severity skill_path; do
    echo "- gate=${gate} severity=${severity:-error}"
    echo "  cause: ${cause}"
    [ -n "$block_file" ] && echo "  block_file: ${block_file}"
    [ -n "$skill_path" ] && echo "  skill: ${skill_path}"
  done
  echo ""
}

# Emit own session's diagnostics first
emit_open_diagnostics "$own_run_id" "this session"

# Step 2 — Cross-session blocks (NEW)
for run_file in .vg/active-runs/*.json; do
  [ "$run_file" = "$own_run_file" ] && continue
  [ -f "$run_file" ] || continue

  other_session_id="$(basename "$run_file" .json)"
  other_run_id="$(jq -r .run_id "$run_file" 2>/dev/null || echo '')"
  [ -z "$other_run_id" ] && continue

  # Skip terminal runs (run.aborted/completed events)
  is_terminal="$(sqlite3 "$EVENTS_DB" "
    SELECT 1 FROM events
    WHERE run_id='$other_run_id'
    AND event_type IN ('run.completed', 'run.aborted')
    LIMIT 1
  " 2>/dev/null)"
  [ -n "$is_terminal" ] && continue

  emit_open_diagnostics "$other_run_id" "session ${other_session_id:0:8}... (cross-session — not yours, but stuck)"
done
```

- [ ] **Step 3: Tests**

Create `tests/test_session_start_cross_session.py`:

```python
"""Task 31 — SessionStart cross-session block awareness.

Pin: SessionStart hook reports unhandled blocks from OTHER active runs
labeled with owner session prefix.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCH = str(REPO_ROOT / ".claude/scripts/vg-orchestrator")
SS_HOOK = str(REPO_ROOT / "scripts/hooks/vg-session-start.sh")


def _setup_two_runs(tmp: Path) -> tuple[str, str]:
    """Init repo + start runs for 2 distinct sessions. Returns (session_a, session_b) ids."""
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    sess_a = "sess-aaaaaaaa-1234"
    sess_b = "sess-bbbbbbbb-5678"

    for sess, command, phase in [(sess_a, "vg:build", "1.1"), (sess_b, "vg:review", "2.2")]:
        env = os.environ.copy()
        env["VG_REPO_ROOT"] = str(tmp)
        env["CLAUDE_SESSION_ID"] = sess
        rs = subprocess.run(
            [sys.executable, ORCH, "run-start", command, phase],
            env=env, capture_output=True, text=True, cwd=str(tmp), timeout=15,
        )
        assert rs.returncode == 0, rs.stderr

    return sess_a, sess_b


def _emit(env, tmp, etype, gate, severity="error", **extra):
    payload = {"gate": gate, "severity": severity, "cause": f"cause for {gate}", **extra}
    subprocess.run(
        [sys.executable, ORCH, "emit-event", etype,
         "--actor", "hook", "--outcome", "BLOCK",
         "--gate", gate, "--cause", f"cause for {gate}",
         "--severity", severity,
         "--payload", json.dumps(payload)],
        env=env, capture_output=True, text=True, cwd=str(tmp), timeout=10, check=True,
    )


def _run_session_start(tmp: Path, session: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", SS_HOOK],
        input="{}",
        env={**os.environ,
             "CLAUDE_HOOK_SESSION_ID": session,
             "VG_REPO_ROOT": str(tmp)},
        capture_output=True, text=True, cwd=str(tmp), timeout=15,
    )


def test_session_start_lists_own_session_block(tmp_path):
    sess_a, sess_b = _setup_two_runs(tmp_path)
    env_a = {**os.environ, "VG_REPO_ROOT": str(tmp_path), "CLAUDE_SESSION_ID": sess_a}
    _emit(env_a, tmp_path, "vg.block.fired", "gate-from-A", severity="error")

    proc = _run_session_start(tmp_path, sess_a)
    # Hook stdout/stderr should include "this session" label and gate name
    out = proc.stdout + proc.stderr
    assert "gate-from-A" in out
    assert "this session" in out


def test_session_start_lists_other_session_block(tmp_path):
    sess_a, sess_b = _setup_two_runs(tmp_path)
    # B has the unhandled block; A starts a new session, should see B's block.
    env_b = {**os.environ, "VG_REPO_ROOT": str(tmp_path), "CLAUDE_SESSION_ID": sess_b}
    _emit(env_b, tmp_path, "vg.block.fired", "gate-from-B", severity="error")

    proc = _run_session_start(tmp_path, sess_a)
    out = proc.stdout + proc.stderr
    assert "gate-from-B" in out
    assert "cross-session" in out or sess_b[:8] in out


def test_session_start_omits_handled_blocks(tmp_path):
    sess_a, sess_b = _setup_two_runs(tmp_path)
    env_b = {**os.environ, "VG_REPO_ROOT": str(tmp_path), "CLAUDE_SESSION_ID": sess_b}
    _emit(env_b, tmp_path, "vg.block.fired", "gate-resolved", severity="error")
    _emit(env_b, tmp_path, "vg.block.handled", "gate-resolved")
    _emit(env_b, tmp_path, "vg.block.fired", "gate-still-open", severity="error")

    proc = _run_session_start(tmp_path, sess_a)
    out = proc.stdout + proc.stderr
    assert "gate-still-open" in out
    assert "gate-resolved" not in out


def test_session_start_omits_warn_severity_blocks(tmp_path):
    """Warn-tier unhandled doesn't pollute SessionStart reinjection (Task 29 contract)."""
    sess_a, sess_b = _setup_two_runs(tmp_path)
    env_b = {**os.environ, "VG_REPO_ROOT": str(tmp_path), "CLAUDE_SESSION_ID": sess_b}
    _emit(env_b, tmp_path, "vg.block.fired", "warn-only", severity="warn")
    _emit(env_b, tmp_path, "vg.block.fired", "real-error", severity="error")

    proc = _run_session_start(tmp_path, sess_a)
    out = proc.stdout + proc.stderr
    assert "real-error" in out
    assert "warn-only" not in out


def test_session_start_skips_terminal_runs(tmp_path):
    """When session B's run is run.aborted, its blocks don't surface."""
    sess_a, sess_b = _setup_two_runs(tmp_path)
    env_b = {**os.environ, "VG_REPO_ROOT": str(tmp_path), "CLAUDE_SESSION_ID": sess_b}
    _emit(env_b, tmp_path, "vg.block.fired", "gate-stale", severity="error")
    # Abort B's run
    subprocess.run(
        [sys.executable, ORCH, "run-abort", "--reason", "test cleanup"],
        env=env_b, capture_output=True, text=True, cwd=str(tmp_path), timeout=10,
    )
    proc = _run_session_start(tmp_path, sess_a)
    out = proc.stdout + proc.stderr
    assert "gate-stale" not in out
```

- [ ] **Step 4: Smoke run**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_session_start_cross_session.py -v
```

Expected: 5/5 PASS. NOTE: depends on Tasks 28 + 29 landing first (severity field + dedupe pairing). If running this task alone before 28+29, severity check + handled check still work because old payloads default to error tier.

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/vg-session-start.sh \
        tests/test_session_start_cross_session.py
git commit -m "$(cat <<'EOF'
feat(diag-v2): cross-session block awareness in SessionStart (Task 31)

Pre-fix: SessionStart only reinjected unhandled blocks from the SAME
CLAUDE_HOOK_SESSION_ID. Operator starting a fresh session had no idea
about stuck blocks left by an earlier crashed/quit session.

Post-fix:
- SessionStart enumerates ALL .vg/active-runs/*.json
- Same-session blocks reported first ("this session" label)
- Other sessions' blocks reported below ("session XXXXX... cross-session")
- Filters: severity in (error, critical), runs not in terminal state
  (skips run.aborted/run.completed)
- Reuses payload fields populated by Tasks 28-30 (severity, gate,
  cause, block_file, skill_path)

5 tests covering own-session, cross-session, handled-omits, warn-omits,
terminal-omits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Codex round 6 correction notes (inlined)

- **Q:** Privacy concern — should session B see session A's block details if they're different operators?
  **A:** VGFlow runs are operator-local (single dev's machine). All sessions share the same `.vg/`. No privacy boundary; transparency wins.

- **Q:** What if a stale orphan run never terminates (no run.aborted)?
  **A:** Stop hook OHOK-FIX-2 logic auto-aborts cross-session stale orphans. SessionStart in this task does NOT auto-abort — it just reports. Operator can `vg-orchestrator run-abort --run-id X` if they want to clean up.

- **Q:** Performance — SessionStart now reads N active-runs files + N sqlite queries. Latency budget?
  **A:** Typical N ≤ 5 (most operators run 1-3 concurrent sessions). Sqlite queries are indexed on run_id + event_type, ~1-3ms each. Total <50ms added to SessionStart, well within budget.
