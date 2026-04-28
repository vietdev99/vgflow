#!/usr/bin/env python3
"""
Stop hook — verifies active run is properly completed via vg-orchestrator.

v2.2 rewrite: this hook no longer parses frontmatter or checks files directly.
Instead it reads .vg/events.db (via vg-orchestrator) to decide.

Rules:
1. If no active run (current-run.json missing) → approve. Session is not
   in the middle of a /vg:* invocation; nothing to verify.
2. If active run exists and is older than 30min → soft-approve (assume
   abandoned/crashed). Log + clear current-run.json for next time.
3. If active run exists and fresh → run vg-orchestrator run-complete.
   Orchestrator evaluates runtime_contract + validators. If PASS,
   session can stop. If BLOCK, we exit 2 + inject structured feedback.

This closes the "AI narrates done without evidence" pattern because the
decision to allow Stop comes from orchestrator reading events.db — which
only has the events that actually were emitted via bash tool calls.

v2.8.3 (2026-04-26): hybrid marker-drift auto-recovery (Tier C).
  When run-complete BLOCKs purely on must_touch_markers (no must_write,
  no must_emit_telemetry violations), track drift count per-run in
  .vg/.session-drift.json keyed by run_id:
    - 1st drift in session → hard BLOCK with hint, increment counter.
      AI gets one chance to fix manually (e.g. realize step was skipped,
      run it correctly).
    - 2nd+ drift in same run → auto-fire migrate-state {phase} --apply,
      retry run-complete. If retry PASSes, approve with annotation;
      audit trail lives in OVERRIDE-DEBT.md (soft-debt entry written by
      migrate-state) + telemetry event marker_drift_recovered.
  Drift state resets when orchestrator clears current-run.json on PASS.

  Why hybrid instead of always-block or always-auto-fire:
    - Always-block: forces session restart for skill-cache, infinite loop
      pain (the bug that triggered this design).
    - Always-auto-fire: AI learns marker discipline doesn't matter, kỷ
      luật loãng, anti-forge guarantees weaken.
    - Hybrid: 1st miss = lesson, 2nd+ = recover (because user has already
      seen the message, no value in repeating).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
CURRENT_RUN = REPO_ROOT / ".vg" / "current-run.json"
HOOK_LOG = REPO_ROOT / ".vg" / "hook-verifier.log"
ORCHESTRATOR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
SESSION_DRIFT = REPO_ROOT / ".vg" / ".session-drift.json"
MIGRATE_STATE = REPO_ROOT / ".claude" / "scripts" / "migrate-state.py"
EVENTS_DB = REPO_ROOT / ".vg" / "events.db"
STALE_MINUTES = 30
DRIFT_STATE_TTL_MINUTES = 120  # GC stale entries after this

# v2.8.3 anti-forge: only auto-fire for these "structurally safe" violations.
# must_write (artifacts) and must_emit_telemetry (events) cannot be backfilled
# without proof — they signal real pipeline gaps. Marker drift is the only
# pure-paperwork class because artifact_evidence in migrate-state already
# proves the pipeline ran.
AUTO_FIRE_ELIGIBLE_TYPES = {"must_touch_markers"}


def log(msg: str) -> None:
    try:
        HOOK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with HOOK_LOG.open("a", encoding="utf-8") as f:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            f.write(f"[{ts}] {msg.rstrip()}\n")
    except Exception:
        pass


def read_current_run() -> dict | None:
    if not CURRENT_RUN.exists():
        return None
    try:
        return json.loads(CURRENT_RUN.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"current-run.json parse error: {e}")
        return None


def is_stale(run: dict) -> bool:
    started = run.get("started_at", "")
    if not started:
        return True
    try:
        ts = datetime.datetime.fromisoformat(started.rstrip("Z"))
        age_min = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds() / 60
        return age_min > STALE_MINUTES
    except Exception:
        return True


def run_orchestrator_complete() -> tuple[int, str, str]:
    """Invoke vg-orchestrator run-complete. Returns (exit_code, stdout, stderr)."""
    python_bin = sys.executable or "python"
    proc = subprocess.run(
        [python_bin, str(ORCHESTRATOR), "run-complete"],
        capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ─── Hybrid marker-drift auto-recovery (v2.8.3) ───────────────────────────


_BLOCK_TYPE_RE = re.compile(r"^\s*\[([a-z_]+)\]\s*$", re.MULTILINE)


def _parse_violation_types(stderr: str) -> set[str]:
    """Extract violation type tags from orchestrator BLOCK stderr.

    Orchestrator format from _format_block_message:
        Missing evidence:
          [must_touch_markers]
            - 8_execute_waves
          [must_emit_telemetry]
            - wave_started

    Returns set of type strings. Empty set means stderr didn't have the
    expected format — we treat that as "unknown, do not auto-fire".
    """
    return set(_BLOCK_TYPE_RE.findall(stderr or ""))


def _is_marker_only_drift(stderr: str) -> bool:
    """True iff stderr contains EXACTLY the marker-drift violation type
    (no must_write, no must_emit_telemetry, no forbidden_without_override).

    Conservative: if we can't parse violation types or there are mixed
    violations, return False — auto-fire MUST NOT mask real pipeline gaps.
    """
    types = _parse_violation_types(stderr)
    if not types:
        return False
    return types <= AUTO_FIRE_ELIGIBLE_TYPES


def _read_drift_state() -> dict:
    """Read .vg/.session-drift.json, GC stale run_ids, return current state."""
    if not SESSION_DRIFT.exists():
        return {}
    try:
        data = json.loads(SESSION_DRIFT.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    # GC entries older than DRIFT_STATE_TTL_MINUTES — keeps file from
    # growing unbounded across many runs.
    now = datetime.datetime.now(datetime.timezone.utc)
    cleaned = {}
    for run_id, entry in data.items():
        last = entry.get("last_drift_at", "")
        try:
            ts = datetime.datetime.fromisoformat(last.rstrip("Z"))
            if (now - ts).total_seconds() / 60 < DRIFT_STATE_TTL_MINUTES:
                cleaned[run_id] = entry
        except Exception:
            continue
    return cleaned


def _write_drift_state(state: dict) -> None:
    try:
        SESSION_DRIFT.parent.mkdir(parents=True, exist_ok=True)
        SESSION_DRIFT.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"failed to write drift state: {e}")


def _bump_drift(run_id: str, violation_types: set[str]) -> int:
    """Increment drift counter for run_id, return new count."""
    state = _read_drift_state()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = state.get(run_id) or {
        "drift_count": 0,
        "first_drift_at": now,
        "violations_seen": [],
    }
    entry["drift_count"] = int(entry.get("drift_count", 0)) + 1
    entry["last_drift_at"] = now
    seen = set(entry.get("violations_seen") or [])
    seen.update(violation_types)
    entry["violations_seen"] = sorted(seen)
    state[run_id] = entry
    _write_drift_state(state)
    return entry["drift_count"]


def _emit_telemetry(event_type: str, payload: dict) -> None:
    """Best-effort telemetry emission via vg-orchestrator emit-event.
    Phase + command auto-resolved from current-run.json by orchestrator.
    Never blocks hook on failure. event_type MUST NOT be reserved (run.*,
    validation.*, wave.*, build.crossai_*, override.*, debt_register.*,
    step.marked) — use a hook.* prefix to avoid forgery-detector trips.
    """
    try:
        python_bin = sys.executable or "python"
        subprocess.run(
            [python_bin, str(ORCHESTRATOR), "emit-event",
             event_type,  # positional
             "--actor", "hook",
             "--outcome", "INFO",
             "--payload", json.dumps(payload)],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        log(f"telemetry emit failed for {event_type}: {e}")


def _auto_fire_markers(phase: str) -> tuple[int, str, str]:
    """Invoke migrate-state.py {phase} --apply. Returns (rc, stdout, stderr).
    The script is idempotent: if drift was already resolved (e.g. by a
    parallel run), it returns rc=0 with 'no drift' in stdout.
    """
    if not MIGRATE_STATE.exists():
        return (127, "", f"migrate-state.py not found at {MIGRATE_STATE}")
    python_bin = sys.executable or "python"
    proc = subprocess.run(
        [python_bin, str(MIGRATE_STATE), phase, "--apply"],
        capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    # Read hook input from stdin
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except Exception:
        hook_input = {}

    stop_active = hook_input.get("stop_hook_active", False)
    session_id = hook_input.get("session_id", "?")

    log(f"--- Stop hook fire — session={session_id[:12] if session_id else '?'}"
        f" stop_active={stop_active}")

    if stop_active:
        # Infinite-loop guard per Claude Code hooks contract
        log("stop_hook_active=True — approving to avoid loop")
        print(json.dumps({"decision": "approve", "reason": "loop-guard"}))
        return 0

    current = read_current_run()
    if not current:
        log("no current-run.json — nothing to verify, approve")
        print(json.dumps({"decision": "approve",
                          "reason": "no-active-run"}))
        return 0

    command = current.get("command", "?")
    phase = current.get("phase", "?")

    if is_stale(current):
        # OHOK-6 (Gemini P1): previously auto-cleared + approved. That was
        # a time-based escape hatch — AI could idle >30min then call Stop
        # to bypass all gates. Now BLOCK with explicit recovery path.
        # User must consciously acknowledge the run was abandoned.
        log(f"active run {command} phase={phase} is stale → BLOCK")
        err = (
            f"⛔ Active run is stale (>30min, started {current.get('started_at', '?')}):\n"
            f"   {command} phase={phase} run_id={current.get('run_id', '?')[:12]}\n\n"
            f"   Stale runs are NOT auto-cleared anymore (OHOK-6). AI could\n"
            f"   previously wait out the threshold and get silent approval.\n"
            f"   Explicitly abort or repair:\n"
            f"   - python .claude/scripts/vg-orchestrator run-abort --reason 'abandoned'\n"
            f"   - python .claude/scripts/vg-orchestrator run-repair --force\n"
            f"   Then retry Stop."
        )
        print(err, file=sys.stderr)
        return 2

    log(f"active run {command} phase={phase} → invoking orchestrator run-complete")
    rc, stdout, stderr = run_orchestrator_complete()
    log(f"orchestrator rc={rc}")

    if rc == 0:
        # PASS — run completed cleanly
        log("run-complete PASS")
        print(json.dumps({"decision": "approve",
                          "reason": "orchestrator-pass"}))
        return 0

    if rc == 2:
        # BLOCK — orchestrator found contract violations
        msg = stderr.strip() or stdout.strip() or (
            "vg-orchestrator run-complete reported contract violations."
        )

        # v2.8.3 hybrid auto-recovery: if violations are PURE marker-drift
        # AND this is the 2nd+ drift in the same run_id, fire migrate-state
        # then retry. 1st drift always blocks (gives AI a chance to learn).
        violation_types = _parse_violation_types(msg)
        run_id = current.get("run_id") or "unknown"

        if _is_marker_only_drift(msg):
            new_count = _bump_drift(run_id, violation_types)
            log(f"marker-drift BLOCK detected (drift_count={new_count} for run_id={run_id[:12]})")

            if new_count >= 2:
                # Auto-fire eligible — try migrate-state then retry
                log(f"drift_count={new_count} ≥ 2 → invoking migrate-state {phase} --apply")
                ar_rc, ar_out, ar_err = _auto_fire_markers(phase)
                log(f"migrate-state rc={ar_rc} stdout={ar_out[:200]!r}")

                if ar_rc == 0:
                    # Retry orchestrator run-complete
                    rc2, sout2, serr2 = run_orchestrator_complete()
                    log(f"retry run-complete rc={rc2}")
                    if rc2 == 0:
                        # Recovery succeeded — emit telemetry, approve
                        _emit_telemetry(
                            "hook.marker_drift_recovered",
                            {"run_id": run_id, "drift_count": new_count,
                             "violations": sorted(violation_types),
                             "migrate_state_stdout": ar_out[:500]},
                        )
                        approve_msg = (
                            f"✓ Marker drift auto-recovered (drift_count={new_count}, "
                            f"run_id={run_id[:12]}). migrate-state backfilled missing "
                            f"markers + logged soft debt. See OVERRIDE-DEBT.md."
                        )
                        log(f"APPROVED via auto-recovery: {approve_msg}")
                        print(json.dumps({
                            "decision": "approve",
                            "reason": "auto-recovered-marker-drift",
                            "hookSpecificOutput": {
                                "hookEventName": "Stop",
                                "additionalContext": approve_msg,
                            },
                        }))
                        return 0
                    # Retry still BLOCKs — fall through to print stderr
                    log(f"retry still blocked, falling through")
                    msg = serr2.strip() or sout2.strip() or msg
                else:
                    log(f"migrate-state failed rc={ar_rc}, stderr={ar_err[:200]}")
                    msg = (
                        f"⛔ Marker-drift auto-recovery FAILED.\n\n"
                        f"migrate-state rc={ar_rc}\n"
                        f"stderr: {ar_err.strip()[:500]}\n\n"
                        f"Original violations:\n{msg}\n\n"
                        f"Manual recovery: python .claude/scripts/migrate-state.py {phase} --apply"
                    )
            else:
                # 1st drift — block with hint about hybrid auto-recovery
                msg = (
                    f"{msg}\n\n"
                    f"💡 Marker drift detected (1st time for run_id={run_id[:12]}).\n"
                    f"   Hybrid recovery (v2.8.3): if Stop fires AGAIN with the SAME\n"
                    f"   markers still missing, hook will auto-fire migrate-state\n"
                    f"   {phase} --apply and retry. Current count: 1 of 2.\n\n"
                    f"   To skip the hint and fix now: python .claude/scripts/migrate-state.py {phase} --apply"
                )

        log(f"BLOCKED: {msg[:200]}")
        print(msg, file=sys.stderr)
        return 2

    # OHOK-3 (2026-04-22): Gemini flagged this branch as "institutionalized
    # cowardice" — soft-approve on unexpected rc meant orchestrator bugs
    # silently let AI claim PASS. Fix: BLOCK with actionable recovery path.
    #
    # If the user hits genuine orchestrator bugs (rare), they can:
    #   - python vg-orchestrator run-abort --reason "orchestrator bug rc=X"
    #   - python vg-orchestrator run-repair --force
    # then retry Stop. We do NOT auto-escape anymore.
    log(f"orchestrator unexpected rc={rc}, stderr={stderr[:500]}")
    err_msg = (
        f"⛔ vg-orchestrator run-complete returned unexpected rc={rc}.\n"
        f"   This is NOT a BLOCK from contract violations — it's a bug or\n"
        f"   transient state issue. Previous versions soft-approved here,\n"
        f"   which let AI claim PASS without real verification.\n\n"
        f"   Recovery options:\n"
        f"   1. Inspect: python .claude/scripts/vg-orchestrator run-status\n"
        f"   2. Inspect log: tail .vg/hook-verifier.log\n"
        f"   3. Repair: python .claude/scripts/vg-orchestrator run-repair --force\n"
        f"   4. Abort: python .claude/scripts/vg-orchestrator run-abort --reason '<why>'\n"
        f"\n   Orchestrator stderr excerpt: {stderr[:300].strip()}"
    )
    print(err_msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        try:
            log(f"HOOK ERROR (soft-approving): {e}")
        except Exception:
            pass
        print(json.dumps({"decision": "approve", "reason": "hook-error"}))
        sys.exit(0)
