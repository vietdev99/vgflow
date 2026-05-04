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
ACTIVE_RUNS_DIR = REPO_ROOT / ".vg" / "active-runs"  # v2.28.0 per-session
SESSION_CONTEXT = REPO_ROOT / ".vg" / ".session-context.json"
HOOK_LOG = REPO_ROOT / ".vg" / "hook-verifier.log"
ORCHESTRATOR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
SESSION_DRIFT = REPO_ROOT / ".vg" / ".session-drift.json"
MIGRATE_STATE = REPO_ROOT / ".claude" / "scripts" / "migrate-state.py"
EVENTS_DB = REPO_ROOT / ".vg" / "events.db"
STALE_MINUTES = 30
DRIFT_STATE_TTL_MINUTES = 120  # GC stale entries after this

# Hotfix 2026-05-04: interactive commands span hours by design (user reads
# diagnostic + fixes + retries between AskUserQuestion turns). Bump to 6h
# so live debug/amend/scope/accept sessions don't get falsely stale-blocked.
INTERACTIVE_CMDS = {"vg:debug", "vg:amend", "vg:scope", "vg:accept"}
INTERACTIVE_STALE_MINUTES = 360


def _stale_threshold_for(command: str | None) -> int:
    if command and command in INTERACTIVE_CMDS:
        return INTERACTIVE_STALE_MINUTES
    return STALE_MINUTES

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


def _safe_session_filename(sid: str) -> str:
    if not sid:
        return "unknown"
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")
    return safe or "unknown"


def read_current_run(hook_session: str | None = None) -> dict | None:
    """v2.28.0: read per-session active run when hook_session is known.

    Resolution:
      1. .vg/active-runs/{hook_session}.json — owns THIS session's state
      2. Legacy .vg/current-run.json — fallback for pre-v2.28.0 install OR
         when no per-session file exists for this session yet.
      3. None.

    Returning the per-session file means a Stop hook fired in session A
    will check session A's run, never session B's. The cross-session
    branch in main() then becomes a defensive backstop rather than the
    primary safety net.
    """
    if hook_session:
        per_session = ACTIVE_RUNS_DIR / f"{_safe_session_filename(hook_session)}.json"
        if per_session.exists():
            try:
                return json.loads(per_session.read_text(encoding="utf-8"))
            except Exception as e:
                log(f"per-session active-run parse error: {e}")
                # fall through to legacy

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
        # PRE-EXISTING BUG (any version): used to be
        #   ts = datetime.datetime.fromisoformat(started.rstrip("Z"))
        # which produces a NAIVE datetime, then `datetime.now(tz=utc) - ts`
        # raised TypeError: "can't subtract offset-naive and offset-aware
        # datetimes". The except branch returned True → is_stale() was
        # ALWAYS True regardless of actual age. Result: Stop hook BLOCKED
        # on every active run with the "stale" message even on fresh runs.
        # This compounded #32 because cross-session detection couldn't
        # distinguish stale vs fresh either.
        # Fix: convert Z → +00:00 then add UTC tz if parser still returned
        # naive, so subtraction works on aware-aware as intended.
        if started.endswith("Z"):
            started = started[:-1] + "+00:00"
        ts = datetime.datetime.fromisoformat(started)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        age_min = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds() / 60
        return age_min > _stale_threshold_for(run.get("command"))
    except Exception:
        return True


def get_run_session_id(run: dict) -> str | None:
    """Read session_id for the active run.

    Issue #32: prior Stop hook treated all active runs as belonging to the
    current session, so a crashed Session A run blocked Session B even on
    completely unrelated phases. Read session_id from current-run.json
    first; fall back to best-effort sqlite lookup by run_id. Returns None
    if neither source has it (cannot differentiate — preserve legacy block).
    """
    sid = run.get("session_id")
    if sid:
        return sid
    run_id = run.get("run_id")
    if not run_id:
        return None
    try:
        import sqlite3
        db_path = REPO_ROOT / ".vg" / "events.db"
        if not db_path.exists():
            return None
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        try:
            row = conn.execute(
                "SELECT session_id FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return row[0] if row and row[0] else None
        finally:
            conn.close()
    except Exception:
        return None


def _read_json_file(path: Path) -> dict | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def _codex_session_context_owns_run(run: dict) -> bool:
    """True when Codex hook session differs but session-context still owns run."""
    if os.environ.get("VG_RUNTIME") != "codex":
        return False

    ctx = _read_json_file(SESSION_CONTEXT)
    if not ctx:
        return False

    run_id = run.get("run_id")
    if not run_id or ctx.get("run_id") != run_id:
        return False

    run_session = get_run_session_id(run)
    ctx_session = ctx.get("session_id")
    if run_session and ctx_session and run_session != ctx_session:
        return False

    for key in ("command", "phase"):
        ctx_value = ctx.get(key)
        run_value = run.get(key)
        if ctx_value and run_value and str(ctx_value) != str(run_value):
            return False

    return True

def auto_abort_run(reason: str, session_id: str | None = None) -> None:
    """Best-effort run-abort via orchestrator. Never raises.

    v2.28.0: pass session_id via env so orchestrator clears the right
    per-session active-run file (not the legacy snapshot mirror).
    """
    try:
        env = os.environ.copy()
        if session_id:
            env["CLAUDE_SESSION_ID"] = session_id
        subprocess.run(
            [sys.executable, str(ORCHESTRATOR), "run-abort",
             "--reason", reason],
            capture_output=True, text=True, timeout=15,
            env=env,
        )
    except Exception as e:
        log(f"auto_abort_run failed: {e}")


def run_orchestrator_complete(session_id: str | None = None) -> tuple[int, str, str]:
    """Invoke vg-orchestrator run-complete. Returns (exit_code, stdout, stderr).

    v2.28.0: explicitly pass CLAUDE_SESSION_ID via env so the orchestrator
    routes state.read_active_run() to THIS session's per-session file.
    Claude Code passes session_id only via stdin hook_input — the env var
    is not always set for hook subprocesses, so we propagate it manually.
    """
    python_bin = sys.executable or "python"
    env = os.environ.copy()
    if session_id:
        env["CLAUDE_SESSION_ID"] = session_id
    proc = subprocess.run(
        [python_bin, str(ORCHESTRATOR), "run-complete"],
        capture_output=True, text=True, timeout=30,
        env=env,
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
            if last.endswith("Z"):
                last = last[:-1] + "+00:00"
            ts = datetime.datetime.fromisoformat(last)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
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


def _emit_telemetry(event_type: str, payload: dict, session_id: str | None = None) -> None:
    """Best-effort telemetry emission via vg-orchestrator emit-event.
    Phase + command auto-resolved from current-run.json by orchestrator.
    Never blocks hook on failure. event_type MUST NOT be reserved (run.*,
    validation.*, wave.*, build.crossai_*, override.*, debt_register.*,
    step.marked) — use a hook.* prefix to avoid forgery-detector trips.

    v2.28.0: propagate session_id env so orchestrator routes to the right
    per-session active-run for phase/command resolution.
    """
    try:
        python_bin = sys.executable or "python"
        env = os.environ.copy()
        if session_id:
            env["CLAUDE_SESSION_ID"] = session_id
        subprocess.run(
            [python_bin, str(ORCHESTRATOR), "emit-event",
             event_type,  # positional
             "--actor", "hook",
             "--outcome", "INFO",
             "--payload", json.dumps(payload)],
            capture_output=True, text=True, timeout=10,
            env=env,
        )
    except Exception as e:
        log(f"telemetry emit failed for {event_type}: {e}")


def _auto_fire_markers(phase: str, session_id: str | None = None) -> tuple[int, str, str]:
    """Invoke migrate-state.py {phase} --apply. Returns (rc, stdout, stderr).
    The script is idempotent: if drift was already resolved (e.g. by a
    parallel run), it returns rc=0 with 'no drift' in stdout.
    """
    if not MIGRATE_STATE.exists():
        return (127, "", f"migrate-state.py not found at {MIGRATE_STATE}")
    python_bin = sys.executable or "python"
    env = os.environ.copy()
    if session_id:
        env["CLAUDE_SESSION_ID"] = session_id
    proc = subprocess.run(
        [python_bin, str(MIGRATE_STATE), phase, "--apply"],
        capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT),
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ─── Modern BLOCK format (orange title + block file + vg.block.fired) ────


def _emit_stale_block(current: dict, session_id: str | None) -> None:
    """Render stale-run BLOCK using the modern 3-line stderr + block-file
    + vg.block.fired pattern (parity with vg-pre-tool-use-bash.sh emit_block).

    Replaces the legacy bare-text format which had no ANSI color, no
    diagnostic event, and no Layer-4 narration template — those are
    contract requirements for any hook BLOCK now (see vg-meta-skill.md
    and `Hook authoring rule — VG context guard`).
    """
    gate_id = "Stop-stale-run"
    run_id = current.get("run_id") or "unknown"
    command = current.get("command", "?")
    phase = current.get("phase", "?")
    started = current.get("started_at", "?")
    cause = (
        f"active run {command} phase={phase} started_at={started} "
        f"exceeds STALE_MINUTES={STALE_MINUTES}"
    )

    block_dir = REPO_ROOT / ".vg" / "blocks" / run_id
    block_file = block_dir / f"{gate_id}.md"
    try:
        block_dir.mkdir(parents=True, exist_ok=True)
        block_file.write_text(
            f"""# Block diagnostic — {gate_id}

## Cause
{cause}

## Required fix
Stale runs are NOT auto-cleared (OHOK-6). AI could previously wait out
the {STALE_MINUTES}-minute threshold and get silent Stop approval —
that escape hatch is closed. Pick ONE recovery path:

1. **Abandon the run** (most common):
   ```
   python .claude/scripts/vg-orchestrator run-abort --reason "abandoned >{STALE_MINUTES}min idle"
   ```

2. **Force-repair** (use only if you know the run actually completed
   but state file is out of sync):
   ```
   python .claude/scripts/vg-orchestrator run-repair --force
   ```

Then retry Stop. Hook will re-evaluate against current state.

## Narration template (use session language)
[VG diagnostic] Run /{command} phase {phase} đã chạy quá {STALE_MINUTES}p
(started_at={started}). Đang abort run cũ trước khi tiếp tục.

## After fix
```
vg-orchestrator emit-event vg.block.handled \\
  --gate {gate_id} \\
  --resolution "stale run aborted/repaired, Stop retried"
```

If this gate blocks ≥3 times in this session, MUST call AskUserQuestion —
something is preventing run-abort/run-repair from succeeding.
""",
            encoding="utf-8",
        )
    except Exception as e:
        log(f"failed to write block file {block_file}: {e}")

    # Compact 3-line stderr (orange title) — parity with vg-pre-tool-use-bash.sh.
    sys.stderr.write(
        f"\033[38;5;208m{gate_id}: {cause}\033[0m\n"
        f"→ Read {block_file} for fix\n"
        f"→ After fix: vg-orchestrator emit-event vg.block.handled --gate {gate_id}\n"
    )

    # Emit vg.block.fired so Stop hook's diagnostic-pairing gate sees it.
    try:
        env = os.environ.copy()
        if session_id:
            env["CLAUDE_SESSION_ID"] = session_id
        subprocess.run(
            [sys.executable, str(ORCHESTRATOR), "emit-event",
             "vg.block.fired",
             "--actor", "hook",
             "--outcome", "FAIL",
             "--payload", json.dumps({
                 "gate": gate_id,
                 "cause": cause,
                 "run_id": run_id,
                 "command": command,
                 "phase": phase,
                 "block_file": str(block_file),
             })],
            capture_output=True, text=True, timeout=10,
            env=env,
        )
    except Exception as e:
        log(f"vg.block.fired emit failed for {gate_id}: {e}")


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

    current = read_current_run(session_id if session_id and session_id != "?" else None)
    if not current:
        log("no current-run.json — nothing to verify, approve")
        print(json.dumps({"decision": "approve",
                          "reason": "no-active-run"}))
        return 0

    command = current.get("command", "?")
    phase = current.get("phase", "?")

    # Issue #32: cross-session zombie detection. If active run was started
    # by a DIFFERENT Claude Code session than the one firing this Stop
    # hook, current session has no business validating that run's
    # contract. Two sub-cases:
    #   - Stale cross-session zombie → auto-abort (best-effort) + approve
    #   - Fresh cross-session run → don't touch (might be parallel work) +
    #     approve current Stop without validating
    # Only differentiate when we can identify both sessions. If either is
    # unknown (legacy install, env var missing), fall through to existing
    # OHOK-6 stale-block behavior to preserve security.
    run_session = get_run_session_id(current)
    hook_session = session_id if session_id and session_id != "?" else None
    cross_session = bool(
        run_session and hook_session and run_session != hook_session
    )

    # OHOK-9 fix (2026-05-02): when run was registered without session_id
    # (orchestrator bug — env var CLAUDE_SESSION_ID missing at run-start)
    # AND current hook session is known, the run is ORPHAN — it cannot
    # belong to this session because this session has its own session_id.
    # Previously this case fell through to "is_stale → BLOCK" which trapped
    # parallel sessions on infinite stop-hook loops while another session
    # was actively running the skill.
    #
    # Treatment: same as cross-session — fresh orphan = leave alone +
    # approve; stale orphan = auto-abort + approve.
    orphan_run = bool(
        not run_session and hook_session and current.get("run_id")
    )

    if cross_session or orphan_run:
        run_id = current.get("run_id", "?")
        kind = "cross-session" if cross_session else "orphan-null-session"
        owner_label = (run_session[:12] if run_session else "<null>")
        if _codex_session_context_owns_run(current):
            log(f"{kind} Codex context-owned run {command} phase={phase} "
                f"owner={owner_label}; approve without touching")
            print(json.dumps({
                "decision": "approve",
                "reason": f"{kind}-codex-context-owned-no-action",
                "other_session_run": run_id[:12] if run_id else "?",
            }))
            return 0
        if is_stale(current):
            log(f"{kind} stale {command} phase={phase} "
                f"owner={owner_label}; auto-abort + approve")
            auto_abort_run(
                f"{kind}-auto-abort: run owner session={owner_label}, "
                f"current session={hook_session[:12] if hook_session else '?'}",
                session_id=run_session,
            )
            print(json.dumps({
                "decision": "approve",
                "reason": f"{kind}-stale-cleared",
                "aborted_run": run_id[:12] if run_id else "?",
            }))
            return 0
        # Fresh orphan/cross-session — don't touch, approve this Stop.
        # Either the other session is still working, OR a recent run-start
        # without session_id is in flight; let it complete naturally.
        log(f"{kind} fresh run {command} phase={phase} "
            f"owner={owner_label}; approve without touching")
        print(json.dumps({
            "decision": "approve",
            "reason": f"{kind}-fresh-no-action",
            "other_session_run": run_id[:12] if run_id else "?",
        }))
        return 0


    if is_stale(current):
        # OHOK-6 (Gemini P1): previously auto-cleared + approved. That was
        # a time-based escape hatch — AI could idle >STALE_MINUTES then
        # call Stop to bypass all gates. Now BLOCK with explicit recovery.
        # User must consciously acknowledge the run was abandoned.
        #
        # Format modernization (2026-05-03): use _emit_stale_block helper
        # for parity with the rest of the VG block surface (orange ANSI +
        # .vg/blocks/{run_id}/Stop-stale-run.md + vg.block.fired event).
        # The bare-text legacy form lacked all three, breaking Layer-4
        # diagnostic pairing + UX color cues.
        log(f"active run {command} phase={phase} is stale → BLOCK")
        _emit_stale_block(current, session_id if session_id and session_id != "?" else None)
        return 2

    log(f"active run {command} phase={phase} → invoking orchestrator run-complete")
    rc, stdout, stderr = run_orchestrator_complete(session_id=session_id)
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
                ar_rc, ar_out, ar_err = _auto_fire_markers(phase, session_id=session_id)
                log(f"migrate-state rc={ar_rc} stdout={ar_out[:200]!r}")

                if ar_rc == 0:
                    # Retry orchestrator run-complete
                    rc2, sout2, serr2 = run_orchestrator_complete(session_id=session_id)
                    log(f"retry run-complete rc={rc2}")
                    if rc2 == 0:
                        # Recovery succeeded — emit telemetry, approve
                        _emit_telemetry(
                            "hook.marker_drift_recovered",
                            {"run_id": run_id, "drift_count": new_count,
                             "violations": sorted(violation_types),
                             "migrate_state_stdout": ar_out[:500]},
                            session_id=session_id,
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
                        f"\033[38;5;208mMarker-drift auto-recovery FAILED.\033[0m\n\n"
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

        # v2.46-wave3 — autonomous recovery loop: try auto_executable paths
        # before giving up to user. Closes "BLOCK = stop" anti-pattern.
        # Only safe paths run (override flags + log debt). NEVER runs
        # token-expensive --retry-failed or destructive code/data edits.
        recovery_script = REPO_ROOT / ".claude" / "scripts" / "vg-recovery.py"
        if recovery_script.exists():
            log(f"v2.46-wave3 auto-recovery: attempting auto_executable paths for run_id={run_id[:12]}")
            try:
                ar = subprocess.run(
                    [sys.executable, str(recovery_script), "--phase", phase, "--auto", "--json"],
                    capture_output=True, text=True, timeout=120,
                )
                log(f"auto-recovery rc={ar.returncode} stdout={ar.stdout[:300]!r}")
                if ar.returncode == 0:
                    # Auto-recovery success → retry run-complete
                    rc3, sout3, serr3 = run_orchestrator_complete(session_id=session_id)
                    log(f"post-auto-recovery run-complete rc={rc3}")
                    if rc3 == 0:
                        _emit_telemetry(
                            "hook.auto_recovery_succeeded",
                            {"run_id": run_id, "violations": sorted(violation_types)},
                            session_id=session_id,
                        )
                        approve_msg = (
                            f"✓ Auto-recovery succeeded (run_id={run_id[:12]}). "
                            f"Override flags applied; debt logged to OVERRIDE-DEBT.md. "
                            f"Review with /vg:doctor recovery for details."
                        )
                        log(f"APPROVED via auto-recovery: {approve_msg}")
                        print(json.dumps({
                            "decision": "approve",
                            "reason": "auto-recovered-via-recovery-paths",
                            "hookSpecificOutput": {
                                "hookEventName": "Stop",
                                "additionalContext": approve_msg,
                            },
                        }))
                        return 0
                    # Recovery ran but BLOCK still fires → fall through with new msg
                    msg = serr3.strip() or sout3.strip() or msg
                    log(f"auto-recovery insufficient — still BLOCKED, surfacing to user")
                else:
                    log(f"auto-recovery couldn't fully resolve (rc={ar.returncode}); falling through")
            except subprocess.TimeoutExpired:
                log("auto-recovery timeout 120s — falling through")
            except Exception as e:
                log(f"auto-recovery error: {e}")

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
        f"\033[38;5;208mvg-orchestrator run-complete returned unexpected rc={rc}.\033[0m\n"
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
