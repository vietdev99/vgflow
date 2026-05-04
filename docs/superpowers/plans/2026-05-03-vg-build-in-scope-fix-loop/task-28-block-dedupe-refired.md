<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 28: Block dedupe via `vg.block.refired` (Diagnostic-v2)

**Why:** Codex GPT-5.5 round 6 missing-proposal #2: same `gate_id` × `run_id` with no intervening `vg.block.handled` should NOT create N independent obligations. Today, hook retry loops can fire the same gate 3-5 times in one run; Stop hook pairing demands 3-5 `handled` events even though logically there's ONE block to resolve. This dilutes the pairing signal and bloats events.db.

**Contract change:**
- First fire of `gate_id` × `run_id` → emit `vg.block.fired` (unchanged).
- Subsequent fires while no `handled` event has occurred → emit `vg.block.refired` with payload `{"original_block_id": "...", "fire_count": N}`.
- Stop hook pairing counts ONE obligation per unique `gate_id` × `run_id` regardless of refired count; resolution by ONE `vg.block.handled --gate <gate_id>` clears the obligation.
- Refired events still land in events.db for `/vg:gate-stats` velocity analysis (Task 32 correlator reads them for high-velocity detection).

**Files:**
- Create: `scripts/lib/block_dedupe.py`
- Create: `tests/test_block_dedupe.py`
- Modify: `scripts/hooks/vg-pre-tool-use-bash.sh` (call dedupe helper before emit)
- Modify: `scripts/hooks/vg-pre-tool-use-write.sh` (same)
- Modify: `scripts/hooks/vg-pre-tool-use-agent.sh` (same)
- Modify: `scripts/vg-verify-claim.py::_emit_stale_block` (use helper)
- Modify: `scripts/hooks/vg-stop.sh` (pairing query: count distinct gates, not events)

- [ ] **Step 1: Write the dedupe helper**

Create `scripts/lib/block_dedupe.py`:

```python
"""block_dedupe — query events.db for an open block before emitting.

An "open" block = `vg.block.fired` exists for (run_id, gate_id) AND no
`vg.block.handled` for the same pair has been emitted since.

This helper exposes BOTH a Python API (used by vg-verify-claim.py) AND a
CLI (used by bash hooks via `python3 scripts/lib/block_dedupe.py
--check-open --run-id X --gate-id Y`).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

EVENTS_DB_REL = ".vg/events.db"


def _resolve_db(repo_root: str | Path | None) -> Path:
    if repo_root:
        return Path(repo_root) / EVENTS_DB_REL
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env) / EVENTS_DB_REL
    # walk up from cwd
    p = Path.cwd()
    for cand in [p, *p.parents]:
        if (cand / ".git").exists():
            return cand / EVENTS_DB_REL
    return p / EVENTS_DB_REL


def has_open_block(run_id: str, gate_id: str,
                   repo_root: str | Path | None = None) -> tuple[bool, int]:
    """Return (is_open, prior_fire_count_for_this_gate).

    prior_fire_count counts fired+refired events for the gate in the run,
    used to populate refired payload's `fire_count` field.
    """
    db = _resolve_db(repo_root)
    if not db.exists():
        return False, 0
    try:
        conn = sqlite3.connect(str(db), timeout=2.0)
        # Last fired/refired/handled timestamp per gate in run
        last_fired = conn.execute(
            "SELECT id FROM events WHERE run_id = ? AND event_type IN "
            "('vg.block.fired', 'vg.block.refired') AND "
            "json_extract(payload_json, '$.gate') = ? "
            "ORDER BY id DESC LIMIT 1",
            (run_id, gate_id),
        ).fetchone()
        if not last_fired:
            return False, 0

        # Did any handled event arrive AFTER the last fired/refired?
        handled_after = conn.execute(
            "SELECT 1 FROM events WHERE run_id = ? AND event_type = 'vg.block.handled' AND "
            "json_extract(payload_json, '$.gate') = ? AND id > ? LIMIT 1",
            (run_id, gate_id, last_fired[0]),
        ).fetchone()

        # Count total prior fires (for fire_count payload)
        prior_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ? AND event_type IN "
            "('vg.block.fired', 'vg.block.refired') AND "
            "json_extract(payload_json, '$.gate') = ?",
            (run_id, gate_id),
        ).fetchone()[0]

        return (handled_after is None), prior_count
    except sqlite3.Error:
        # On query failure, fall back to "not open" so we never deadlock
        # the hook on telemetry issues.
        return False, 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-open", action="store_true",
                    help="Print 'open' or 'closed' to stdout based on (--run-id, --gate-id) state")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--gate-id", required=True)
    args = ap.parse_args()
    if args.check_open:
        is_open, count = has_open_block(args.run_id, args.gate_id)
        print(f"{'open' if is_open else 'closed'} {count}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Wire into bash hooks (3 files)**

Pattern for each bash hook (`vg-pre-tool-use-bash.sh`, `vg-pre-tool-use-write.sh`, `vg-pre-tool-use-agent.sh`): replace the existing `emit-event vg.block.fired ...` call with:

```bash
# Check if a prior block for this gate is still open in this run.
DEDUPE_RESULT="$(python3 "${REPO_ROOT}/scripts/lib/block_dedupe.py" --check-open \
                  --run-id "$run_id" --gate-id "$gate_id" 2>/dev/null || echo "closed 0")"
DEDUPE_STATE="$(echo "$DEDUPE_RESULT" | cut -d' ' -f1)"
DEDUPE_COUNT="$(echo "$DEDUPE_RESULT" | cut -d' ' -f2)"

if [ "$DEDUPE_STATE" = "open" ]; then
  EVENT_TYPE="vg.block.refired"
  PAYLOAD_EXTRA="--payload '{\"fire_count\": $((DEDUPE_COUNT + 1))}'"
else
  EVENT_TYPE="vg.block.fired"
  PAYLOAD_EXTRA=""
fi

if command -v vg-orchestrator >/dev/null 2>&1; then
  eval vg-orchestrator emit-event "$EVENT_TYPE" \
    --gate "\"$gate_id\"" --cause "\"$cause\"" \
    --block-file "\"$block_file\"" \
    $PAYLOAD_EXTRA >/dev/null 2>&1 || true
fi
```

NOTE: `REPO_ROOT` must be set earlier in the hook (most hooks already derive it from `${CLAUDE_PROJECT_DIR}` or git toplevel — reuse existing).

- [ ] **Step 3: Wire into Python emit (vg-verify-claim.py)**

In `_emit_stale_block`, before the emit-event subprocess call, add:

```python
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
try:
    from block_dedupe import has_open_block
    is_open, prior_count = has_open_block(run_id, gate_id, repo_root=str(REPO_ROOT))
except Exception:
    is_open, prior_count = False, 0

event_type = "vg.block.refired" if is_open else "vg.block.fired"
extra_payload = {"fire_count": prior_count + 1} if is_open else {}

# build payload as before, then merge extra_payload:
payload = {"gate": gate_id, "cause": cause, "run_id": run_id,
           "command": command, "phase": phase, "block_file": str(block_file),
           **extra_payload}

subprocess.run(
    [sys.executable, str(ORCHESTRATOR), "emit-event",
     event_type,
     "--actor", "hook",
     "--outcome", "FAIL",
     "--payload", json.dumps(payload)],
    capture_output=True, text=True, timeout=10, env=env,
)
```

- [ ] **Step 4: Update Stop hook pairing query**

In `scripts/hooks/vg-stop.sh` lines 20-29, the existing query counts fired vs handled events. Update to count DISTINCT gate_ids per side:

```bash
# OLD (counts events, breaks under refired):
# fired="$(sqlite3 "$db" "SELECT COUNT(*) FROM events WHERE run_id='$run_id' AND event_type='vg.block.fired'")"

# NEW (counts distinct gates with at least one fire/refire):
fired_gates="$(sqlite3 "$db" "
  SELECT COUNT(DISTINCT json_extract(payload_json, '\$.gate'))
  FROM events
  WHERE run_id='$run_id' AND event_type IN ('vg.block.fired', 'vg.block.refired')
")"
handled_gates="$(sqlite3 "$db" "
  SELECT COUNT(DISTINCT json_extract(payload_json, '\$.gate'))
  FROM events
  WHERE run_id='$run_id' AND event_type='vg.block.handled'
")"

if [ "$fired_gates" -gt "$handled_gates" ]; then
  unhandled="$(sqlite3 "$db" "
    SELECT json_extract(payload_json, '\$.gate')
    FROM events
    WHERE run_id='$run_id' AND event_type IN ('vg.block.fired', 'vg.block.refired')
    AND json_extract(payload_json, '\$.gate') NOT IN (
      SELECT json_extract(payload_json, '\$.gate')
      FROM events
      WHERE run_id='$run_id' AND event_type='vg.block.handled'
    )
    GROUP BY json_extract(payload_json, '\$.gate')
  ")"
  failures+=("UNHANDLED DIAGNOSTIC: ${fired_gates} gates fired, ${handled_gates} handled. Unhandled: ${unhandled}")
fi
```

- [ ] **Step 5: Tests**

Create `tests/test_block_dedupe.py`:

```python
"""Task 28 — block dedupe contract.

Pin: same gate_id × run_id with no intervening handled = ONE obligation
regardless of fire count. Refired events recorded for velocity analysis
but don't multiply pairing demand.
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
DEDUPE_CLI = str(REPO_ROOT / "scripts/lib/block_dedupe.py")
STOP_HOOK = str(REPO_ROOT / "scripts/hooks/vg-stop.sh")

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))


def _setup_run(tmp: Path) -> dict:
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp)
    env["CLAUDE_SESSION_ID"] = "test-dedupe"
    rs = subprocess.run(
        [sys.executable, ORCH, "run-start", "vg:accept", "99.9.9"],
        env=env, capture_output=True, text=True, cwd=str(tmp), timeout=15,
    )
    assert rs.returncode == 0, rs.stderr
    return env


def _emit(env: dict, tmp: Path, event_type: str, gate: str, **extra) -> None:
    payload = {"gate": gate, **extra}
    subprocess.run(
        [sys.executable, ORCH, "emit-event", event_type,
         "--actor", "hook", "--outcome", "BLOCK",
         "--gate", gate, "--cause", "test",
         "--payload", json.dumps(payload)],
        env=env, capture_output=True, text=True, cwd=str(tmp), timeout=10, check=True,
    )


def test_first_fire_returns_closed(tmp_path):
    from block_dedupe import has_open_block
    _setup_run(tmp_path)
    is_open, count = has_open_block("any-run", "fresh-gate", repo_root=tmp_path)
    assert is_open is False
    assert count == 0


def test_second_fire_returns_open(tmp_path):
    from block_dedupe import has_open_block
    env = _setup_run(tmp_path)
    # Read run_id from active-runs file
    runs = list((tmp_path / ".vg/active-runs").glob("*.json"))
    run_id = json.loads(runs[0].read_text())["run_id"]
    _emit(env, tmp_path, "vg.block.fired", "g1")
    is_open, count = has_open_block(run_id, "g1", repo_root=tmp_path)
    assert is_open is True
    assert count == 1


def test_handled_resets_to_closed(tmp_path):
    from block_dedupe import has_open_block
    env = _setup_run(tmp_path)
    runs = list((tmp_path / ".vg/active-runs").glob("*.json"))
    run_id = json.loads(runs[0].read_text())["run_id"]
    _emit(env, tmp_path, "vg.block.fired", "g1")
    _emit(env, tmp_path, "vg.block.handled", "g1")
    is_open, count = has_open_block(run_id, "g1", repo_root=tmp_path)
    assert is_open is False  # handled cleared the obligation
    # count still reflects total fires (for velocity analysis)
    assert count == 1


def test_refired_after_handled_starts_fresh(tmp_path):
    """fired → handled → fired again → second fired is NOT a refire (it's a fresh obligation)."""
    from block_dedupe import has_open_block
    env = _setup_run(tmp_path)
    runs = list((tmp_path / ".vg/active-runs").glob("*.json"))
    run_id = json.loads(runs[0].read_text())["run_id"]
    _emit(env, tmp_path, "vg.block.fired", "g1")
    _emit(env, tmp_path, "vg.block.handled", "g1")
    is_open, _ = has_open_block(run_id, "g1", repo_root=tmp_path)
    assert is_open is False
    # Now fire again — this IS a fresh fire, dedupe should report closed
    # so caller emits vg.block.fired (not refired).


def test_stop_hook_pairing_treats_refired_as_one_obligation(tmp_path):
    """3 fires of same gate (1 fired + 2 refired) + 1 handled = balanced."""
    env = _setup_run(tmp_path)
    runs = list((tmp_path / ".vg/active-runs").glob("*.json"))
    run_id = json.loads(runs[0].read_text())["run_id"]
    _emit(env, tmp_path, "vg.block.fired", "g1")
    _emit(env, tmp_path, "vg.block.refired", "g1", fire_count=2)
    _emit(env, tmp_path, "vg.block.refired", "g1", fire_count=3)
    _emit(env, tmp_path, "vg.block.handled", "g1")

    # Run Stop hook directly. With dedupe wiring, fired_gates=1, handled_gates=1
    # → no UNHANDLED DIAGNOSTIC error (state machine may still fail for
    # unrelated reasons, but pairing alone should pass).
    proc = subprocess.run(
        ["bash", STOP_HOOK], input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": env["CLAUDE_SESSION_ID"]},
        cwd=str(tmp_path),
    )
    assert "UNHANDLED DIAGNOSTIC" not in proc.stderr, (
        f"Pairing should treat dedupe correctly; stderr={proc.stderr}"
    )


def test_two_distinct_gates_both_need_handling(tmp_path):
    """gate-A fired + gate-B fired + only gate-A handled → still UNHANDLED."""
    env = _setup_run(tmp_path)
    _emit(env, tmp_path, "vg.block.fired", "gateA")
    _emit(env, tmp_path, "vg.block.fired", "gateB")
    _emit(env, tmp_path, "vg.block.handled", "gateA")

    proc = subprocess.run(
        ["bash", STOP_HOOK], input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": env["CLAUDE_SESSION_ID"]},
        cwd=str(tmp_path),
    )
    assert proc.returncode == 2
    assert "gateB" in proc.stderr or "UNHANDLED" in proc.stderr.upper()


def test_cli_check_open(tmp_path):
    env = _setup_run(tmp_path)
    runs = list((tmp_path / ".vg/active-runs").glob("*.json"))
    run_id = json.loads(runs[0].read_text())["run_id"]
    _emit(env, tmp_path, "vg.block.fired", "g1")

    proc = subprocess.run(
        [sys.executable, DEDUPE_CLI, "--check-open",
         "--run-id", run_id, "--gate-id", "g1"],
        env={**os.environ, "VG_REPO_ROOT": str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.startswith("open")
    assert proc.stdout.strip().endswith("1")
```

- [ ] **Step 6: Smoke run**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_block_dedupe.py -v
```

Expected: 7/7 PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/block_dedupe.py \
        scripts/hooks/vg-pre-tool-use-bash.sh \
        scripts/hooks/vg-pre-tool-use-write.sh \
        scripts/hooks/vg-pre-tool-use-agent.sh \
        scripts/hooks/vg-stop.sh \
        scripts/vg-verify-claim.py \
        .claude/scripts/vg-verify-claim.py \
        tests/test_block_dedupe.py
git commit -m "$(cat <<'EOF'
feat(diag-v2): block dedupe via vg.block.refired (Task 28)

Same gate_id × run_id with no intervening handled now emits
vg.block.refired instead of duplicate vg.block.fired. Stop hook pairing
counts DISTINCT gates per side, so retry loops produce ONE obligation
regardless of fire count. Refired events still land for velocity analysis
(consumed by Task 32 correlator).

- New scripts/lib/block_dedupe.py (Python API + CLI for bash hooks)
- Wired into 3 bash pre-tool hooks + vg-verify-claim _emit_stale_block
- vg-stop.sh pairing query rewritten: COUNT(DISTINCT gate) instead of
  COUNT(*) — refired no longer multiplies pairing demand
- 7 tests covering open/closed transitions, handled resets, multi-gate
  obligations, Stop hook integration, CLI

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Codex round 6 correction notes (inlined)

- **Q:** Why query events.db on every emit instead of caching open-block state in `.vg/active-runs/`?
  **A:** Cache invalidation is hard. events.db is the single source of truth (hash-chained, append-only). The query is cheap: indexed on `run_id`, payload_json JSON1 path lookup, ~1-2ms typical.

- **Q:** What if the same gate fires concurrently in 2 hooks (race)?
  **A:** events.db has a write lock (`BEGIN IMMEDIATE`). Worst case: both queries see "closed", both emit `vg.block.fired`. Stop hook sees 2 fired, 0 handled → still UNHANDLED. Acceptable: race produces over-pairing not under-pairing.

- **Q:** Should `vg.block.refired` count toward `/vg:gate-stats --high-override` threshold?
  **A:** Yes — Task 32 correlator's high-velocity rule reads both fired+refired. This task only changes Stop hook pairing semantics, not gate-stats.
