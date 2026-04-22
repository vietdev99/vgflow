"""
vg-orchestrator CLI dispatcher.

Entry point for ALL /vg:* pipeline transitions. Skill-MD bash blocks call
subcommands here; AI cannot legitimately advance pipeline state without
going through this binary.

Subcommands:
  run-start <command> <phase> [args...]
  run-status
  run-complete [outcome]
  run-abort --reason <text>
  run-resume
  run-repair [--force]
  emit-event <event_type> [--payload JSON]
  mark-step <namespace> <step_name>
  wave-start <wave_n>
  wave-complete <wave_n> < evidence.json   (reads stdin or --evidence-file)
  validate <validator_name> [args...]
  verify-hash-chain [--since-id N]
  query-events [--phase X] [--event-type Y] [--run-id Z]
  override --flag <f> --reason <text>

Exit codes:
  0 = success
  1 = validation/state error (AI should read stderr + retry)
  2 = hook-blocking (forces Claude Code Stop to block)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Ensure package-relative imports work when run via `python -m vg_orchestrator`
# or `python .claude/scripts/vg-orchestrator/__main__.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402
import contracts  # noqa: E402
import state as state_mod  # noqa: E402
import evidence  # noqa: E402


def _git_sha() -> str | None:
    import subprocess
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


_RUN_STALE_MINUTES = 30


def _is_run_stale(active: dict) -> bool:
    """True if active run is old enough to be considered abandoned.
    Matches Stop hook's STALE_MINUTES so the two layers stay consistent.
    """
    started = active.get("started_at", "")
    if not started:
        return True
    try:
        ts = datetime.fromisoformat(started.rstrip("Z"))
        age_min = (datetime.utcnow() - ts).total_seconds() / 60
        return age_min > _RUN_STALE_MINUTES
    except Exception:
        return True


def cmd_run_start(args) -> int:
    """Write runs row + emit run.started. Return run_id on stdout."""
    active = state_mod.read_current_run()
    if active:
        # OHOK-4 (2026-04-22): previously blocked forever if prior run crashed
        # without run-complete — user had to manually rm current-run.json.
        # Now: auto-clear stale (>30min) runs + warn, block fresh ones.
        if _is_run_stale(active):
            age_note = f"stale (>{_RUN_STALE_MINUTES}min)"
            print(
                f"⚠ Clearing {age_note} run: {active.get('command')} "
                f"phase={active.get('phase')} started {active.get('started_at', '?')}.\n"
                f"   Orphaned run likely from crashed session. If this was\n"
                f"   intentional, run-abort it first to preserve audit trail.",
                file=sys.stderr,
            )
            # Emit event so events.db reflects the takeover
            try:
                db.append_event(
                    run_id=active.get("run_id", "unknown"),
                    event_type="run.stale_cleared",
                    phase=active.get("phase", ""),
                    command=active.get("command", ""),
                    actor="orchestrator",
                    outcome="INFO",
                    payload={"reason": "stale_at_run_start",
                             "age_minutes_threshold": _RUN_STALE_MINUTES,
                             "new_command": args.command,
                             "new_phase": args.phase},
                )
            except Exception:
                pass
            state_mod.clear_current_run()
            # Continue to fresh run-start below
        else:
            print(f"⛔ Active run exists: {active.get('command')} "
                  f"phase={active.get('phase')} started "
                  f"{active.get('started_at', '?')} (<{_RUN_STALE_MINUTES}min old).\n"
                  f"   Options:\n"
                  f"   1. Complete it: python vg-orchestrator run-complete\n"
                  f"   2. Abort: python vg-orchestrator run-abort --reason '<why>'\n"
                  f"   3. Wait >{_RUN_STALE_MINUTES}min — it will auto-clear",
                  file=sys.stderr)
            return 1

    session_id = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID")
    extra_str = " ".join(args.extra) if isinstance(args.extra, list) else (args.extra or "")

    # OHOK v2 Day 2 — reject --override-reason < 50 chars or obvious placeholders.
    # Prior state: 4-char reason like "foo" was accepted → Codex audit flagged
    # override-abuse vector (4-char reason normalizing to blanket skip). Now:
    # reason MUST be concrete, minimum 50 chars, not match common placeholder
    # patterns. Also emit override.proposed event so skill-level caller MUST
    # invoke rationalization-guard before proceeding.
    import re as _re

    # Parse REMAINDER list directly — args.extra is a list when nargs=REMAINDER.
    # Shell already tokenized; we must concat everything between --override-reason
    # and the next --flag (or EOL) to reconstruct quoted multi-word values.
    override_flag = None  # the flag being justified (e.g. --skip-goal-coverage)
    override_reason_val = None
    extra_list = args.extra if isinstance(args.extra, list) else []
    i = 0
    while i < len(extra_list):
        tok = extra_list[i]
        if tok == "--override-reason":
            # Consume tokens until next flag or EOL
            val_tokens = []
            j = i + 1
            while j < len(extra_list) and not extra_list[j].startswith("--"):
                val_tokens.append(extra_list[j])
                j += 1
            override_reason_val = " ".join(val_tokens).strip()
            i = j
            continue
        if tok.startswith("--override-reason="):
            override_reason_val = tok.split("=", 1)[1].strip()
            i += 1
            continue
        i += 1

    # Identify which flag is being overridden (first --skip-*/--allow-* before reason)
    for t in extra_list:
        if t.startswith("--skip-") or t.startswith("--allow-"):
            override_flag = t
            break

    override_match = override_reason_val is not None
    if override_match:
        reason = override_reason_val or ""
        if len(reason) < 50:
            print(f"⛔ --override-reason too short ({len(reason)} chars, min 50).\n"
                  f"   Got: {reason!r}\n"
                  f"   Overrides must cite concrete evidence: ticket/issue URL, "
                  f"failing test name, infra blocker, etc. Placeholder reasons "
                  f"normalize into blanket skips.",
                  file=sys.stderr)
            return 2

        # Reject common placeholder patterns (case-insensitive)
        placeholders = [
            r"^(test|tbd|fixme|fix ?later|todo|temp|temporary)\b",
            r"^(quick|small|minor|trivial) ?(fix|patch|change)",
            r"^(need|will|should|might) ?(to )?(fix|check|verify)",
            r"^skip(ping)? for now",
            r"^not( a)? blocker",
        ]
        for pat in placeholders:
            if _re.search(pat, reason, _re.IGNORECASE):
                print(f"⛔ --override-reason matches placeholder pattern: {pat!r}\n"
                      f"   Got: {reason!r}\n"
                      f"   Cite concrete evidence: issue URL, test name, CI run ID, etc.",
                      file=sys.stderr)
                return 2
    run_id = db.create_run(
        command=args.command,
        phase=args.phase,
        args=extra_str,
        session_id=session_id,
        git_sha=_git_sha(),
    )

    state_mod.write_current_run({
        "run_id": run_id,
        "command": args.command,
        "phase": args.phase,
        "args": extra_str,
        "started_at": _now_iso(),
    })

    db.append_event(
        run_id=run_id,
        event_type="run.started",
        phase=args.phase,
        command=args.command,
        actor="orchestrator",
        outcome="INFO",
        payload={"args": extra_str, "git_sha": _git_sha()},
    )
    # Also emit {cmd}.started for backward compat with contract declarations
    short_cmd = args.command.replace("vg:", "")
    db.append_event(
        run_id=run_id,
        event_type=f"{short_cmd}.started",
        phase=args.phase,
        command=args.command,
        actor="orchestrator",
        outcome="INFO",
        payload={},
    )

    # OHOK v2 Day 2 — if override-reason was approved (passed length + placeholder
    # checks above), emit override.proposed so skill-level caller can invoke
    # rationalization-guard + log override-debt atomically. Skill must call
    # vg-orchestrator override <flag> <reason> to close the loop.
    if override_match:
        db.append_event(
            run_id=run_id,
            event_type="override.proposed",
            phase=args.phase,
            command=args.command,
            actor="orchestrator",
            outcome="INFO",
            payload={"flag": override_flag or "(unknown-flag)",
                     "reason": (override_reason_val or "")[:200],
                     "requires_guard": True},
        )

    print(run_id)
    return 0


def cmd_run_status(_args) -> int:
    current = state_mod.read_current_run()
    if not current:
        print("no-active-run")
        return 0
    run = db.get_run(current["run_id"])
    print(json.dumps({"current_run": current, "run_row": run}, indent=2,
                     default=str))
    return 0


def cmd_run_complete(args) -> int:
    """Verify runtime_contract evidence, emit completion event, clear current-run."""
    current = state_mod.read_current_run()
    if not current:
        print("⛔ No active run to complete.", file=sys.stderr)
        return 1

    run_id = current["run_id"]
    command = current["command"]
    phase = current["phase"]
    run_args = current.get("args", "")

    contract = contracts.parse(command)
    verdict, violations = _verify_contract(contract, run_id, command, phase,
                                           run_args)

    outcome = "PASS" if verdict else args.outcome or "BLOCK"
    # {cmd}.completed must be emitted BY THE SKILL before run-complete so we
    # can verify it here. Orchestrator emits only run.completed/run.blocked.
    db.append_event(
        run_id=run_id,
        event_type="run.completed" if verdict else "run.blocked",
        phase=phase,
        command=command,
        actor="orchestrator",
        outcome=outcome,
        payload={"violations": violations} if violations else {},
    )

    # Outcome attribution — any bootstrap.rule_fired events from this run
    # inherit the run verdict. This closes the learning loop that was dead
    # in v1 (success_count / fail_count stayed 0 forever because nobody
    # emitted bootstrap.outcome_recorded).
    _record_rule_outcomes(run_id, command, phase, verdict)

    if verdict:
        db.complete_run(run_id, outcome="PASS")
        state_mod.clear_current_run()
        print(f"✓ {command} phase={phase} PASS")
        return 0

    # Verdict failed — keep current_run so user/AI can inspect + retry
    print(_format_block_message(command, phase, violations), file=sys.stderr)
    return 2


def cmd_run_abort(args) -> int:
    current = state_mod.read_current_run()
    if not current:
        print("no-active-run")
        return 0
    db.append_event(
        run_id=current["run_id"],
        event_type="run.aborted",
        phase=current["phase"],
        command=current["command"],
        actor="user",
        outcome="INFO",
        payload={"reason": args.reason},
    )
    db.complete_run(current["run_id"], outcome="ABORTED")
    state_mod.clear_current_run()
    print(f"aborted: {args.reason}")
    return 0


# OHOK-8 (2026-04-22, CrossAI round 3): prevent forgery of system-emitted
# events via the CLI. Skills need emit-event for their own signaling (step
# markers, custom signals) but MUST NOT be able to forge gate-relevant
# events that validators trust.
#
# Any event type matching these prefixes can ONLY be emitted from inside
# orchestrator core code (which calls db.append_event() directly with
# actor="orchestrator"). CLI emission with these prefixes is rejected.
#
# The exception: validator-internal emissions (e.g. validation.passed/blocked)
# already bypass this path because validators invoke db.append_event directly
# via _run_validators.
RESERVED_EVENT_PREFIXES = (
    "run.",                   # run.started, run.completed, run.aborted, etc.
    "validation.",            # validation.passed / .failed / .blocked / .warned
    "wave.",                  # wave.started, wave.completed
    "build.crossai_",         # iteration_started, iteration_complete, loop_*
    "goal.promoted_manual",   # manual promotions — must go through cmd
    "override.",              # override.proposed, .used, .resolved
    "debt_register.",         # debt_register.write_failed (orchestrator-only)
)
RESERVED_EVENT_EXACT = {
    "step.marked",            # step markers — must use mark-step command
}


def _is_reserved_event(event_type: str) -> bool:
    if event_type in RESERVED_EVENT_EXACT:
        return True
    return any(event_type.startswith(p) for p in RESERVED_EVENT_PREFIXES)


def cmd_emit_event(args) -> int:
    current = state_mod.read_current_run()
    if not current:
        print("⛔ No active run. Call run-start first.", file=sys.stderr)
        return 1

    # OHOK-8: block forgery of gate-relevant event types via CLI
    if _is_reserved_event(args.event_type):
        print(
            f"⛔ Event type '{args.event_type}' is RESERVED for orchestrator "
            f"core — cannot be emitted via CLI.\n"
            f"   Reserved prefixes: {', '.join(RESERVED_EVENT_PREFIXES)}\n"
            f"   Reserved exact: {', '.join(sorted(RESERVED_EVENT_EXACT))}\n\n"
            f"   Rationale (OHOK-8 round-3): CrossAI reviewers found that\n"
            f"   AI could forge terminal events like build.crossai_loop_complete\n"
            f"   via `emit-event` CLI → bypass validators that count events.\n"
            f"   These events must come from the actual code paths (run-start/\n"
            f"   run-complete/wave-complete/vg-build-crossai-loop.py etc.).\n\n"
            f"   If you need a custom skill signal, use a non-reserved\n"
            f"   namespace like `skill.<name>.custom_event` or similar.",
            file=sys.stderr,
        )
        return 2

    payload = {}
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as e:
            print(f"⛔ Invalid payload JSON: {e}", file=sys.stderr)
            return 1

    evt = db.append_event(
        run_id=current["run_id"],
        event_type=args.event_type,
        phase=current["phase"],
        command=current["command"],
        actor=args.actor,
        outcome=args.outcome,
        step=args.step,
        payload=payload,
    )
    print(evt["this_hash"][:16])
    return 0


def cmd_emit_crossai_terminal(args) -> int:
    """OHOK-8: dedicated path for emitting loop_exhausted / loop_user_override.
    Bypasses cmd_emit_event's reserved-type block because this subcommand is
    itself the controlled path.

    For `exhausted`: verifies that iteration count already reached max_iterations.
    For `user_override`: verifies a recent override.used event with crossai flag
    exists in this run (→ guarantees the HARD debt was logged first).
    """
    current = state_mod.read_current_run()
    if not current:
        print("⛔ No active run", file=sys.stderr)
        return 1
    if current["command"] != "vg:build":
        print(f"⛔ emit-crossai-terminal only valid in vg:build run, "
              f"got {current['command']}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as e:
        print(f"⛔ Invalid payload JSON: {e}", file=sys.stderr)
        return 1

    run_id = current["run_id"]

    # Sanity: verify pre-condition per kind
    import sqlite3
    conn = sqlite3.connect(str(Path(os.environ.get("VG_REPO_ROOT")
                                     or os.getcwd()) / ".vg" / "events.db"))
    try:
        if args.kind == "exhausted":
            r = conn.execute(
                "SELECT COUNT(*) FROM events WHERE run_id = ? "
                "AND event_type = 'build.crossai_iteration_started'",
                (run_id,),
            ).fetchone()
            iter_count = r[0] or 0
            max_iter = int(payload.get("max_iterations", 5))
            if iter_count < max_iter:
                print(
                    f"⛔ Cannot declare exhausted — only {iter_count}/{max_iter} "
                    f"iterations started. Run more iterations or adjust "
                    f"max_iterations in the loop invocation.",
                    file=sys.stderr,
                )
                return 2
            event_type = "build.crossai_loop_exhausted"
        else:  # user_override
            r = conn.execute(
                "SELECT COUNT(*) FROM events WHERE run_id = ? "
                "AND event_type = 'override.used' "
                "AND payload_json LIKE '%crossai%'",
                (run_id,),
            ).fetchone()
            override_count = r[0] or 0
            if override_count == 0:
                print(
                    "⛔ user_override requires override.used event with crossai "
                    "flag first. Run: vg-orchestrator override "
                    "--flag=skip-crossai-build-loop --reason='<ticket/URL, ≥50ch>'",
                    file=sys.stderr,
                )
                return 2
            event_type = "build.crossai_loop_user_override"
    finally:
        conn.close()

    evt = db.append_event(
        run_id=run_id,
        event_type=event_type,
        phase=current["phase"],
        command="vg:build",
        actor="orchestrator",
        outcome="INFO",
        payload=payload,
    )
    print(f"emitted: {event_type} hash={evt['this_hash'][:12]}")
    return 0


def cmd_mark_step(args) -> int:
    current = state_mod.read_current_run()
    if not current:
        print("⛔ No active run. Call run-start first.", file=sys.stderr)
        return 1

    phase_dir = contracts.resolve_phase_dir(current["phase"])
    if not phase_dir:
        print(f"⛔ Phase dir not found for phase={current['phase']}",
              file=sys.stderr)
        return 1

    marker = state_mod.mark_step(phase_dir, args.namespace, args.step_name)
    db.append_event(
        run_id=current["run_id"],
        event_type="step.marked",
        phase=current["phase"],
        command=current["command"],
        actor="orchestrator",
        outcome="INFO",
        step=args.step_name,
        payload={"namespace": args.namespace, "marker": str(marker)},
    )
    print(f"marked: {args.namespace}/{args.step_name}")
    return 0


def cmd_verify_hash_chain(args) -> int:
    ok, broken_at, reason = db.verify_hash_chain(since_id=args.since_id or 0)
    if ok:
        print("hash-chain: OK")
        return 0
    print(f"⛔ hash-chain BROKEN at id={broken_at}: {reason}",
          file=sys.stderr)
    current = state_mod.read_current_run()
    if current:
        db.append_event(
            run_id=current["run_id"],
            event_type="integrity.compromised",
            phase=current["phase"],
            command=current["command"],
            actor="orchestrator",
            outcome="BLOCK",
            payload={"broken_at_id": broken_at, "reason": reason},
        )
    return 2


def cmd_wave_start(args) -> int:
    """Register new wave in active build run. Emit wave.started event.
    Same-wave re-start rejected (idempotency)."""
    current = state_mod.read_current_run()
    if not current:
        print("⛔ No active run. Call run-start first.", file=sys.stderr)
        return 1
    if current["command"] != "vg:build":
        print(f"⛔ wave-start only valid in vg:build runs, not "
              f"{current['command']}", file=sys.stderr)
        return 1

    # Check same wave already started
    existing = db.query_events(
        run_id=current["run_id"], event_type="wave.started",
    )
    for e in existing:
        try:
            if json.loads(e["payload_json"]).get("wave") == args.wave_n:
                print(f"⛔ wave {args.wave_n} already started in this run",
                      file=sys.stderr)
                return 1
        except Exception:
            continue

    db.append_event(
        run_id=current["run_id"],
        event_type="wave.started",
        phase=current["phase"],
        command=current["command"],
        actor="orchestrator",
        outcome="INFO",
        payload={"wave": args.wave_n},
    )
    print(f"wave {args.wave_n} started")
    return 0


def cmd_wave_complete(args) -> int:
    """Read evidence_json from stdin or --evidence-file. Validate schema.
    Run wave-attribution validator. Emit wave.completed or wave.blocked.
    Same-wave re-complete with different evidence = BLOCK (integrity)."""
    current = state_mod.read_current_run()
    if not current:
        print("⛔ No active run", file=sys.stderr)
        return 1

    # Load evidence
    if args.evidence_file:
        try:
            raw = Path(args.evidence_file).read_text(encoding="utf-8")
        except Exception as e:
            print(f"⛔ evidence file read error: {e}", file=sys.stderr)
            return 1
    else:
        raw = sys.stdin.read()

    try:
        evidence_data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⛔ evidence_json parse error: {e}", file=sys.stderr)
        return 1

    if evidence_data.get("wave") != args.wave_n:
        print(f"⛔ evidence.wave ({evidence_data.get('wave')}) != "
              f"--wave ({args.wave_n})", file=sys.stderr)
        return 1

    # Idempotency: re-complete with identical evidence = no-op PASS
    prior_completes = db.query_events(
        run_id=current["run_id"], event_type="wave.completed",
    )
    for e in prior_completes:
        pl = json.loads(e["payload_json"])
        if pl.get("wave") == args.wave_n:
            if pl.get("evidence_hash") == _hash_evidence(raw):
                print(f"wave {args.wave_n} already completed (idempotent)")
                return 0
            else:
                print(f"⛔ wave {args.wave_n} re-complete with DIFFERENT "
                      f"evidence → integrity violation", file=sys.stderr)
                db.append_event(
                    run_id=current["run_id"],
                    event_type="integrity.compromised",
                    phase=current["phase"],
                    command=current["command"],
                    actor="orchestrator",
                    outcome="BLOCK",
                    payload={"wave": args.wave_n,
                             "reason": "wave-complete evidence diverged"},
                )
                return 2

    # Invoke wave-attribution validator
    import subprocess
    validator = (Path(__file__).parent.parent / "validators" /
                 "wave-attribution.py")
    if not validator.exists():
        print("⛔ wave-attribution validator missing", file=sys.stderr)
        return 1

    r = subprocess.run(
        [sys.executable, str(validator),
         "--phase", current["phase"], "--wave", str(args.wave_n)],
        input=raw, capture_output=True, text=True, timeout=60,
    )

    if r.returncode != 0:
        # Validator BLOCKED — emit wave.blocked with violations
        try:
            verdict = json.loads(r.stdout)
        except Exception:
            verdict = {"verdict": "BLOCK",
                       "evidence": [{"message": r.stdout[:200]}]}

        db.append_event(
            run_id=current["run_id"],
            event_type="wave.blocked",
            phase=current["phase"],
            command=current["command"],
            actor="validator",
            outcome="BLOCK",
            payload={"wave": args.wave_n,
                     "evidence_hash": _hash_evidence(raw),
                     "violations": verdict.get("evidence", [])},
        )
        print(f"⛔ wave {args.wave_n} BLOCK — wave-attribution rejected evidence",
              file=sys.stderr)
        print(r.stdout, file=sys.stderr)
        return 2

    # PASS
    db.append_event(
        run_id=current["run_id"],
        event_type="wave.completed",
        phase=current["phase"],
        command=current["command"],
        actor="orchestrator",
        outcome="PASS",
        payload={"wave": args.wave_n,
                 "evidence_hash": _hash_evidence(raw),
                 "task_count": len(evidence_data.get("tasks", [])),
                 "commit_count": len(evidence_data.get("commits", []))},
    )
    print(f"✓ wave {args.wave_n} PASS")
    return 0


def _hash_evidence(raw: str) -> str:
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cmd_validate(args) -> int:
    """Run a named validator standalone (not at run-complete).
    Useful for skill-MD to check a gate mid-flow."""
    import subprocess
    validator = (Path(__file__).parent.parent / "validators" /
                 f"{args.validator_name}.py")
    if not validator.exists():
        print(f"⛔ validator not found: {args.validator_name}",
              file=sys.stderr)
        return 1

    current = state_mod.read_current_run()
    phase = args.phase or (current["phase"] if current else "")
    if not phase:
        print("⛔ --phase required when no active run", file=sys.stderr)
        return 1

    call_args = [sys.executable, str(validator), "--phase", phase]
    call_args.extend(args.forward or [])

    stdin_data = sys.stdin.read() if args.stdin else None
    r = subprocess.run(call_args, input=stdin_data, capture_output=True,
                       text=True, timeout=60)
    # Forward validator output verbatim
    if r.stdout:
        print(r.stdout.rstrip())
    if r.stderr:
        print(r.stderr.rstrip(), file=sys.stderr)
    return r.returncode


_TICKET_RE = re.compile(
    r"(?:https?://\S+|#\d+|(?:GH|JIRA|ISSUE|TICKET|PR|BUG|OD)-?\d+)",
    re.IGNORECASE,
)
_SHA_RE = re.compile(r"\b([0-9a-f]{7,40})\b")
# Accept only URLs pointing at real artifact trackers. Random https://x.y is
# NOT proof — it's just a string that matches the pattern.
_URL_RE = re.compile(r"https?://([^/\s]+)(/\S*)?", re.IGNORECASE)
_ACCEPTED_TRACKER_HOSTS = {
    "github.com", "gitlab.com", "bitbucket.org", "codeberg.org",
    "gitea.com", "linear.app",
}


def _verify_sha_in_repo(sha: str) -> bool:
    """OHOK-5 (Codex P0): verify a SHA-looking string is actually a git object
    in the local repo. Blocks `deadbee` / `1a2b3c4` fabricated proofs.
    """
    import subprocess
    try:
        r = subprocess.run(
            ["git", "cat-file", "-t", sha],
            capture_output=True, text=True, timeout=3,
            cwd=os.environ.get("VG_REPO_ROOT") or os.getcwd(),
        )
        # Output should be one of: commit, tree, blob, tag
        return r.returncode == 0 and r.stdout.strip() in {
            "commit", "tree", "blob", "tag"
        }
    except Exception:
        return False


def _verify_proof_resolves(reason: str) -> tuple[bool, str]:
    """OHOK-5 (Codex/Gemini P0): verify at least one proof token in `reason`
    resolves to a real artifact. Distinguishes audit breadcrumbs from proof.

    Accept paths (any ONE sufficient):
    1. SHA found via `_SHA_RE` AND `git cat-file -t <sha>` succeeds → real commit
    2. URL with trusted tracker host (github.com, gitlab.com, etc.) → assume
       real (offline URL existence check is out of scope — trust tracker list)
    3. Tracker ID (GH-42, JIRA-1234, #42) → lower trust; MUST appear alongside
       another proof OR explicit `--user-confirmed` flag (future work)

    Returns (verified, proof_kind). If nothing resolves, verified=False.
    """
    # Check SHA-like tokens
    for m in _SHA_RE.finditer(reason):
        sha = m.group(1)
        if _verify_sha_in_repo(sha):
            return True, f"git_sha:{sha[:12]}"
    # Check URL with accepted host
    for m in _URL_RE.finditer(reason):
        host = m.group(1).lower()
        # Strip port if present
        host = host.split(":", 1)[0]
        if host in _ACCEPTED_TRACKER_HOSTS:
            return True, f"url:{host}"
        # Also accept any subdomain of accepted hosts
        for tracker in _ACCEPTED_TRACKER_HOSTS:
            if host.endswith(f".{tracker}") or host == tracker:
                return True, f"url:{host}"
    return False, ""

# OHOK-3 (2026-04-22): promote-goal-manual quota per phase.
# Gemini flagged that unlimited MANUAL promotion = escape hatch. Phase 14 OHOK
# v2 run resolved OD-148/149 via promote-goal-manual instead of fixing CORS
# drift root cause. Quota forces the user to feel the cost of each manual
# goal — 3 is the soft ceiling (real phases may have legit manual goals for
# visual/UX/payment flows not feasible to automate).
PROMOTE_MANUAL_QUOTA_PER_PHASE = 3


def cmd_promote_goal_manual(args) -> int:
    """OHOK v2 Day 3 — promote a goal to verification=manual with user justification.
    Emits goal.promoted_manual event (review-skip-guard accepts MANUAL status as
    explicit promotion, not silent skip). Writes GOAL-COVERAGE-MATRIX row if
    missing, else updates status column.

    Usage: vg-orchestrator promote-goal-manual G-02 --phase 14 \\
             --reason "..." (≥50 chars with ticket/URL/commit proof)

    OHOK-3 hardening:
      - Quota: max 3 manual promotions per phase (across all runs). Forces
        user to feel escape-hatch cost. Fix root cause instead of bulk-promote.
      - Proof: --reason MUST contain a ticket URL, GH/ISSUE/JIRA ID, PR#,
        or commit SHA (min 7 hex chars). Free-text "we'll fix later" rejected.
    """
    current = state_mod.read_current_run()
    phase = args.phase or (current["phase"] if current else None)
    if not phase:
        print("⛔ --phase required (no active run)", file=sys.stderr)
        return 1

    reason = args.reason.strip()
    if len(reason) < 50:
        print(f"⛔ --reason must be ≥50 chars (got {len(reason)}).\n"
              f"   Manual promotion is an explicit user decision — require "
              f"concrete user-visible justification not auto-generated prose.",
              file=sys.stderr)
        return 2

    # OHOK-3: proof requirement — reason must cite an external artifact.
    # OHOK-5 (Codex/Gemini): proof must also RESOLVE, not just match regex.
    # Random `deadbee`, fake `#1`, or `https://bogus.invalid/` were bypass
    # vectors in the shape-only check.
    has_ticket = bool(_TICKET_RE.search(reason))
    has_commit_sha = bool(_SHA_RE.search(reason))
    if not (has_ticket or has_commit_sha):
        print(
            "⛔ --reason must cite an external artifact proving user sign-off.\n"
            "   Accept one of:\n"
            "   - Ticket URL:   https://github.com/.../issues/42\n"
            "   - Ticket ID:    GH-42, ISSUE-42, JIRA-1234, #42\n"
            "   - Commit SHA:   abc1234 (≥7 hex chars, proves root-cause fix exists)\n"
            "   - PR ref:       PR-42\n\n"
            "   Rationale (OHOK-3): free-text 'we will fix later' has no\n"
            "   forcing function. A ticket/commit reference creates an\n"
            "   externally-auditable trail that the deferred work actually\n"
            "   happens. Gemini verdict: escape hatch needs a paper trail.",
            file=sys.stderr,
        )
        return 2

    # OHOK-5: resolvable-proof gate
    resolved, proof_kind = _verify_proof_resolves(reason)
    if not resolved:
        print(
            "⛔ --reason contains shape-matching proof but NOTHING RESOLVES.\n"
            "   Shape-only tokens create audit breadcrumbs, not proof.\n"
            "   Must contain at least ONE of:\n"
            "   - A git SHA that exists in this repo (verified via\n"
            "     `git cat-file -t <sha>`). Random `deadbee` / `1a2b3c4` rejected.\n"
            "   - A URL on a trusted tracker host: github.com, gitlab.com,\n"
            "     bitbucket.org, codeberg.org, linear.app (or subdomain).\n"
            "     Standalone IDs like 'GH-42' without a URL are insufficient —\n"
            "     add the full ticket URL.\n"
            "   Rationale (OHOK-5 round-2 findings): Codex + Gemini both flagged\n"
            "   that regex shape matching accepts fabricated proofs like\n"
            "   'deadbee' or 'https://not.a.real.tracker/foo'. SHA-in-repo\n"
            "   + tracker-host allowlist closes that.",
            file=sys.stderr,
        )
        return 2

    # OHOK-3: per-phase quota. Count prior goal.promoted_manual events for this
    # phase (across all runs in events.db). Exceeds quota → BLOCK until user
    # increases quota via explicit override.
    prior = db.query_events(phase=phase, event_type="goal.promoted_manual")
    prior_count = len(prior) if prior else 0
    if prior_count >= PROMOTE_MANUAL_QUOTA_PER_PHASE:
        print(
            f"⛔ Phase {phase} has already used {prior_count}/"
            f"{PROMOTE_MANUAL_QUOTA_PER_PHASE} manual promotion slots.\n"
            f"   Quota exists to prevent bulk-flipping goals to MANUAL as\n"
            f"   escape hatch. Options:\n"
            f"   1. Fix the root cause so goal auto-verifies (preferred)\n"
            f"   2. Mark goal 'deferred' via GOAL-COVERAGE-MATRIX.md edit\n"
            f"      + add deferred-reason cite to a ticket\n"
            f"   3. Override quota (logs HARD debt): vg-orchestrator override \\\n"
            f"        --flag=promote-manual-quota-exceeded --reason '<≥20char>'\n",
            file=sys.stderr,
        )
        return 2

    repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd())
    phase_dirs = list((repo / ".vg" / "phases").glob(f"{phase}-*")) or \
                 list((repo / ".vg" / "phases").glob(f"{phase.zfill(2)}-*"))
    if not phase_dirs:
        print(f"⛔ phase {phase} not found", file=sys.stderr)
        return 1

    matrix = phase_dirs[0] / "GOAL-COVERAGE-MATRIX.md"
    if not matrix.exists():
        print(f"⛔ {matrix} not found — run /vg:review first to create it",
              file=sys.stderr)
        return 1

    text = matrix.read_text(encoding="utf-8", errors="replace")
    # Pattern: | G-02 | ... | ... | READY | ... |
    goal_pat = re.compile(
        rf"(^\|\s*{re.escape(args.goal_id)}\s*\|[^|]+\|[^|]+\|\s*)([A-Z_]+)(\s*\|)",
        re.MULTILINE,
    )
    new_text, n = goal_pat.subn(r"\1MANUAL\3", text, count=1)
    if n == 0:
        print(f"⛔ goal {args.goal_id} not found in {matrix.name}",
              file=sys.stderr)
        return 1

    # Append justification line near goal row (or in a dedicated MANUAL section)
    manual_entry = (f"\n- **{args.goal_id} MANUAL** ({datetime.utcnow().isoformat()}Z): "
                    f"{args.reason}\n")
    new_text += manual_entry
    matrix.write_text(new_text, encoding="utf-8")

    # OHOK-5 (Codex P0): event MUST fire whether or not an active run exists.
    # Previous bug: offline `promote-goal-manual --phase X` edited matrix +
    # debt file but emitted NO event → quota counter skipped → bypass vector.
    # Fix: if no active run, synthesize an offline-mode run-id so the event
    # still lands in events.db and quota counts correctly. OHOK metrics also
    # see it because by_run groups by run_id.
    if current:
        event_run_id = current["run_id"]
        event_command = current["command"]
        offline_mode = False
    else:
        # Synthesize an audited offline run so event isn't orphaned
        event_run_id = db.create_run(
            command="vg:promote-goal-manual",
            phase=phase,
            args=f"--goal-id {args.goal_id}",
            session_id=os.environ.get("CLAUDE_SESSION_ID"),
            git_sha=_git_sha(),
        )
        event_command = "vg:promote-goal-manual"
        offline_mode = True
        # Emit run.started/completed bracket so this offline call shows up
        # as a complete run in metrics rather than a dangling event.
        db.append_event(
            run_id=event_run_id,
            event_type="run.started",
            phase=phase,
            command=event_command,
            actor="user",
            outcome="INFO",
            payload={"offline_mode": True,
                     "purpose": "promote_goal_manual"},
        )

    db.append_event(
        run_id=event_run_id,
        event_type="goal.promoted_manual",
        phase=phase,
        command=event_command,
        actor="user",
        outcome="INFO",
        payload={"goal_id": args.goal_id,
                 "reason": args.reason[:300],
                 "has_ticket": has_ticket,
                 "has_commit_sha": has_commit_sha,
                 "offline_mode": offline_mode,
                 "quota_used": prior_count + 1,
                 "quota_max": PROMOTE_MANUAL_QUOTA_PER_PHASE},
    )

    if offline_mode:
        # Close the synthetic run so it appears finalized in metrics
        db.append_event(
            run_id=event_run_id,
            event_type="run.completed",
            phase=phase,
            command=event_command,
            actor="user",
            outcome="PASS",
            payload={"offline_mode": True,
                     "action": "promote_goal_manual"},
        )

    # OHOK-3: also append to OVERRIDE-DEBT.md so bulk MANUAL promotion is
    # visible during /vg:accept review, not buried in events.db alone.
    # OHOK-6 (Codex P1): write failures previously swallowed silently —
    # audit trail could vanish without anyone noticing. Now surface loudly
    # + emit debt_register.write_failed event.
    register = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()) / \
               ".vg" / "OVERRIDE-DEBT.md"
    try:
        register.parent.mkdir(parents=True, exist_ok=True)
        with register.open("a", encoding="utf-8") as f:
            f.write(
                f"\n- id: PROMOTE-MANUAL-{phase}-{args.goal_id}\n"
                f"  logged_at: {datetime.utcnow().isoformat()}Z\n"
                f"  type: goal_promoted_manual\n"
                f"  phase: \"{phase}\"\n"
                f"  goal_id: {args.goal_id}\n"
                f"  quota: {prior_count + 1}/{PROMOTE_MANUAL_QUOTA_PER_PHASE}\n"
                f"  reason: \"{args.reason.replace(chr(34), chr(39))}\"\n"
                f"  status: active\n"
            )
    except Exception as e:
        print(
            f"⚠ OVERRIDE-DEBT.md write FAILED: {e}\n"
            f"   Event still emitted to events.db (audit trail preserved there),\n"
            f"   but human-visible register is out of sync. Investigate:\n"
            f"   - disk full?\n"
            f"   - permission denied on {register}?\n"
            f"   - file locked by other process?\n"
            f"   Re-run after fixing.",
            file=sys.stderr,
        )
        try:
            db.append_event(
                run_id=event_run_id,
                event_type="debt_register.write_failed",
                phase=phase,
                command=event_command,
                actor="orchestrator",
                outcome="WARN",
                payload={"error": str(e)[:200],
                         "register": str(register),
                         "context": "promote_goal_manual"},
            )
        except Exception:
            pass  # even event DB failure → give up gracefully, don't crash

    print(f"✓ {args.goal_id} → MANUAL in {matrix.name} "
          f"(quota {prior_count + 1}/{PROMOTE_MANUAL_QUOTA_PER_PHASE})")
    return 0


def cmd_override(args) -> int:
    """Log override.used event for this run + append to OVERRIDE-DEBT.md.
    Satisfies forbidden_without_override contract check at run-complete.

    OHOK-3 hardening (2026-04-22): reason gate raised from 4→50 chars AND
    must cite external artifact (ticket/commit/PR). Previous 4-char bar let
    AI pass 'meh' as valid override — Gemini flagged as bypass vector.
    """
    current = state_mod.read_current_run()
    if not current:
        print("⛔ No active run", file=sys.stderr)
        return 1

    reason = args.reason.strip()
    if len(reason) < 50:
        print(
            f"⛔ --reason must be ≥50 chars (got {len(reason)}).\n"
            f"   Override is an explicit decision to bypass a gate — the\n"
            f"   reason becomes the audit trail. Terse reasons get rubber-\n"
            f"   stamped by reviewers. Write why this override is safe,\n"
            f"   what you checked, and when the debt gets paid down.",
            file=sys.stderr,
        )
        return 2

    has_ticket = bool(_TICKET_RE.search(reason))
    has_commit_sha = bool(_SHA_RE.search(reason))
    if not (has_ticket or has_commit_sha):
        print(
            "⛔ --reason must cite an external artifact (ticket/URL/PR/commit SHA).\n"
            "   Accept one of: https://..., GH-42, ISSUE-42, JIRA-1234, #42,\n"
            "   PR-42, or commit hash (≥7 hex chars).\n"
            "   Rationale: override without paper-trail = silent debt. The\n"
            "   OVERRIDE-DEBT register is only useful if entries are\n"
            "   externally auditable.",
            file=sys.stderr,
        )
        return 2

    # OHOK-5: resolvable-proof gate (same check as promote-goal-manual)
    resolved, proof_kind = _verify_proof_resolves(reason)
    if not resolved:
        print(
            "⛔ --reason shape-matches but NOTHING RESOLVES.\n"
            "   Shape-only proof = audit breadcrumb, not real evidence.\n"
            "   Must contain ONE of:\n"
            "   - git SHA in this repo (verified via `git cat-file -t`)\n"
            "   - URL on trusted tracker (github.com/gitlab.com/bitbucket.org/\n"
            "     codeberg.org/linear.app + subdomains)\n"
            "   Fake tokens like `deadbee` or bogus URLs rejected.",
            file=sys.stderr,
        )
        return 2

    ev = db.append_event(
        run_id=current["run_id"],
        event_type="override.used",
        phase=current["phase"],
        command=current["command"],
        actor="user",
        outcome="INFO",
        payload={"flag": args.flag, "reason": args.reason},
    )

    # Append human-readable entry to OVERRIDE-DEBT.md
    register = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()) / \
               ".vg" / "OVERRIDE-DEBT.md"
    try:
        register.parent.mkdir(parents=True, exist_ok=True)
        with register.open("a", encoding="utf-8") as f:
            f.write(
                f"\n- id: OD-{ev['id']:03d}\n"
                f"  logged_at: {ev['ts']}\n"
                f"  command: {current['command']}\n"
                f"  phase: \"{current['phase']}\"\n"
                f"  flag: {args.flag}\n"
                f"  reason: \"{args.reason}\"\n"
                f"  git_sha: {_git_sha() or 'unknown'}\n"
                f"  status: active\n"
            )
    except Exception as e:
        # OHOK-6 (Codex P1): surface loud, emit event — don't swallow
        print(
            f"⚠ OVERRIDE-DEBT.md write FAILED (cmd_override): {e}\n"
            f"   Event OD-{ev['id']:03d} already in events.db (audit trail OK),\n"
            f"   but human-visible register is out of sync. Fix + re-run.",
            file=sys.stderr,
        )
        try:
            db.append_event(
                run_id=current["run_id"],
                event_type="debt_register.write_failed",
                phase=current["phase"],
                command=current["command"],
                actor="orchestrator",
                outcome="WARN",
                payload={"error": str(e)[:200],
                         "register": str(register),
                         "context": "override",
                         "event_id": ev["id"]},
            )
        except Exception:
            pass

    print(f"OD-{ev['id']:03d} logged: {args.flag}")
    return 0


def cmd_run_resume(args) -> int:
    """Resume interrupted run. Reads current-run.json, verifies runs table
    row is incomplete, re-prints status. No destructive actions."""
    current = state_mod.read_current_run()
    if not current:
        print("no-active-run")
        return 0

    run = db.get_run(current["run_id"])
    if not run:
        print("⛔ current-run.json refs run_id not in runs table — "
              "state corrupted. Use run-repair.", file=sys.stderr)
        return 2

    if run.get("completed_at"):
        print(f"⛔ run {current['run_id'][:8]} already completed at "
              f"{run['completed_at']}. Current-run.json stale.",
              file=sys.stderr)
        return 2

    # Count events + last event type for context
    events = db.query_events(run_id=current["run_id"])
    last_event = events[-1] if events else None
    print(f"resumed: {current['command']} phase={current['phase']} "
          f"events={len(events)}")
    if last_event:
        print(f"last event: {last_event['event_type']} @ {last_event['ts']}")

    db.append_event(
        run_id=current["run_id"], event_type="run.resumed",
        phase=current["phase"], command=current["command"],
        actor="user", outcome="INFO",
        payload={"events_replayed": len(events)},
    )
    return 0


def cmd_run_repair(args) -> int:
    """Reconcile inconsistent state. Default: report + ask. With --force:
    - If current-run.json refs run_id not in runs table → clear current-run
    - If runs table has orphaned active runs → mark them aborted
    Integrity checks remain manual (hash chain tamper requires human)."""
    current = state_mod.read_current_run()
    issues = []

    if current:
        run = db.get_run(current["run_id"])
        if not run:
            issues.append({
                "type": "current-run-no-db-row",
                "detail": f"run_id {current['run_id']} not in runs table",
                "fix": "clear current-run.json",
            })
        elif run.get("completed_at"):
            issues.append({
                "type": "current-run-stale",
                "detail": f"run completed at {run['completed_at']}",
                "fix": "clear current-run.json",
            })

    # Orphaned active runs older than 1 day
    import sqlite3
    conn = sqlite3.connect(str(db.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        orphans = conn.execute(
            "SELECT run_id, command, phase, started_at FROM runs "
            "WHERE completed_at IS NULL AND "
            "started_at < datetime('now', '-1 day')"
        ).fetchall()
        for o in orphans:
            issues.append({
                "type": "orphaned-run",
                "detail": (f"{o['command']} phase={o['phase']} "
                           f"started {o['started_at']}"),
                "fix": "mark aborted",
                "run_id": o["run_id"],
            })
    finally:
        conn.close()

    if not issues:
        print("no-repairs-needed")
        return 0

    print(f"{len(issues)} issue(s) detected:")
    for i in issues:
        print(f"  [{i['type']}] {i['detail']} → fix: {i['fix']}")

    if not args.force:
        print("\nRe-run with --force to apply fixes.")
        return 1

    # Apply fixes
    for i in issues:
        if i["type"] in ("current-run-no-db-row", "current-run-stale"):
            state_mod.clear_current_run()
            print(f"  ✓ cleared current-run.json")
        elif i["type"] == "orphaned-run":
            db.complete_run(i["run_id"], outcome="ABORTED_STALE")
            db.append_event(
                run_id=i["run_id"], event_type="run.aborted",
                phase="", command="", actor="orchestrator",
                outcome="INFO", payload={"reason": "orphaned by repair"},
            )
            print(f"  ✓ marked {i['run_id'][:8]} aborted")

    print("\nrepair complete")
    return 0


def cmd_query_events(args) -> int:
    events = db.query_events(
        run_id=args.run_id,
        event_type=args.event_type,
        phase=args.phase,
        command=args.command,
        since=args.since,
        limit=args.limit,
    )
    print(json.dumps(events, indent=2, default=str))
    return 0


def _record_rule_outcomes(run_id: str, command: str, phase: str,
                          run_passed: bool) -> None:
    """Emit bootstrap.outcome_recorded for every rule that fired this run.
    outcome=success if run passed, fail if run blocked.
    Closes the learning loop that never closed in v1."""
    rule_fires = db.query_events(run_id=run_id,
                                 event_type="bootstrap.rule_fired")
    if not rule_fires:
        return

    seen_rules = set()
    for fire in rule_fires:
        try:
            pl = json.loads(fire["payload_json"])
        except Exception:
            continue
        rule_id = pl.get("rule_id")
        if not rule_id or rule_id in seen_rules:
            continue
        seen_rules.add(rule_id)

        db.append_event(
            run_id=run_id,
            event_type="bootstrap.outcome_recorded",
            phase=phase,
            command=command,
            actor="orchestrator",
            outcome="PASS" if run_passed else "BLOCK",
            payload={
                "rule_id": rule_id,
                "outcome": "success" if run_passed else "fail",
                "run_id": run_id,
            },
        )


COMMAND_VALIDATORS = {
    "vg:scope": ["phase-exists", "context-structure"],
    "vg:blueprint": ["phase-exists", "context-structure", "plan-granularity",
                     "task-goal-binding", "vg-design-coherence"],
    # OHOK v2 Day 2 expansion — build previously had min enforcement (phase-exists
    # only). Now catches: commit format drift (R1), missing citations (R2),
    # goal-binding gap, plan granularity drift, override-debt balance per-step
    # not only at accept. Wave-attribution still runs per wave-complete separately.
    # OHOK v2 finish — register test-first (TDD gate: test commit must precede
    # src commit per task, or opt-out via 'no-test-gate' marker in message).
    # Previously orphaned (existed but unregistered) — surfaced by
    # /vg:doctor wired check.
    "vg:build": ["phase-exists", "commit-attribution", "task-goal-binding",
                 "plan-granularity", "override-debt-balance", "test-first",
                 # OHOK-7 (2026-04-22): MANDATORY post-build CrossAI loop.
                 # Must see events.db evidence of ≥1 crossai iteration +
                 # a terminal event (loop_complete / loop_exhausted /
                 # loop_user_override). No way to pass this gate without
                 # actually running .claude/scripts/vg-build-crossai-loop.py.
                 "build-crossai-required"],
    # Review doesn't enforce goal-coverage — tests land in /vg:test, so review
    # always fails before tests exist. Enforcement moved to /vg:test + /vg:accept
    # where tests MUST exist. Review's in-skill 0b gate warns advisory only.
    # runtime-evidence: BLOCK if Playwright specs exist but not executed
    # (anti-rationalization — prevents AI from certifying "code evidence only").
    # OHOK v2 Day 3 — review-skip-guard catches skipped_no_browser with
    # critical UI goals (phase 14 dogfood pattern). deferred-evidence catches
    # @deferred-* tags without ticket link.
    "vg:review": ["phase-exists", "runtime-evidence", "review-skip-guard"],
    "vg:test": ["phase-exists", "goal-coverage", "runtime-evidence",
                "deferred-evidence"],
    # OHOK v2 Day 4 — add acceptance-reconciliation as final gate.
    # Catches: critical goals not passing, HARD override-debt active,
    # scope branching unresolved, step markers missing after build waves.
    "vg:accept": ["phase-exists", "event-reconciliation",
                  "override-debt-balance", "runtime-evidence",
                  "commit-attribution",
                  "acceptance-reconciliation"],
}


QUARANTINE_FILE = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()
                       ) / ".vg" / "validator-quarantine.json"
QUARANTINE_THRESHOLD = 3  # consecutive crashes OR BLOCKs → auto-disable

# OHOK-8 round-3 P0.4: validators on this allowlist NEVER get quarantined.
# Codex flagged that mandatory validators could be intentionally failed 3
# times by AI to trigger auto-disable, then skipped on iteration 4. Hard
# gates stay live always — a broken hard gate surfaces as operator pain,
# which is correct behavior (fix the validator, don't skip it).
UNQUARANTINABLE = {
    "phase-exists",               # precondition — never skip
    "commit-attribution",         # commit discipline — core contract
    "runtime-evidence",           # actual test pass verification
    "build-crossai-required",     # OHOK-7 MANDATORY loop enforcement
    "context-structure",          # scope contract integrity
}


def _load_quarantine() -> dict:
    if not QUARANTINE_FILE.exists():
        return {}
    try:
        return json.loads(QUARANTINE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_quarantine(state: dict) -> None:
    try:
        QUARANTINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUARANTINE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _quarantine_record(v_name: str, verdict: str) -> bool:
    """Update quarantine state; return True if validator now quarantined.

    OHOK-8 round-3 P0.4: hard gates on UNQUARANTINABLE allowlist can record
    their consecutive_fails count but NEVER transition to disabled. Codex
    flagged intentional-trip attack: AI fails same validator 3x to get it
    auto-disabled on iteration 4.
    """
    state = _load_quarantine()
    entry = state.setdefault(v_name, {"consecutive_fails": 0, "disabled": False})
    if verdict in ("BLOCK", "CRASH"):
        entry["consecutive_fails"] = entry.get("consecutive_fails", 0) + 1
        entry["last_fail_at"] = _now_iso()
        # Only quarantine validators NOT on the unquarantinable allowlist
        if (v_name not in UNQUARANTINABLE
                and entry["consecutive_fails"] >= QUARANTINE_THRESHOLD
                and not entry["disabled"]):
            entry["disabled"] = True
            entry["disabled_at"] = _now_iso()
    else:  # PASS / WARN — reset counter AND re-enable (validator proved healthy)
        entry["consecutive_fails"] = 0
        if entry.get("disabled"):
            entry["disabled"] = False
            entry["re_enabled_at"] = _now_iso()
    _save_quarantine(state)
    return entry["disabled"]


def _run_validators(command: str, phase: str, run_id: str,
                    run_args: str) -> list[dict]:
    """Dispatch applicable validators for this command.
    Returns list of BLOCK violations (WARN gets logged as events, doesn't block).

    Quarantine: a validator that BLOCKs 3 times in a row gets auto-disabled to
    prevent a single broken validator stalling the whole pipeline. Reset with
    manual edit of .vg/validator-quarantine.json or one PASS/WARN verdict."""
    import subprocess
    validator_dir = Path(__file__).parent.parent / "validators"
    validators = COMMAND_VALIDATORS.get(command, [])
    block_results = []
    quarantine = _load_quarantine()

    for v_name in validators:
        v_path = validator_dir / f"{v_name}.py"
        if not v_path.exists():
            continue

        # Skip if quarantined
        if quarantine.get(v_name, {}).get("disabled"):
            try:
                db.append_event(
                    run_id=run_id,
                    event_type="validation.warned",
                    phase=phase,
                    command=command,
                    actor="orchestrator",
                    outcome="WARN",
                    payload={"validator": v_name,
                             "evidence_count": 1,
                             "reason": "quarantined"},
                )
            except Exception:
                pass
            continue

        args = [sys.executable, str(v_path), "--phase", phase]
        if v_name == "override-debt-balance":
            args.extend(["--run-id", run_id, "--flags", run_args])

        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=30)
            if not r.stdout.strip():
                continue
            out = json.loads(r.stdout)
        except Exception as e:
            _quarantine_record(v_name, "CRASH")
            block_results.append({
                "validator": v_name,
                "verdict": "BLOCK",
                "evidence": [{"type": "info",
                              "message": f"validator crash: {e}"}],
            })
            continue

        # Update quarantine state (3 consecutive BLOCKs → auto-disable).
        _quarantine_record(v_name, out["verdict"])

        # Emit validation event for audit trail.
        # Three distinct states: PASS (green), WARN (non-blocking yellow),
        # BLOCK (red, blocks run-complete). Prior code collapsed WARN+BLOCK
        # into validation.failed which misled audits — WARN is informational.
        verdict_to_event = {
            "PASS": "validation.passed",
            "WARN": "validation.warned",
            "BLOCK": "validation.failed",
        }
        event_type = verdict_to_event.get(out["verdict"], "validation.failed")
        try:
            db.append_event(
                run_id=run_id,
                event_type=event_type,
                phase=phase,
                command=command,
                actor="validator",
                outcome=out["verdict"],
                payload={"validator": v_name,
                         "evidence_count": len(out.get("evidence", []))},
            )
        except Exception:
            pass

        if out["verdict"] == "BLOCK":
            block_results.append(out)

    return block_results


def _verify_contract(contract: dict | None, run_id: str, command: str,
                     phase: str, run_args: str) -> tuple[bool, list[dict]]:
    """Check must_write, must_touch_markers, must_emit_telemetry,
    forbidden_without_override + run applicable validators.
    Returns (pass, violations[])."""
    violations = []
    phase_dir = contracts.resolve_phase_dir(phase)

    # Run command-specific validators first (catches semantic issues even
    # when contract frontmatter is thin)
    validator_blocks = _run_validators(command, phase, run_id, run_args)
    for vb in validator_blocks:
        violations.append({
            "type": f"validator:{vb['validator']}",
            "missing": [
                f"[{e.get('type','?')}] {e.get('message','?')}"
                for e in vb.get("evidence", [])
            ],
        })

    if not contract:
        return (len(violations) == 0), violations

    # must_write — profile-aware + glob-aware (v2.2 OHOK-9)
    must_write = contracts.normalize_must_write(contract.get("must_write") or [])
    phase_profile = contracts.detect_phase_profile(phase)
    missing_files = []
    profile_skipped = []  # WARN, not BLOCK
    for item in must_write:
        rendered = contracts.substitute(item["path"], phase, phase_dir)
        p = Path(rendered)
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        result = evidence.check_artifact(
            p, min_bytes=item["content_min_bytes"],
            required_sections=item["content_required_sections"],
            glob_fallback=True,
        )
        if result["ok"]:
            continue
        # Missing — is this artifact even applicable for the phase profile?
        if not contracts.artifact_applicable(phase_profile, rendered):
            profile_skipped.append({
                "path": str(p),
                "reason": result["reason"],
                "profile": phase_profile,
            })
            continue
        missing_files.append({"path": str(p), "reason": result["reason"]})

    if profile_skipped:
        # Emit WARN event — visible in telemetry, not a violation
        try:
            for skip in profile_skipped:
                db.append_event(
                    run_id=run_id,
                    event_type="contract.profile_skip",
                    phase=phase,
                    command=command,
                    outcome="WARN",
                    payload={
                        "path": skip["path"],
                        "profile": skip["profile"],
                        "reason": skip["reason"],
                    },
                )
        except Exception:
            # telemetry failure must not break verify
            pass

    if missing_files:
        violations.append({"type": "must_write", "missing": missing_files})

    # --wave N partial-run exemption: when user explicitly runs a single wave
    # (e.g. /vg:build 14 --wave 2), the terminal steps (8_execute_waves,
    # 9_post_execution, 10_postmortem_sanity) + build.completed event are
    # NOT expected. Full pipeline requires a subsequent /vg:build without --wave.
    # Partial-run exemption applies to must_touch_markers + must_emit_telemetry,
    # not to must_write (SUMMARY.md still required — wave work must be logged).
    is_partial_wave = bool(re.search(r"--wave[=\s]+\d+", run_args or ""))
    PARTIAL_EXEMPT_MARKERS = {"8_execute_waves", "9_post_execution",
                              "10_postmortem_sanity", "complete"}
    PARTIAL_EXEMPT_EVENTS = {"build.completed", "review.completed",
                             "test.completed", "accept.completed"}

    # must_touch_markers — fallback check against {command-short} namespace
    # so v1 flat markers + v2 per-command markers both satisfy contract.
    # Severity-aware (v2.2 OHOK-9 d): markers with severity=warn emit
    # telemetry instead of violation; required_unless_flag waives check
    # when the named flag appears in run_args.
    markers = contracts.normalize_markers(contract.get("must_touch_markers") or [])
    if markers and phase_dir:
        if is_partial_wave:
            markers = [m for m in markers
                       if m.get("name") not in PARTIAL_EXEMPT_MARKERS]

        # Separate flag-waived markers (conditional) from always-checked
        checked = []
        waived = []
        for m in markers:
            waiver = m.get("required_unless_flag")
            if waiver and waiver in (run_args or ""):
                waived.append(m)
            else:
                checked.append(m)

        cmd_ns = command.replace("vg:", "")
        missing_markers = state_mod.check_markers(
            phase_dir, checked, fallback_namespaces=[cmd_ns, "shared"],
        )

        # Split missing into block vs warn severity
        block_missing = []
        warn_missing = []
        for missing_label in missing_markers:
            # Find original marker spec by name (label may be "ns/name" form)
            bare_name = missing_label.rsplit("/", 1)[-1]
            m_spec = next(
                (m for m in checked
                 if m["name"] == bare_name or m["name"] == missing_label),
                None,
            )
            if m_spec and m_spec.get("severity") == "warn":
                warn_missing.append(missing_label)
            else:
                block_missing.append(missing_label)

        if warn_missing:
            try:
                for wm in warn_missing:
                    db.append_event(
                        run_id=run_id,
                        event_type="contract.marker_warn",
                        phase=phase,
                        command=command,
                        outcome="WARN",
                        payload={"marker": wm, "reason": "missing (severity=warn)"},
                    )
            except Exception:
                pass

        if waived:
            try:
                for wm in waived:
                    db.append_event(
                        run_id=run_id,
                        event_type="contract.marker_waived",
                        phase=phase,
                        command=command,
                        outcome="INFO",
                        payload={"marker": wm["name"],
                                 "flag": wm.get("required_unless_flag")},
                    )
            except Exception:
                pass

        if block_missing:
            violations.append({"type": "must_touch_markers",
                               "missing": block_missing})

    # must_emit_telemetry
    telemetry_specs = contracts.normalize_telemetry(
        contract.get("must_emit_telemetry") or []
    )
    if telemetry_specs:
        if is_partial_wave:
            telemetry_specs = [t for t in telemetry_specs
                               if t.get("event_type") not in PARTIAL_EXEMPT_EVENTS]
        events = db.query_events(run_id=run_id)
        missing_tel = evidence.check_telemetry(telemetry_specs, events)
        if missing_tel:
            violations.append({"type": "must_emit_telemetry",
                               "missing": missing_tel})

    # forbidden_without_override
    forbidden = contract.get("forbidden_without_override") or []
    unresolved_overrides = []
    for flag in forbidden:
        if flag in run_args:
            # Check if override.used event exists for this flag in this run
            matches = db.query_events(run_id=run_id,
                                      event_type="override.used")
            found = False
            for m in matches:
                pl = json.loads(m["payload_json"])
                if pl.get("flag") == flag:
                    found = True
                    break
            if not found:
                unresolved_overrides.append(flag)
    if unresolved_overrides:
        violations.append({"type": "forbidden_without_override",
                           "missing": unresolved_overrides})

    return (len(violations) == 0), violations


def _format_block_message(command: str, phase: str,
                          violations: list[dict]) -> str:
    lines = [
        "⛔ VG runtime_contract violations — cannot complete run.",
        "",
        f"Command: /{command} {phase}",
        "",
        "Missing evidence:",
    ]
    for v in violations:
        lines.append(f"  [{v['type']}]")
        for m in v["missing"]:
            if isinstance(m, dict):
                lines.append(f"    - {m.get('path', m)} ({m.get('reason', '')})")
            else:
                lines.append(f"    - {m}")
    lines.extend([
        "",
        "Fix options:",
        "  1. Run missing step + produce artifacts + mark + emit",
        "  2. vg-orchestrator override --flag <f> --reason <text> "
        "(logs to OVERRIDE-DEBT.md)",
        "  3. vg-orchestrator run-abort --reason <text> (gives up)",
        "",
        "Log: .vg/events.db",
    ])
    return "\n".join(lines)


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vg-orchestrator",
                                description="VG pipeline state machine")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("run-start", help="Register new run")
    s.add_argument("command", help="vg:* command name")
    s.add_argument("phase", help="phase number")
    s.add_argument("extra", nargs=argparse.REMAINDER,
                   help="flags/args (captured verbatim; use -- prefix or quote)")
    s.set_defaults(func=cmd_run_start)

    s = sub.add_parser("run-status", help="Show active run")
    s.set_defaults(func=cmd_run_status)

    s = sub.add_parser("run-complete", help="Verify contract + complete")
    s.add_argument("--outcome", default="PASS")
    s.set_defaults(func=cmd_run_complete)

    s = sub.add_parser("run-abort", help="Abort current run")
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_run_abort)

    s = sub.add_parser("emit-event", help="Append event to active run")
    s.add_argument("event_type")
    s.add_argument("--payload", default=None,
                   help="JSON payload (or use stdin with --stdin)")
    s.add_argument("--step", default=None)
    s.add_argument("--actor", default="orchestrator",
                   choices=["orchestrator", "hook", "validator",
                            "llm-claimed", "user"])
    s.add_argument("--outcome", default="INFO",
                   choices=["PASS", "BLOCK", "WARN", "INFO"])
    s.set_defaults(func=cmd_emit_event)

    s = sub.add_parser("mark-step", help="Touch step marker")
    s.add_argument("namespace", help="e.g. 'build', 'blueprint', 'shared'")
    s.add_argument("step_name")
    s.set_defaults(func=cmd_mark_step)

    # OHOK-8 round-3 P0.1: dedicated path for emit terminal CrossAI events
    # (exhausted/user_override). loop_complete is emitted automatically by
    # the loop script; this subcommand covers the user-choice terminals.
    s = sub.add_parser(
        "emit-crossai-terminal",
        help="Emit build.crossai_loop_exhausted or _user_override (restricted)",
    )
    s.add_argument(
        "kind",
        choices=["exhausted", "user_override"],
        help="loop_exhausted (after max iter) or loop_user_override (after override)",
    )
    s.add_argument("--payload", default="{}",
                   help="JSON payload (optional)")
    s.set_defaults(func=cmd_emit_crossai_terminal)

    s = sub.add_parser("wave-start", help="Register wave in build run")
    s.add_argument("wave_n", type=int)
    s.set_defaults(func=cmd_wave_start)

    s = sub.add_parser("wave-complete", help="Close wave with evidence")
    s.add_argument("wave_n", type=int)
    s.add_argument("--evidence-file", default=None,
                   help="evidence JSON file; omit to read stdin")
    s.set_defaults(func=cmd_wave_complete)

    s = sub.add_parser("validate", help="Run named validator standalone")
    s.add_argument("validator_name")
    s.add_argument("--phase", default=None,
                   help="override phase (else uses active run)")
    s.add_argument("--stdin", action="store_true",
                   help="forward stdin to validator")
    s.add_argument("forward", nargs=argparse.REMAINDER,
                   help="args forwarded to validator")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("override", help="Log override.used event + debt entry")
    s.add_argument("--flag", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_override)

    # OHOK v2 Day 3 — promote goal to MANUAL with user justification
    s = sub.add_parser("promote-goal-manual",
                       help="Promote goal to verification=manual (user sign-off)")
    s.add_argument("goal_id", help="e.g. G-02")
    s.add_argument("--phase", default=None,
                   help="phase (else uses active run)")
    s.add_argument("--reason", required=True,
                   help="Justification ≥50 chars (user-visible)")
    s.set_defaults(func=cmd_promote_goal_manual)

    s = sub.add_parser("run-resume", help="Resume interrupted run")
    s.set_defaults(func=cmd_run_resume)

    s = sub.add_parser("run-repair", help="Reconcile inconsistent state")
    s.add_argument("--force", action="store_true",
                   help="apply fixes; default is dry-run report")
    s.set_defaults(func=cmd_run_repair)

    s = sub.add_parser("verify-hash-chain", help="Integrity check")
    s.add_argument("--since-id", type=int, default=0)
    s.set_defaults(func=cmd_verify_hash_chain)

    s = sub.add_parser("query-events", help="Read events")
    s.add_argument("--run-id", default=None)
    s.add_argument("--event-type", default=None)
    s.add_argument("--phase", default=None)
    s.add_argument("--command", default=None)
    s.add_argument("--since", default=None)
    s.add_argument("--limit", type=int, default=1000)
    s.set_defaults(func=cmd_query_events)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as e:
        print(f"⛔ orchestrator error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
