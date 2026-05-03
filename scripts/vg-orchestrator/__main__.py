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
  tasklist-projected --adapter claude|codex|fallback
  step-active <step_name>
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
from datetime import datetime, timezone
from pathlib import Path

# Ensure package-relative imports work when run via `python -m vg_orchestrator`
# or `python .claude/scripts/vg-orchestrator/__main__.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402
import contracts  # noqa: E402
import state as state_mod  # noqa: E402
import evidence  # noqa: E402
from _repo_root import find_repo_root  # noqa: E402

_REPO_ROOT = find_repo_root(__file__)

# v2.5.2 Phase O — optional imports. Wrapped in try/except so missing
# modules in older clones never break run-start. All call sites below
# check hasattr / is-not-None before invoking.
try:
    import lock as _lock_mod  # noqa: E402
except Exception:  # pragma: no cover
    _lock_mod = None  # type: ignore

try:
    import journal as _journal_mod  # noqa: E402
except Exception:  # pragma: no cover
    _journal_mod = None  # type: ignore

try:
    import allow_flag_gate as _allow_flag_gate  # noqa: E402
except Exception:  # pragma: no cover
    _allow_flag_gate = None  # type: ignore

try:
    import _orphans as _orphans_mod  # noqa: E402
except Exception:  # pragma: no cover
    _orphans_mod = None  # type: ignore


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


def _verify_artifact_run_binding(artifact_path: Path, run_id: str,
                                 check_provenance: bool = False) -> dict:
    """Phase K of v2.5.2 — verify artifact was created by current run.

    Returns dict {ok: bool, reason: str}. Non-blocking lookup — if manifest
    machinery missing, returns ok=False with actionable reason.

    Checks (in order):
      1. .vg/runs/{run_id}/evidence-manifest.json exists
      2. Manifest has entry for this artifact path
      3. entry.creator_run_id == run_id
      4. entry.sha256 matches current file sha256 (not mutated after emit)
      5. (optional) source_inputs hashes still match disk (--check-provenance)
    """
    import hashlib as _hashlib
    import json as _json
    import subprocess
    from pathlib import Path as _Path

    def _sha256(p: _Path) -> str | None:
        try:
            data = p.read_bytes()
            data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            return _hashlib.sha256(data).hexdigest()
        except (FileNotFoundError, PermissionError):
            return None

    repo_root = _Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    ) if _Path(".git").exists() or True else _Path(os.getcwd())

    manifest_path = repo_root / ".vg" / "runs" / run_id / "evidence-manifest.json"
    if not manifest_path.exists():
        return {
            "ok": False,
            "reason": (
                f"evidence-manifest.json missing for run {run_id[:12]}... "
                f"— emit-evidence-manifest.py was never called during this run"
            ),
        }

    try:
        manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError:
        return {"ok": False, "reason": "evidence-manifest.json unparseable"}

    # Match entry by relative path (portable)
    try:
        rel_path = artifact_path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        rel_path = str(artifact_path)

    entry = next(
        (e for e in manifest.get("entries", []) if e.get("path") == rel_path),
        None,
    )
    if entry is None:
        return {
            "ok": False,
            "reason": (
                f"no manifest entry for {rel_path} — "
                f"artifact exists but was not logged via emit-evidence-manifest"
            ),
        }

    if entry.get("creator_run_id") != run_id:
        return {
            "ok": False,
            "reason": (
                f"entry.creator_run_id={entry.get('creator_run_id', '?')[:12]}... "
                f"but current run_id={run_id[:12]}... — artifact from prior run (stale)"
            ),
        }

    entry_hash = entry.get("sha256")
    current_hash = _sha256(artifact_path)
    if entry_hash and current_hash and entry_hash != current_hash:
        return {
            "ok": False,
            "reason": (
                f"file mutated after emit — manifest sha256={entry_hash[:12]}... "
                f"vs current={current_hash[:12]}..."
            ),
        }

    if check_provenance:
        for src in entry.get("source_inputs", []):
            src_path_str = src.get("path", "")
            expected = src.get("sha256")
            src_path = _Path(src_path_str)
            if not src_path.is_absolute():
                src_path = repo_root / src_path
            current_src_hash = _sha256(src_path)
            if expected and current_src_hash != expected:
                return {
                    "ok": False,
                    "reason": (
                        f"provenance drift: source input {src_path_str} "
                        f"mutated since artifact emit"
                    ),
                }

    return {"ok": True, "reason": None}


def _mirror_sync_preflight(command: str, phase: str, extra_args: str) -> None:
    """Phase 0 of v2.5.2 — check Codex skill mirror parity before registering run.

    Modes via VG_SYNC_CHECK_MODE env:
        "off"   — skip entirely (legacy default during rollout)
        "warn"  — log drift to events.db but allow run (default after rollout)
        "block" — reject run-start on drift (hard enforce)

    Bypass flags:
        VG_SYNC_CHECK_DISABLED=true in env
        --allow-mirror-drift in run args (logs to override-debt per Phase O)

    Does NOT raise exceptions — best-effort, never breaks run-start on its own
    internal errors. Only blocks when (a) mode=block AND drift clearly detected.
    """
    import os as _os
    import subprocess as _sp
    import sys as _sys
    from pathlib import Path as _Path

    if _os.environ.get("VG_SYNC_CHECK_DISABLED", "").lower() == "true":
        return
    if "--allow-mirror-drift" in extra_args:
        return

    mode = _os.environ.get("VG_SYNC_CHECK_MODE", "warn").lower()
    if mode == "off":
        return

    # Locate validator — skip if not installed (pre-v2.5.2 repos)
    try:
        repo_root = _Path(_sp.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=_sp.DEVNULL, text=True,
        ).strip())
    except Exception:
        return  # not in git repo — can't verify

    validator = repo_root / ".claude" / "scripts" / "validators" / \
        "verify-codex-skill-mirror-sync.py"
    if not validator.exists():
        return  # validator not installed yet

    try:
        env = _os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        r = _sp.run(
            [_sys.executable, str(validator), "--quiet", "--json",
             "--skip-vgflow"],
            capture_output=True, text=True, timeout=10,
            env=env, encoding="utf-8", errors="replace",
        )
    except (_sp.TimeoutExpired, FileNotFoundError):
        return  # best-effort — don't block on infra issues

    if r.returncode == 0:
        return  # in sync, nothing to do

    # Drift detected
    try:
        import json as _json
        data = _json.loads(r.stdout) if r.stdout else {}
        drift_count = data.get("drift_count", 0)
    except Exception:
        drift_count = "?"

    # Emit telemetry event (always — even in warn mode) so drift is audit-visible
    try:
        db.append_event(
            run_id="pre-run-preflight",  # no run_id yet — will be orphaned
            event_type="mirror_sync.drift_detected",
            phase=phase,
            command=command,
            actor="orchestrator",
            outcome="WARN" if mode != "block" else "BLOCK",
            payload={
                "drift_count": drift_count,
                "mode": mode,
                "command_attempted": command,
            },
        )
    except Exception:
        pass

    if mode == "block":
        print(
            f"\033[38;5;208mCodex skill mirror drift detected \033[0m"
            f"({drift_count} skill(s) out of sync).\n"
            f"   Running /{command} now risks Codex agents reading stale\n"
            f"   skill contract — trust parity breach.\n\n"
            f"   Fix (choose one):\n"
            f"     (a) python .claude/scripts/sync-vg-skills.py\n"
            f"     (b) DEV_ROOT=\"$PWD\" bash ../vgflow-repo/sync.sh\n"
            f"     (c) VG_SYNC_CHECK_MODE=warn python vg-orchestrator run-start ...\n"
            f"         (downgrade to warn for this run; logs drift event)\n"
            f"     (d) --allow-mirror-drift in args (emergency bypass + debt)\n",
            file=_sys.stderr,
        )
        _sys.exit(1)

    # warn mode — pass through with visible warning
    print(
        f"\033[33mCodex skill mirror drift: {drift_count} skill(s) out of sync\033[0m\n"
        f"   Continuing in warn mode (VG_SYNC_CHECK_MODE={mode}).\n"
        f"   Fix: python .claude/scripts/sync-vg-skills.py",
        file=_sys.stderr,
    )


def _is_run_stale(active: dict) -> bool:
    """True if active run is old enough to be considered abandoned.
    Matches Stop hook's STALE_MINUTES so the two layers stay consistent.

    Pre-existing bug: `fromisoformat(started.rstrip("Z"))` produced a
    NAIVE datetime; subtracting from `now(tz=utc)` raised TypeError
    (aware-naive mismatch); except branch returned True → ALWAYS stale.
    Fix: normalize Z → +00:00 and add UTC tz if parser still returned
    naive. Same fix applied in vg-verify-claim.py is_stale().
    """
    started = active.get("started_at", "")
    if not started:
        return True
    try:
        if started.endswith("Z"):
            started = started[:-1] + "+00:00"
        ts = datetime.fromisoformat(started)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        return age_min > _RUN_STALE_MINUTES
    except Exception:
        return True


def cmd_run_start(args) -> int:
    """Write runs row + emit run.started. Return run_id on stdout.

    v2.28.0: per-session active-run keying. The active-run check now scopes
    to THIS session's state file (.vg/active-runs/{session_id}.json) rather
    than the global current-run.json. Two parallel Claude Code sessions on
    the same project (different phases) used to cross-block here; now each
    session manages its own slot. Cross-session active runs are surfaced
    as a WARN, never blocking — prevents user-perceived "lock" when one
    window runs /vg:scope while another runs /vg:build.
    """
    session_id = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID")

    active = state_mod.read_active_run(session_id)
    if active:
        # Same-session active run — existing block-or-stale-clear logic applies.
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
            state_mod.clear_active_run(session_id)
            # Continue to fresh run-start below
        else:
            print(f"⛔ Active run exists in THIS session: {active.get('command')} "
                  f"phase={active.get('phase')} started "
                  f"{active.get('started_at', '?')} (<{_RUN_STALE_MINUTES}min old).\n"
                  f"   Options:\n"
                  f"   1. Complete it: python vg-orchestrator run-complete\n"
                  f"   2. Abort: python vg-orchestrator run-abort --reason '<why>'\n"
                  f"   3. Wait >{_RUN_STALE_MINUTES}min — it will auto-clear",
                  file=sys.stderr)
            return 1

    # v2.28.0: cross-session active runs from OTHER sessions are surfaced as a
    # warning, not a block. Two windows on the same project doing different
    # phases is a legitimate workflow. Stop hook (vg-verify-claim) handles
    # the cross-session case via session_id matching, so safety is preserved.
    if session_id:
        for other in state_mod.list_active_runs():
            other_sid = other.get("session_id")
            if other_sid and other_sid != session_id and not _is_run_stale(other):
                print(
                    f"⚠ Another session is running {other.get('command')} "
                    f"phase={other.get('phase')} (session "
                    f"{other_sid[:12]}…). Starting concurrent run in this "
                    f"session is allowed but git index + commit-queue mutex "
                    f"are shared — sequence build steps if they touch the "
                    f"same files.",
                    file=sys.stderr,
                )
                break
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
            print(f"\033[38;5;208m--override-reason too short ({len(reason)} chars, min 50).\033[0m\n"
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
                print(f"\033[38;5;208m--override-reason matches placeholder pattern: {pat!r}\033[0m\n"
                      f"   Got: {reason!r}\n"
                      f"   Cite concrete evidence: issue URL, test name, CI run ID, etc.",
                      file=sys.stderr)
                return 2

        # Harness v2.6.1 (2026-04-26): wire TTY/HMAC caller-auth on
        # --override-reason. Per AUDIT.md D2 finding: AI subagent could
        # craft 50+ char "professional-looking" reason and bypass any hard
        # gate. Min-length + placeholder check filters obvious sloppiness
        # but doesn't block determined self-justification.
        #
        # Same gate verify_human_operator() used for --allow-* flags
        # (v2.5.2.1). TTY OR HMAC-signed token required. AI subagent
        # without TTY + without signing-key access → BLOCK.
        #
        # Override the gate via VG_ALLOW_FLAGS_LEGACY_RAW=true (audit-flagged
        # back-compat path) — but DEFAULT is strict per v2.5.2.2.
        try:
            from allow_flag_gate import verify_human_operator  # type: ignore
            is_human, approver = verify_human_operator("override-reason")
            if not is_human:
                print(
                    "\033[38;5;208m--override-reason requires TTY session OR signed \033[0m"
                    "approver token (HMAC).\n"
                    "   AI subagents cannot self-inject overrides — this "
                    "would bypass hard security gates with self-crafted\n"
                    "   reasons. Min-length + placeholder check is not "
                    "sufficient defense against determined misuse.\n"
                    "\n"
                    "   To approve as human:\n"
                    "     a) Run /vg:* command from interactive shell "
                    "(TTY) — auto-approved.\n"
                    "     b) Mint signed token: python3 .claude/scripts/"
                    "vg-auth.py approve --flag override-reason\n"
                    "        Then export VG_HUMAN_OPERATOR=<token> before "
                    "invoking the command.\n"
                    f"\n   Got reason: {reason[:80]!r}{'...' if len(reason) > 80 else ''}",
                    file=sys.stderr,
                )
                # Audit trail
                try:
                    db.append_event(
                        run_id="orchestrator-preflight",
                        event_type="override.blocked_caller_auth",
                        phase=args.phase or "",
                        command=args.command,
                        actor="orchestrator",
                        outcome="BLOCK",
                        payload={
                            "flag": "--override-reason",
                            "reason_head": reason[:120],
                            "reason_len": len(reason),
                        },
                    )
                except Exception:
                    pass
                return 2

            # Rubber-stamp escalator: same reason fingerprint copy-pasted
            # across ≥2 prior phases → BLOCK with prompt for fresh
            # justification. Uses check_skip_flag_rubber_stamp from v2.5.2.
            # Only runs when override-reason is paired with a --skip-* flag
            # (the typical rubber-stamp scenario).
            if override_flag and override_flag.startswith("--skip-"):
                try:
                    from allow_flag_gate import check_skip_flag_rubber_stamp  # type: ignore
                    # Recent override.used events for rubber-stamp pattern check
                    recent_events_raw = db.query_events(
                        event_type="override.used",
                        limit=500,
                    ) or []
                    # Normalize payload (db.query_events returns payload_json string)
                    recent_events = []
                    for ev in recent_events_raw:
                        ev_copy = dict(ev)
                        if "payload_json" in ev_copy and isinstance(ev_copy["payload_json"], str):
                            try:
                                ev_copy["payload"] = json.loads(ev_copy["payload_json"])
                            except Exception:
                                ev_copy["payload"] = {}
                        recent_events.append(ev_copy)
                    is_rubber_stamp, hit_count, matching = check_skip_flag_rubber_stamp(
                        events=recent_events,
                        flag_name=override_flag,
                        reason=reason,
                        current_phase=args.phase or "",
                        threshold=2,
                    )
                    if is_rubber_stamp:
                        print(
                            f"\033[38;5;208mRubber-stamp detected: same justification \033[0m"
                            f"used in {hit_count} prior phase(s) for "
                            f"{override_flag}.\n"
                            f"   Matching phases: {', '.join(matching[:5])}\n"
                            f"   Echo-chamber risk — copy-paste rationale "
                            f"defeats CrossAI/2nd-opinion gates.\n"
                            f"\n   Required: write a NEW justification "
                            f"specific to this phase's context.\n"
                            f"   Or escalate via interactive prompt with "
                            f"phase-specific evidence.",
                            file=sys.stderr,
                        )
                        try:
                            db.append_event(
                                run_id="orchestrator-preflight",
                                event_type="override.blocked_rubber_stamp",
                                phase=args.phase or "",
                                command=args.command,
                                actor="orchestrator",
                                outcome="BLOCK",
                                payload={
                                    "flag": override_flag,
                                    "matching_phases": matching,
                                    "hit_count": hit_count,
                                },
                            )
                        except Exception:
                            pass
                        return 2
                except ImportError:
                    pass  # check_skip_flag_rubber_stamp absent — older install
        except ImportError:
            # allow_flag_gate not yet built (older install) — fall through
            # with min-length + placeholder check only. Operator should
            # upgrade to get full caller-auth.
            pass

    # Phase 0 of v2.5.2 — Codex skill mirror sync preflight.
    # Runs before run registration. Detects drift between .claude source,
    # vgflow-repo mirror, and .codex/~/.codex Codex mirrors. If drift
    # present, Codex agents could forge evidence against stale contract.
    # Mode gated by env VG_SYNC_CHECK_MODE: "off" (skip), "warn" (log + pass,
    # default), "block" (reject run-start). Bypass via VG_SYNC_CHECK_DISABLED=true.
    # --allow-mirror-drift in args also bypasses (with override-debt logged).
    _mirror_sync_preflight(args.command, args.phase, extra_str)

    run_id = db.create_run(
        command=args.command,
        phase=args.phase,
        args=extra_str,
        session_id=session_id,
        git_sha=_git_sha(),
    )

    # v2.5.2 Phase O — acquire repo-level advisory lock. Failure logs a
    # warning event but does NOT block the run until config.orchestrator_lock
    # flips to hard-enforce mode (future phase). This avoids breaking any
    # caller that hasn't been upgraded yet.
    lock_token = None
    if _lock_mod is not None:
        try:
            lock_token = _lock_mod.acquire_repo_lock(
                command=args.command, phase=args.phase,
            )
            if lock_token is None:
                active_lock = _lock_mod.get_active_lock() or {}
                try:
                    db.append_event(
                        run_id=run_id, event_type="lock.acquire_failed",
                        phase=args.phase, command=args.command,
                        actor="orchestrator", outcome="WARN",
                        payload={
                            "active_holder": active_lock.get("command"),
                            "active_phase": active_lock.get("phase"),
                            "active_pid": active_lock.get("pid"),
                        },
                    )
                except Exception:
                    pass
        except Exception:
            lock_token = None

    # OHOK-9 fix (2026-05-02): when CLAUDE_SESSION_ID env var missing,
    # the run was previously stored with session_id=null which caused
    # Stop hook in OTHER parallel sessions to mistake it for their own
    # run and BLOCK with infinite contract-violation loop. Synthesize
    # a placeholder session_id so cross-session detection always works.
    # Format: "session-unknown-{run_id_prefix}" — distinguishable from
    # real Claude Code session_ids (UUIDs without "unknown-" prefix).
    if not session_id:
        session_id = f"session-unknown-{run_id[:8]}"
        print(
            f"\033[33mrun-start: CLAUDE_SESSION_ID env var missing — tagged \033[0m"
            f"run_id={run_id[:12]} with synthetic session={session_id}. "
            f"Cross-session detection still works, but parent caller "
            f"should propagate CLAUDE_SESSION_ID via env for full audit.",
            file=sys.stderr,
        )
        try:
            db.update_run_session(run_id, session_id)
        except Exception:
            # State file remains authoritative for active-run routing. The DB
            # backfill is audit metadata; do not fail a valid run-start if the
            # ledger is temporarily locked.
            pass

    current_run_entry = {
        "run_id": run_id,
        "command": args.command,
        "phase": args.phase,
        "args": extra_str,
        "started_at": _now_iso(),
        # v2.28.0: persist session_id in state file. Stop hook
        # (vg-verify-claim) reads this for cross-session detection;
        # state.read_active_run() routes by session_id; multi-tenant
        # active-run dispatch needs it as the routing key.
        "session_id": session_id,
    }
    if lock_token:
        current_run_entry["lock_token"] = lock_token
    state_mod.write_active_run(current_run_entry, session_id=session_id)

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


def _tasklist_event_name(command: str) -> str:
    return f"{command.replace('vg:', '').replace(':', '_')}.tasklist_shown"


def _tasklist_projection_event_name(command: str) -> str:
    return f"{command.replace('vg:', '').replace(':', '_')}.native_tasklist_projected"


def _humanize_step_name(step: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", step)
    text = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", text)
    text = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", text)
    text = text.replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in text.split())


def _load_run_taskboard(run_id: str, command: str) -> dict:
    tasklist_events = db.query_events(
        run_id=run_id,
        event_type=_tasklist_event_name(command),
        limit=20,
    )
    tasklist_payload = {}
    if tasklist_events:
        try:
            tasklist_payload = json.loads(tasklist_events[-1]["payload_json"] or "{}")
        except Exception:
            tasklist_payload = {}

    steps = tasklist_payload.get("steps") or []
    profile = tasklist_payload.get("profile")
    marked_events = db.query_events(run_id=run_id, event_type="step.marked", limit=2000)
    marked = [evt.get("step") for evt in marked_events if evt.get("step")]
    marked_set = set(marked)

    current_step = None
    for step in steps:
        if step not in marked_set:
            current_step = step
            break

    return {
        "profile": profile,
        "steps": steps,
        "marked": marked,
        "marked_set": marked_set,
        "completed_count": sum(1 for step in steps if step in marked_set),
        "current_step": current_step,
        "last_completed_step": marked[-1] if marked else None,
    }


def _render_taskboard(current: dict, run_row: dict | None, compact: bool = False) -> str:
    board = _load_run_taskboard(current["run_id"], current["command"])
    steps = board["steps"]
    if not steps:
        return ""

    lines = []
    profile = board.get("profile") or "unknown"
    completed = board["completed_count"]
    total = len(steps)
    active_step = current.get("active_step")
    current_step = active_step or board["current_step"]
    last_completed = board["last_completed_step"]

    lines.append("━" * 78)
    lines.append(
        f"  {current['command']} — Phase {current['phase']} — Profile {profile}"
    )
    if run_row and run_row.get("started_at"):
        lines.append(f"  Started: {run_row['started_at']}")
    lines.append(f"  Progress: {completed}/{total} step(s) completed")
    if last_completed:
        lines.append(f"  Last completed: {last_completed}")
    if active_step:
        lines.append(f"  Active: {active_step}")
    elif current_step:
        lines.append(f"  Next: {current_step}")
    lines.append("━" * 78)

    visible_steps = steps
    if compact and total > 7:
        done_tail = [s for s in steps if s in board["marked_set"]][-2:]
        pending_head = [s for s in steps if s not in board["marked_set"]][:4]
        keep = []
        seen = set()
        for step in done_tail + pending_head:
            if step not in seen:
                seen.add(step)
                keep.append(step)
        visible_steps = keep

    for step in visible_steps:
        if step in board["marked_set"]:
            icon = "[x]"
        elif step == current_step:
            icon = "[>]"
        else:
            icon = "[ ]"
        real_idx = steps.index(step) + 1
        lines.append(f"  {icon} {real_idx:2d}. {step}")
        if not compact:
            lines.append(f"      {_humanize_step_name(step)}")

    if compact and len(visible_steps) < total:
        remaining = total - len(visible_steps)
        lines.append(f"  ... {remaining} more step(s) hidden")

    lines.append("━" * 78)
    return "\n".join(lines)


def cmd_tasklist_projected(args) -> int:
    """Record that the runtime-native task UI now mirrors the task contract.

    The native task list is intentionally a projection, not the source of
    truth. This command binds that projection back to the durable harness
    contract so run-complete can verify that users saw the step checklist
    before execution moved on.
    """
    current = state_mod.read_current_run()
    if not current:
        print("\033[38;5;208mNo active run. Call run-start first.\033[0m", file=sys.stderr)
        return 1

    run_id = current["run_id"]
    contract_path = _REPO_ROOT / ".vg" / "runs" / run_id / "tasklist-contract.json"
    if not contract_path.exists():
        print(
            f"\033[38;5;208mtasklist-contract.json missing for run_id={run_id[:12]}.\033[0m\n"
            f"   Run emit-tasklist.py after run-start, then project its items "
            f"to the native task UI before continuing.",
            file=sys.stderr,
        )
        return 2

    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"\033[38;5;208mtasklist-contract.json is unreadable: {exc}\033[0m", file=sys.stderr)
        return 2

    items = contract.get("items") or []
    checklists = contract.get("checklists") or []
    item_ids = [
        item.get("id")
        for item in items
        if isinstance(item, dict) and item.get("id")
    ]
    checklist_ids = [
        checklist.get("id")
        for checklist in checklists
        if isinstance(checklist, dict) and checklist.get("id")
    ]
    # v2 is a field-superset of v1 (adds hierarchical group headers); event
    # payload is identical so we accept both. Bug S2 fix — emit-tasklist.py
    # writes v2 unconditionally; rejecting v1-only here meant
    # `<flow>.native_tasklist_projected` never fired, breaking run-complete.
    if contract.get("schema") not in ("native-tasklist.v1", "native-tasklist.v2"):
        print(
            "\033[38;5;208mtasklist contract schema must be native-tasklist.v1 or v2\033[0m",
            file=sys.stderr,
        )
        return 2
    if contract.get("run_id") != run_id:
        print("\033[38;5;208mtasklist contract belongs to a different run_id\033[0m", file=sys.stderr)
        return 2
    if contract.get("command") != current.get("command"):
        print("\033[38;5;208mtasklist contract command does not match active run\033[0m", file=sys.stderr)
        return 2
    if str(contract.get("phase")) != str(current.get("phase")):
        print("\033[38;5;208mtasklist contract phase does not match active run\033[0m", file=sys.stderr)
        return 2
    if not item_ids:
        print("\033[38;5;208mtasklist contract contains no task items\033[0m", file=sys.stderr)
        return 2

    event_type = _tasklist_projection_event_name(current["command"])
    evt = db.append_event(
        run_id=run_id,
        event_type=event_type,
        phase=current["phase"],
        command=current["command"],
        actor="orchestrator",
        outcome="INFO",
        payload={
            "adapter": args.adapter,
            "contract_path": str(contract_path),
            "item_count": len(item_ids),
            "item_ids": item_ids,
            "checklist_count": len(checklist_ids),
            "checklist_ids": checklist_ids,
            "projection_required": True,
            "source_schema": contract.get("schema"),
        },
    )

    current["tasklist_projected"] = True
    current["tasklist_projected_adapter"] = args.adapter
    current["tasklist_projected_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state_mod.write_active_run(current)

    print(
        f"native-tasklist-projected: {event_type} "
        f"items={len(item_ids)} checklists={len(checklist_ids)} "
        f"adapter={args.adapter} hash={evt['this_hash'][:12]}"
    )
    return 0


def cmd_step_active(args) -> int:
    current = state_mod.read_current_run()
    if not current:
        print("\033[38;5;208mNo active run. Call run-start first.\033[0m", file=sys.stderr)
        return 1

    current["active_step"] = args.step_name
    current["active_step_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state_mod.write_active_run(current)

    db.append_event(
        run_id=current["run_id"],
        event_type="step.active",
        phase=current["phase"],
        command=current["command"],
        actor="orchestrator",
        outcome="INFO",
        step=args.step_name,
        payload={"step": args.step_name},
    )
    print(f"active: {args.step_name}")
    pretty = _render_taskboard(current, db.get_run(current["run_id"]), compact=True)
    if pretty:
        print(pretty)
    return 0


def cmd_run_status(_args) -> int:
    """Show active run for THIS session + cross-session sibling runs (if any).

    v2.28.0: surfaces multi-tenant state. Two parallel sessions on the same
    project will both show up, each scoped to its own session_id.
    """
    session_id = (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
    )
    current = state_mod.read_active_run(session_id)
    all_active = state_mod.list_active_runs()
    current_run_id = current.get("run_id") if current else None

    other_sessions = [
        r for r in all_active
        if r.get("run_id") != current_run_id
        and r.get("session_id")
        and r.get("session_id") != session_id
    ]

    if not current and not other_sessions:
        print("no-active-run")
        return 0

    state_warnings = []
    if current and not current_run_id:
        state_warnings.append("current active-run state is missing run_id")

    run_row = db.get_run(current_run_id) if current_run_id else None
    payload = {
        "this_session": session_id,
        "current_run": current,
        "run_row": run_row,
    }
    if state_warnings:
        payload["state_warnings"] = state_warnings
    if other_sessions:
        payload["other_sessions_active"] = [
            {"session_id": (r.get("session_id") or "")[:12],
             "command": r.get("command"),
             "phase": r.get("phase"),
             "started_at": r.get("started_at")}
            for r in other_sessions
        ]
    if getattr(_args, "pretty", False) and current:
        pretty = _render_taskboard(current, run_row)
        if pretty:
            print(pretty)
            if other_sessions:
                print("Other active sessions:")
                for r in payload["other_sessions_active"]:
                    print(
                        f"  - {r['session_id']} {r['command']} "
                        f"phase={r['phase']} started={r['started_at']}"
                    )
            return 0
    print(json.dumps(payload, indent=2, default=str))
    return 0


def cmd_run_complete(args) -> int:
    """Verify runtime_contract evidence, emit completion event, clear current-run."""
    current = state_mod.read_current_run()
    if not current:
        print("\033[38;5;208mNo active run to complete.\033[0m", file=sys.stderr)
        return 1

    run_id = current["run_id"]
    command = current["command"]
    phase = current["phase"]
    run_args = current.get("args", "")

    # Tier B: pin-aware contract loading. If .contract-pins.json exists for
    # this (phase, command), use pinned must_touch_markers + must_emit_telemetry
    # so harness upgrades don't retroactively invalidate already-shipped phases.
    contract = contracts.parse_for_phase(phase, command)
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
        # v2.5.2 Phase O — release repo-lock if we own it
        lock_token = current.get("lock_token")
        if lock_token and _lock_mod is not None:
            try:
                _lock_mod.release_repo_lock(lock_token)
            except Exception:
                pass
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
    # v2.5.2 Phase O — release repo-lock on abort
    lock_token = current.get("lock_token")
    if lock_token and _lock_mod is not None:
        try:
            _lock_mod.release_repo_lock(lock_token)
        except Exception:
            pass
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
RESERVED_EVENT_SUFFIXES = (
    ".native_tasklist_projected",  # must use tasklist-projected contract binder
)


def _is_reserved_event(event_type: str) -> bool:
    if event_type in RESERVED_EVENT_EXACT:
        return True
    if any(event_type.endswith(s) for s in RESERVED_EVENT_SUFFIXES):
        return True
    return any(event_type.startswith(p) for p in RESERVED_EVENT_PREFIXES)


def cmd_emit_event(args) -> int:
    current = state_mod.read_current_run()
    if not current:
        print("\033[38;5;208mNo active run. Call run-start first.\033[0m", file=sys.stderr)
        return 1

    # OHOK-8: block forgery of gate-relevant event types via CLI
    if _is_reserved_event(args.event_type):
        print(
            f"⛔ Event type '{args.event_type}' is RESERVED for orchestrator "
            f"core — cannot be emitted via CLI.\n"
            f"   Reserved prefixes: {', '.join(RESERVED_EVENT_PREFIXES)}\n"
            f"   Reserved exact: {', '.join(sorted(RESERVED_EVENT_EXACT))}\n\n"
            f"   Reserved suffixes: {', '.join(RESERVED_EVENT_SUFFIXES)}\n\n"
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
            print(f"\033[38;5;208mInvalid payload JSON: {e}\033[0m", file=sys.stderr)
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
        print("\033[38;5;208mNo active run\033[0m", file=sys.stderr)
        return 1
    if current["command"] != "vg:build":
        print(f"\033[38;5;208memit-crossai-terminal only valid in vg:build run, \033[0m"
              f"got {current['command']}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as e:
        print(f"\033[38;5;208mInvalid payload JSON: {e}\033[0m", file=sys.stderr)
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
                    f"\033[38;5;208mCannot declare exhausted — only {iter_count}/{max_iter} \033[0m"
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
                    "\033[38;5;208muser_override requires override.used event with crossai \033[0m"
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
        print("\033[38;5;208mNo active run. Call run-start first.\033[0m", file=sys.stderr)
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
    if current.get("active_step") == args.step_name:
        current.pop("active_step", None)
        current.pop("active_step_at", None)
        state_mod.write_active_run(current)
    print(f"marked: {args.namespace}/{args.step_name}")
    pretty = _render_taskboard(current, db.get_run(current["run_id"]), compact=True)
    if pretty:
        print(pretty)
    return 0


def cmd_verify_hash_chain(args) -> int:
    ok, broken_at, reason = db.verify_hash_chain(since_id=args.since_id or 0)
    if ok:
        print("hash-chain: OK")
        return 0
    print(f"\033[38;5;208mhash-chain BROKEN at id={broken_at}: {reason}\033[0m",
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
        print("\033[38;5;208mNo active run. Call run-start first.\033[0m", file=sys.stderr)
        return 1
    if current["command"] != "vg:build":
        print(f"\033[38;5;208mwave-start only valid in vg:build runs, not \033[0m"
              f"{current['command']}", file=sys.stderr)
        return 1

    # Check same wave already started
    existing = db.query_events(
        run_id=current["run_id"], event_type="wave.started",
    )
    for e in existing:
        try:
            if json.loads(e["payload_json"]).get("wave") == args.wave_n:
                print(f"\033[38;5;208mwave {args.wave_n} already started in this run\033[0m",
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
        print("\033[38;5;208mNo active run\033[0m", file=sys.stderr)
        return 1

    # Load evidence
    if args.evidence_file:
        try:
            raw = Path(args.evidence_file).read_text(encoding="utf-8")
        except Exception as e:
            print(f"\033[38;5;208mevidence file read error: {e}\033[0m", file=sys.stderr)
            return 1
    else:
        raw = sys.stdin.read()

    try:
        evidence_data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"\033[38;5;208mevidence_json parse error: {e}\033[0m", file=sys.stderr)
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
                print(f"\033[38;5;208mwave {args.wave_n} re-complete with DIFFERENT \033[0m"
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
        print("\033[38;5;208mwave-attribution validator missing\033[0m", file=sys.stderr)
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
        print(f"\033[38;5;208mwave {args.wave_n} BLOCK — wave-attribution rejected evidence\033[0m",
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
        print(f"\033[38;5;208mvalidator not found: {args.validator_name}\033[0m",
              file=sys.stderr)
        return 1

    current = state_mod.read_current_run()
    phase = args.phase or (current["phase"] if current else "")
    if not phase:
        print("\033[38;5;208m--phase required when no active run\033[0m", file=sys.stderr)
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
            cwd=str(_REPO_ROOT),
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
        print("\033[38;5;208m--phase required (no active run)\033[0m", file=sys.stderr)
        return 1

    reason = args.reason.strip()
    if len(reason) < 50:
        print(f"\033[38;5;208m--reason must be ≥50 chars (got {len(reason)}).\033[0m\n"
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
            "\033[38;5;208m--reason must cite an external artifact proving user sign-off.\033[0m\n"
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
            "\033[38;5;208m--reason contains shape-matching proof but NOTHING RESOLVES.\033[0m\n"
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
            f"\033[38;5;208mPhase {phase} has already used {prior_count}/\033[0m"
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

    repo = _REPO_ROOT
    phase_dirs = list((repo / ".vg" / "phases").glob(f"{phase}-*")) or \
                 list((repo / ".vg" / "phases").glob(f"{phase.zfill(2)}-*"))
    if not phase_dirs:
        print(f"\033[38;5;208mphase {phase} not found\033[0m", file=sys.stderr)
        return 1

    matrix = phase_dirs[0] / "GOAL-COVERAGE-MATRIX.md"
    if not matrix.exists():
        print(f"\033[38;5;208m{matrix} not found — run /vg:review first to create it\033[0m",
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
        print(f"\033[38;5;208mgoal {args.goal_id} not found in {matrix.name}\033[0m",
              file=sys.stderr)
        return 1

    # Append justification line near goal row (or in a dedicated MANUAL section)
    manual_entry = (f"\n- **{args.goal_id} MANUAL** ({datetime.now(timezone.utc).isoformat()}Z): "
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
    register = _REPO_ROOT / ".vg" / "OVERRIDE-DEBT.md"
    try:
        register.parent.mkdir(parents=True, exist_ok=True)
        with register.open("a", encoding="utf-8") as f:
            f.write(
                f"\n- id: PROMOTE-MANUAL-{phase}-{args.goal_id}\n"
                f"  logged_at: {datetime.now(timezone.utc).isoformat()}Z\n"
                f"  type: goal_promoted_manual\n"
                f"  phase: \"{phase}\"\n"
                f"  goal_id: {args.goal_id}\n"
                f"  quota: {prior_count + 1}/{PROMOTE_MANUAL_QUOTA_PER_PHASE}\n"
                f"  reason: \"{args.reason.replace(chr(34), chr(39))}\"\n"
                f"  status: active\n"
            )
    except Exception as e:
        print(
            f"\033[33mOVERRIDE-DEBT.md write FAILED: {e}\033[0m\n"
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
        print("\033[38;5;208mNo active run\033[0m", file=sys.stderr)
        return 1

    reason = args.reason.strip()
    if len(reason) < 50:
        print(
            f"\033[38;5;208m--reason must be ≥50 chars (got {len(reason)}).\033[0m\n"
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
            "\033[38;5;208m--reason must cite an external artifact (ticket/URL/PR/commit SHA).\033[0m\n"
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
            "\033[38;5;208m--reason shape-matches but NOTHING RESOLVES.\033[0m\n"
            "   Shape-only proof = audit breadcrumb, not real evidence.\n"
            "   Must contain ONE of:\n"
            "   - git SHA in this repo (verified via `git cat-file -t`)\n"
            "   - URL on trusted tracker (github.com/gitlab.com/bitbucket.org/\n"
            "     codeberg.org/linear.app + subdomains)\n"
            "   Fake tokens like `deadbee` or bogus URLs rejected.",
            file=sys.stderr,
        )
        return 2

    # v2.5.2 Phase O — allow-flag human gate. For --allow-* flags (vs
    # --skip-*), verify caller is on a TTY or has VG_HUMAN_OPERATOR env
    # set. AI subagents running headless without the env get blocked.
    if args.flag.startswith("--allow-") and _allow_flag_gate is not None:
        try:
            is_human, approver = _allow_flag_gate.verify_human_operator(
                args.flag,
            )
        except Exception:
            is_human, approver = True, None  # fail-open on gate error
        if not is_human:
            print(
                "\033[38;5;208m--allow-* flags require a human operator (TTY session \033[0m"
                "or VG_HUMAN_OPERATOR env var).\n"
                "   Rationale: these flags carry an approver identity for "
                "audit. AI subagents without an audited approver cannot "
                "authorize gate bypasses. If you're a human running "
                "headless, export VG_HUMAN_OPERATOR=<your-handle> before "
                "retrying.",
                file=sys.stderr,
            )
            try:
                db.append_event(
                    run_id=current["run_id"],
                    event_type="allow_flag.blocked",
                    phase=current["phase"],
                    command=current["command"],
                    actor="orchestrator",
                    outcome="BLOCK",
                    payload={"flag": args.flag,
                             "reason_head": args.reason[:120]},
                )
            except Exception:
                pass
            return 2
        try:
            _allow_flag_gate.log_allow_flag_used(
                flag_name=args.flag,
                approver=approver or "unknown",
                reason=args.reason,
                run_id=current["run_id"],
                phase=current["phase"],
                command=current["command"],
            )
        except Exception:
            pass

    # v2.5.2.10 — rubber-stamp guard for skip-crossai* overrides.
    # Observed in 7.14 → 7.15 → 7.16: reason "UI-only no API change, CrossAI
    # marginal value" copy-pasted across 3 phases. Each entry passed proof
    # gate (cited prior commit SHA), but the pattern was unchecked.
    # This guard fires when the same reason fingerprint appears on the same
    # flag across ≥2 DIFFERENT phases, blocking unless VG_ALLOW_RUBBER_STAMP
    # env is set (which itself logs a new meta-debt entry).
    _skip_flag_family = (
        "--skip-crossai",
        "--skip-crossai-build-loop",
        "skip-crossai",
        "skip-crossai-build-loop",
    )
    if args.flag in _skip_flag_family and _allow_flag_gate is not None:
        try:
            recent = db.query_events(event_type="override.used", limit=500)
            rs_hit, rs_count, rs_phases = \
                _allow_flag_gate.check_skip_flag_rubber_stamp(
                    recent, args.flag, args.reason,
                    current["phase"], threshold=2,
                )
        except Exception:
            rs_hit, rs_count, rs_phases = False, 0, []

        if rs_hit and os.environ.get("VG_ALLOW_RUBBER_STAMP") != "1":
            phases_str = ", ".join(rs_phases)
            print(
                f"\n⛔ Rubber-stamp detected — lý do skip CrossAI này đã dùng "
                f"y hệt ở {rs_count} phase trước: {phases_str}\n\n"
                f"   Flag:   {args.flag}\n"
                f"   Phase:  {current['phase']} (current)\n"
                f"   Reason dùng lại nguyên xi từ các phase trước → pattern\n"
                f"   copy-paste không chứng minh CrossAI thực sự không cần\n"
                f"   ở phase này.\n\n"
                f"   Cách sửa:\n"
                f"     1. Bỏ --skip-crossai → để CrossAI chạy thật (khuyến nghị)\n"
                f"     2. Viết reason khác hẳn, chứng minh cụ thể tại sao\n"
                f"        phase NÀY không cần CrossAI (VD: chỉ edit comments,\n"
                f"        không đổi logic, CrossAI zero signal)\n"
                f"     3. Bypass khẩn cấp: export VG_ALLOW_RUBBER_STAMP=1\n"
                f"        trước khi retry → log thêm 1 meta-debt entry\n",
                file=sys.stderr,
            )
            try:
                db.append_event(
                    run_id=current["run_id"],
                    event_type="override.rubber_stamp_blocked",
                    phase=current["phase"],
                    command=current["command"],
                    actor="orchestrator",
                    outcome="BLOCK",
                    payload={
                        "flag": args.flag,
                        "matching_phases": rs_phases,
                        "reason_head": args.reason[:120],
                    },
                )
            except Exception:
                pass
            return 2

        if rs_hit and os.environ.get("VG_ALLOW_RUBBER_STAMP") == "1":
            # Log bypass as meta-debt — user consciously skipped the guard
            try:
                db.append_event(
                    run_id=current["run_id"],
                    event_type="override.rubber_stamp_bypassed",
                    phase=current["phase"],
                    command=current["command"],
                    actor="user",
                    outcome="WARN",
                    payload={
                        "flag": args.flag,
                        "matching_phases": rs_phases,
                        "bypass_env": "VG_ALLOW_RUBBER_STAMP=1",
                    },
                )
            except Exception:
                pass
            print(
                f"\033[33mRubber-stamp BYPASSED qua VG_ALLOW_RUBBER_STAMP=1 — \033[0m"
                f"matching phases: {', '.join(rs_phases)}. Meta-debt ghi rồi.",
                file=sys.stderr,
            )

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
    register = _REPO_ROOT / ".vg" / "OVERRIDE-DEBT.md"
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
            f"\033[33mOVERRIDE-DEBT.md write FAILED (cmd_override): {e}\033[0m\n"
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
        print("\033[38;5;208mcurrent-run.json refs run_id not in runs table — \033[0m"
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


# Issue #21: required artifacts per command — mirrors event-reconciliation.py
# REQUIRED_ARTIFACTS so backfill validates with the same evidence the validator
# would later check. Kept inline to avoid cross-package imports.
_BACKFILL_REQUIRED_ARTIFACTS = {
    "vg:scope": ["CONTEXT.md"],
    "vg:blueprint": ["PLAN*.md", "API-CONTRACTS.md", "TEST-GOALS.md"],
    "vg:build": ["SUMMARY*.md"],
    "vg:review": ["RUNTIME-MAP.json", "GOAL-COVERAGE-MATRIX.md"],
    "vg:test": ["SANDBOX-TEST*.md"],
}


def cmd_run_backfill(args) -> int:
    """Backfill `run.completed` for runs that predate Stop-hook contract
    enforcement (issue #21).

    Projects upgrading across the contract-tightening point have in-flight
    phases whose blueprint/build/test runs have a `run.started` event but
    no `run.completed`. The `event-reconciliation` validator at
    `/vg:accept` blocks until they exist; re-running the original command
    would redo functionally-completed work and may diverge.

    This subcommand provides a paved path that honors the same evidence
    the validator already checks (artifact existence on disk). Strict
    pre-conditions:

      1. `run.started` event exists for the given --run-id
      2. No terminal event already recorded (run.completed/blocked/aborted)
      3. command is in the supported set (scope/blueprint/build/review/test)
      4. all required artifacts for that command exist in phase dir
      5. --reason is non-empty and ≥ 10 chars (avoid "test" reasons)

    On success: emits `run.completed` with `payload.backfill=true` and
    appends a critical-severity entry to OVERRIDE-DEBT.md (so the reviewer
    sees it during /vg:accept). Refuses otherwise with explicit reason.
    """
    import sqlite3 as _sqlite3
    import datetime as _dt

    if not args.reason or len(args.reason.strip()) < 10:
        print("\033[38;5;208m--reason required, ≥ 10 chars (audit trail).\033[0m", file=sys.stderr)
        return 1

    conn = _sqlite3.connect(str(db.DB_PATH))
    conn.row_factory = _sqlite3.Row
    try:
        started = conn.execute(
            "SELECT * FROM events WHERE run_id = ? AND event_type = 'run.started' "
            "ORDER BY id ASC LIMIT 1",
            (args.run_id,),
        ).fetchone()
        if not started:
            print(f"\033[38;5;208mrun.started event not found for run_id={args.run_id}\033[0m",
                  file=sys.stderr)
            print("   Run: vg-orchestrator query-events --event-type=run.started",
                  file=sys.stderr)
            return 2

        terminal = conn.execute(
            "SELECT id, event_type FROM events WHERE run_id = ? AND "
            "event_type IN ('run.completed', 'run.blocked', 'run.aborted') "
            "LIMIT 1",
            (args.run_id,),
        ).fetchone()
        if terminal:
            print(f"\033[38;5;208mrun {args.run_id[:8]} already has terminal event \033[0m"
                  f"id={terminal['id']} type={terminal['event_type']} — "
                  f"backfill rejected.", file=sys.stderr)
            return 3

        command = started["command"]
        phase = started["phase"]
    finally:
        conn.close()

    patterns = _BACKFILL_REQUIRED_ARTIFACTS.get(command)
    if patterns is None:
        print(f"\033[38;5;208mcommand {command!r} not in backfill table — supported: \033[0m"
              f"{sorted(_BACKFILL_REQUIRED_ARTIFACTS)}", file=sys.stderr)
        return 4

    # Locate phase dir. Phases live under .vg/phases/<NN>-<slug>/ usually,
    # but the prefix can vary; glob any dir starting with phase number.
    phases_root = _REPO_ROOT / ".vg" / "phases"
    if not phases_root.exists():
        print(f"\033[38;5;208m{phases_root} does not exist\033[0m", file=sys.stderr)
        return 5
    matches = sorted(p for p in phases_root.iterdir()
                     if p.is_dir() and (p.name == phase or
                                        p.name.startswith(f"{phase}-") or
                                        p.name.startswith(f"phase-{phase}-")))
    if not matches:
        print(f"\033[38;5;208mphase dir for phase={phase} not found under {phases_root}\033[0m",
              file=sys.stderr)
        return 5
    phase_dir = matches[0]

    missing = [p for p in patterns if not list(phase_dir.glob(p))]
    if missing:
        print(f"\033[38;5;208mMissing required artifacts for {command} in {phase_dir}:\033[0m",
              file=sys.stderr)
        for m in missing:
            print(f"   - {m}", file=sys.stderr)
        print("   Backfill refused — re-run the original command instead "
              "of backfilling empty work.", file=sys.stderr)
        return 6

    ts_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "backfill": True,
        "reason": args.reason,
        "verified_artifacts": list(patterns),
        "phase_dir": str(phase_dir.relative_to(_REPO_ROOT)),
        "ts_backfilled": ts_iso,
    }
    db.append_event(
        run_id=args.run_id,
        event_type="run.completed",
        phase=phase,
        command=command,
        actor="user-backfill",
        outcome="PASS",
        payload=payload,
    )

    # Audit trail in OVERRIDE-DEBT.md (critical severity — reviewer must see).
    register = _REPO_ROOT / ".vg" / "OVERRIDE-DEBT.md"
    register.parent.mkdir(parents=True, exist_ok=True)
    debt_id = (f"BF-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d%H%M%S')}"
               f"-{os.getpid()}")
    try:
        with register.open("a", encoding="utf-8") as f:
            f.write(
                f"\n- id: {debt_id}\n"
                f"  logged_at: {ts_iso}\n"
                f"  command: vg-orchestrator-run-backfill\n"
                f"  phase: \"{phase}\"\n"
                f"  flag: --run-backfill\n"
                f"  target_run_id: {args.run_id}\n"
                f"  target_command: {command}\n"
                f"  reason: \"{args.reason}\"\n"
                f"  severity: critical\n"
                f"  status: active\n"
            )
    except Exception as e:
        print(f"\033[33mOVERRIDE-DEBT.md write failed (audit trail incomplete): {e}\033[0m",
              file=sys.stderr)

    print(f"✓ run.completed backfilled for {args.run_id[:8]} "
          f"({command} phase={phase})")
    print(f"  Verified artifacts: {', '.join(patterns)}")
    print(f"  Debt entry: {debt_id} (severity=critical, "
          f"surfaces at /vg:accept)")
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


def cmd_quarantine(args) -> int:
    """Harness v2.6.1 (2026-04-26): quarantine inspection + recovery.

    Closes AUDIT.md D2 finding: 14 validators auto-disabled across runs
    with no operator-visible recovery path. Auto-recovery via PASS/WARN
    works ONLY when validator gets a chance to run — which it doesn't
    when entry["disabled"]=true skips it. Catch-22 broken by:

      status               — list all quarantined + last-fail timestamp
      re-enable            — manually clear one entry (with audit reason)
      force-enable-stale   — bulk clean any UNQUARANTINABLE entry that
                             leaked into the disabled list
    """
    state = _load_quarantine()

    if args.action == "status":
        # Phase E (2026-04-26): structured JSON output for dogfood-dashboard.py.
        # Backward compat: default still prints human-readable; only --json flips
        # the format. Exposes UNQUARANTINABLE tag per validator so dashboard can
        # render a "policy-locked" badge.
        if getattr(args, "json", False):
            entries = []
            for v_name in sorted(state.keys()):
                entry = state[v_name]
                entries.append({
                    "validator": v_name,
                    "disabled": bool(entry.get("disabled", False)),
                    "consecutive_fails": int(entry.get("consecutive_fails", 0)),
                    "last_fail_at": entry.get("last_fail_at"),
                    "unquarantinable": v_name in UNQUARANTINABLE,
                    "re_enabled_at": entry.get("re_enabled_at"),
                    "re_enabled_reason": entry.get("re_enabled_reason"),
                })
            disabled_count = sum(1 for e in entries if e["disabled"])
            stale = [e["validator"] for e in entries
                     if e["unquarantinable"] and e["disabled"]]
            payload = {
                "schema": "quarantine.status.v1",
                "total": len(entries),
                "disabled_count": disabled_count,
                "stale_unquarantinable": stale,
                "entries": entries,
            }
            print(json.dumps(payload, indent=2, default=str))
            return 0

        if not state:
            print("✓ No quarantine state — all validators healthy.")
            return 0
        print(f"━━━ Validator quarantine state ({len(state)} entries) ━━━")
        for v_name in sorted(state.keys()):
            entry = state[v_name]
            disabled = entry.get("disabled", False)
            consecutive = entry.get("consecutive_fails", 0)
            last_fail = entry.get("last_fail_at", "—")
            tags: list[str] = []
            if disabled:
                tags.append("DISABLED")
            if v_name in UNQUARANTINABLE:
                tags.append("UNQUARANTINABLE")
            tag_str = " ".join(f"[{t}]" for t in tags) or "[active]"
            print(f"  {v_name:<48s} {tag_str:<32s} fails={consecutive} last_fail={last_fail}")
        disabled_count = sum(1 for e in state.values() if e.get("disabled"))
        if disabled_count:
            print(f"\n{disabled_count} validator(s) DISABLED — re-enable via:")
            print("  python3 .claude/scripts/vg-orchestrator quarantine re-enable --validator <name> --reason '<audit text>'")
            stale = [v for v in state if v in UNQUARANTINABLE and state[v].get("disabled")]
            if stale:
                print(f"\n⚠ {len(stale)} UNQUARANTINABLE entries are stale-disabled — clean via:")
                print("  python3 .claude/scripts/vg-orchestrator quarantine force-enable-stale")
        return 0

    if args.action == "re-enable":
        if not args.validator:
            print("\033[38;5;208m--validator required for re-enable\033[0m", file=sys.stderr)
            return 2
        if args.validator not in state:
            print(f"⛔ '{args.validator}' not in quarantine state.", file=sys.stderr)
            return 1
        if not state[args.validator].get("disabled"):
            print(f"✓ '{args.validator}' is already enabled — no action.")
            return 0
        if not args.reason or len(args.reason) < 10:
            print(
                "\033[38;5;208m--reason required (min 10 chars). Re-enabling a \033[0m"
                "quarantined validator without justification defeats "
                "the audit trail.\n"
                "   Example: --reason 'transient infra issue 2026-04-22 "
                "— validator dependency restored'",
                file=sys.stderr,
            )
            return 2
        state[args.validator]["disabled"] = False
        state[args.validator]["consecutive_fails"] = 0
        state[args.validator]["re_enabled_at"] = _now_iso()
        state[args.validator]["re_enabled_reason"] = args.reason[:500]
        _save_quarantine(state)
        print(f"✓ Re-enabled {args.validator}")
        try:
            db.append_event(
                run_id="quarantine-recovery",
                event_type="quarantine.re_enabled",
                phase="",
                command="quarantine",
                actor="user",
                outcome="INFO",
                payload={
                    "validator": args.validator,
                    "reason": args.reason[:500],
                },
            )
        except Exception:
            pass
        return 0

    if args.action == "force-enable-stale":
        forced = _force_enable_unquarantinable_stale()
        if not forced:
            print("✓ No stale UNQUARANTINABLE entries — quarantine state clean.")
            return 0
        print(f"✓ Force-enabled {len(forced)} stale UNQUARANTINABLE entries:")
        for v in forced:
            print(f"  - {v}")
        try:
            db.append_event(
                run_id="quarantine-recovery",
                event_type="quarantine.force_enabled_stale",
                phase="",
                command="quarantine",
                actor="user",
                outcome="INFO",
                payload={"validators": forced, "count": len(forced)},
            )
        except Exception:
            pass
        return 0

    return 0


def cmd_calibrate(args) -> int:
    """Harness v2.6 Phase F (2026-04-26): severity calibration subcommand.

    Mirrors cmd_quarantine shape (status / apply / apply-all). Shells
    out to registry-calibrate.py for compute logic + manifest mutation,
    so this wrapper only handles argparse → subprocess + audit emission
    on success.

    Apply path is gated by:
      * --reason min 50 chars (same gate as --override-reason)
      * verify_human_operator() TTY-OR-HMAC (same gate as --allow-* flags)

    Both gates also live inside registry-calibrate.py, so direct CLI
    use is equally protected. This wrapper exists for operator UX
    (single discoverable orchestrator surface) + audit symmetry with
    quarantine.
    """
    import subprocess as _sub
    script = _REPO_ROOT / ".claude" / "scripts" / "registry-calibrate.py"
    if not script.exists():
        print(f"\033[38;5;208mregistry-calibrate.py not found at {script}\033[0m",
              file=sys.stderr)
        return 1

    # status branch — pure read, no gating, allow --json passthrough
    if args.action == "status":
        cmd_args = [sys.executable, str(script), "status"]
        if getattr(args, "lookback_phases", None) is not None:
            cmd_args += ["--lookback-phases", str(args.lookback_phases)]
        if getattr(args, "json", False):
            cmd_args.append("--json")
        result = _sub.run(cmd_args, cwd=str(_REPO_ROOT))
        return result.returncode

    # apply / apply-all / apply-decay branches — local gates BEFORE
    # shelling out so we emit a single coherent audit story per apply
    # attempt. apply-decay is Phase Q (v2.7); same gate surface as Phase
    # F apply (TTY/HMAC + reason >= 50 chars).
    if args.action in ("apply", "apply-all", "apply-decay"):
        reason = getattr(args, "reason", "") or ""
        if len(reason) < 50:
            print(
                "\033[38;5;208m--reason required (min 50 chars). Calibration \033[0m"
                "changes alter hard gate behavior — audit text must "
                "explain the data + operator verification.",
                file=sys.stderr,
            )
            return 2

        # TTY/HMAC gate — same surface as --override-reason / --allow-*
        try:
            sys.path.insert(
                0,
                str(_REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"),
            )
            from allow_flag_gate import verify_human_operator  # type: ignore
            is_human, approver = verify_human_operator("calibrate-apply")
        except Exception as e:
            print(
                f"\033[38;5;208mcaller-auth unavailable: {e}\033[0m",
                file=sys.stderr,
            )
            return 2
        if not is_human:
            print(
                f"\033[38;5;208mcalibrate {args.action} requires TTY OR signed \033[0m"
                "approver token (HMAC). AI subagents cannot self-mutate "
                "validator severity.\n"
                "   To approve as human:\n"
                "     a) Run from interactive shell (TTY) — auto-approved.\n"
                "     b) Mint signed token: python3 .claude/scripts/"
                "vg-auth.py approve --flag calibrate-apply\n"
                "        Then export VG_HUMAN_OPERATOR=<token>.",
                file=sys.stderr,
            )
            try:
                db.append_event(
                    run_id="calibrate-apply",
                    event_type="calibrate.blocked_caller_auth",
                    phase="",
                    command="calibrate",
                    actor="orchestrator",
                    outcome="BLOCK",
                    payload={
                        "action": args.action,
                        "suggestion_id": getattr(
                            args, "suggestion_id", ""
                        ),
                        "reason_head": reason[:120],
                        "reason_len": len(reason),
                    },
                )
            except Exception:
                pass
            return 2

        # Delegate to registry-calibrate.py — it re-runs the same gates
        # internally (defense in depth) but they should pass given we
        # just verified them here.
        cmd_args = [sys.executable, str(script), args.action]
        if args.action == "apply":
            sid = getattr(args, "suggestion_id", "") or ""
            if not sid:
                print("\033[38;5;208m--suggestion-id required for apply\033[0m",
                      file=sys.stderr)
                return 2
            cmd_args += ["--suggestion-id", sid]
        if args.action == "apply-decay":
            # Phase Q — pass through optional flags
            if getattr(args, "dry_run", False):
                cmd_args.append("--dry-run")
            decay_n = getattr(args, "decay_after_phases", None)
            if decay_n is not None:
                cmd_args += ["--decay-after-phases", str(decay_n)]
        cmd_args += ["--reason", reason]
        # Pass the verified approver downstream (subprocess inherits env)
        env = os.environ.copy()
        if approver and "VG_HUMAN_OPERATOR" not in env:
            env["VG_HUMAN_OPERATOR"] = approver
        # Allow legacy raw so downstream re-verify doesn't re-block on
        # token-format mismatch — orchestrator already gated above.
        env.setdefault("VG_ALLOW_FLAGS_LEGACY_RAW", "true")
        result = _sub.run(cmd_args, cwd=str(_REPO_ROOT), env=env)
        # Audit emission — best-effort, regardless of subprocess outcome.
        # Phase Q: apply-decay emits its own per-suggestion
        # `calibration.suggestion_decayed` events via registry-calibrate;
        # this wrapper additionally emits a summary event for
        # orchestrator-level audit symmetry with apply/apply-all.
        ok_event = {
            "apply": "calibrate.applied",
            "apply-all": "calibrate.applied",
            "apply-decay": "calibrate.decay_applied",
        }[args.action]
        fail_event = {
            "apply": "calibrate.apply_failed",
            "apply-all": "calibrate.apply_failed",
            "apply-decay": "calibrate.decay_failed",
        }[args.action]
        try:
            db.append_event(
                run_id="calibrate-apply",
                event_type=(ok_event if result.returncode == 0
                            else fail_event),
                phase="",
                command="calibrate",
                actor="user",
                outcome="INFO" if result.returncode == 0 else "BLOCK",
                payload={
                    "action": args.action,
                    "suggestion_id": getattr(args, "suggestion_id", ""),
                    "reason": reason[:500],
                    "operator_token": (approver or "tty")[:120],
                    "exit_code": result.returncode,
                    "dry_run": bool(getattr(args, "dry_run", False)),
                },
            )
        except Exception:
            pass
        return result.returncode

    print(f"\033[38;5;208munknown calibrate action: {args.action}\033[0m", file=sys.stderr)
    return 2


def _candidate_block(candidates_path: Path, cid: str) -> tuple[str, int, int] | None:
    """Locate fenced ```yaml block whose body contains `id: <cid>`.

    Returns (block_text, start_idx, end_idx) where start/end are byte offsets
    of the FULL fence (including ```yaml ... ``` markers) so caller can splice.
    None if not found. Stdlib-only — same regex pattern used by
    learn-tier-classify._parse_candidates.
    """
    if not candidates_path.exists():
        return None
    text = candidates_path.read_text(encoding="utf-8", errors="replace")
    fence_re = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)
    for m in fence_re.finditer(text):
        body = m.group(1)
        # Match `id: <cid>` at line start (allow leading spaces)
        if re.search(r"^\s*id\s*:\s*" + re.escape(cid) + r"\b",
                     body, re.MULTILINE):
            return (m.group(0), m.start(), m.end())
    return None


def cmd_learn(args) -> int:
    """Harness v2.6 Phase G (2026-04-26): /vg:learn TTY/HMAC parity gate.

    Phase F shipped TTY+HMAC on `cmd_calibrate apply`. Promoting a learn
    candidate is equally mutating — it injects the rule into every
    subsequent executor prompt. Without this gate, an AI subagent could
    fabricate a candidate, then `learn promote` it and persist behaviour
    change across phases. Same surface, same defense.

    Read-only actions (`--list`, `--review`) bypass the gate. Mutating
    actions (`promote`, `reject`) require:
      * --reason min 50 chars (audit text)
      * verify_human_operator() — TTY OR signed HMAC token
      * audit event emission on success/failure/blocked-attempt

    The actual file mutation is intentionally minimal in this wrapper:
      * promote — move candidate block from CANDIDATES.md → ACCEPTED.md
      * reject  — move candidate block from CANDIDATES.md → REJECTED.md
    Schema validation, conflict detection, and rule-file generation
    documented in `.claude/commands/vg/learn.md` flow remain the operator
    workflow surface. This subcommand is the auth-gated tail (the part
    that actually writes the new state).
    """
    bootstrap_dir = _REPO_ROOT / ".vg" / "bootstrap"
    candidates_path = bootstrap_dir / "CANDIDATES.md"
    accepted_path = bootstrap_dir / "ACCEPTED.md"
    rejected_path = bootstrap_dir / "REJECTED.md"

    # ─── Read-only actions — no auth gate ─────────────────────────────
    if args.action == "list":
        # Shell out to learn-tier-classify.py --all (existing read-only
        # entry point). No mutation, no gate.
        import subprocess as _sub
        script = _REPO_ROOT / ".claude" / "scripts" / "learn-tier-classify.py"
        if not script.exists():
            print(f"\033[38;5;208mlearn-tier-classify.py not found at {script}\033[0m",
                  file=sys.stderr)
            return 1
        cmd_args = [sys.executable, str(script), "--all"]
        if getattr(args, "include_retired", False):
            cmd_args.append("--include-retired")
        result = _sub.run(cmd_args, cwd=str(_REPO_ROOT))
        return result.returncode

    if args.action == "review":
        cid = (getattr(args, "candidate", "") or "").strip()
        if not cid:
            print(
                "\033[38;5;208m--candidate <L-XXX> required for review\033[0m",
                file=sys.stderr,
            )
            return 2
        block = _candidate_block(candidates_path, cid)
        if block is None:
            print(
                f"⛔ candidate '{cid}' not found in {candidates_path}",
                file=sys.stderr,
            )
            return 1
        print(block[0])
        return 0

    # ─── Mutating actions — auth-gated ────────────────────────────────
    if args.action not in ("promote", "reject"):
        print(f"\033[38;5;208munknown learn action: {args.action}\033[0m", file=sys.stderr)
        return 2

    cid = (getattr(args, "candidate", "") or "").strip()
    if not cid:
        print(
            f"\033[38;5;208m--candidate <L-XXX> required for {args.action}\033[0m",
            file=sys.stderr,
        )
        return 2

    reason = (getattr(args, "reason", "") or "").strip()
    if len(reason) < 50:
        print(
            f"\033[38;5;208m--reason required (min 50 chars) for {args.action}.\033[0m\n"
            f"   Promoting/rejecting a learn candidate alters the rule\n"
            f"   set injected into every subsequent executor prompt.\n"
            f"   Audit text must justify the decision concretely:\n"
            f"   evidence count, phases observed, conflict assessment.",
            file=sys.stderr,
        )
        return 2

    # TTY/HMAC gate — same surface as --override-reason and calibrate apply.
    try:
        sys.path.insert(
            0,
            str(_REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"),
        )
        from allow_flag_gate import verify_human_operator  # type: ignore
        is_human, approver = verify_human_operator(f"learn-{args.action}")
    except Exception as e:
        print(f"\033[38;5;208mcaller-auth unavailable: {e}\033[0m", file=sys.stderr)
        return 2

    if not is_human:
        print(
            f"\033[38;5;208mlearn {args.action} requires TTY OR signed approver \033[0m"
            "token (HMAC).\n"
            "   AI subagents cannot self-mutate the bootstrap rule set —\n"
            "   a fabricated candidate could be self-promoted into every\n"
            "   future executor prompt without human review.\n"
            "   To approve as human:\n"
            "     a) Run from interactive shell (TTY) — auto-approved.\n"
            "     b) Mint signed token: python3 .claude/scripts/"
            "vg-auth.py approve --flag learn-promote\n"
            "        Then export VG_HUMAN_OPERATOR=<token>.",
            file=sys.stderr,
        )
        # Forensic audit event for failed/unauthenticated attempt
        try:
            db.append_event(
                run_id=f"learn-{args.action}",
                event_type=f"learn.{args.action}_attempt_unauthenticated",
                phase="",
                command="learn",
                actor="orchestrator",
                outcome="BLOCK",
                payload={
                    "candidate_id": cid,
                    "reason_head": reason[:120],
                    "reason_len": len(reason),
                },
            )
        except Exception:
            pass
        return 2

    # Locate candidate block — required for both promote + reject
    block = _candidate_block(candidates_path, cid)
    if block is None:
        print(
            f"⛔ candidate '{cid}' not found in {candidates_path}",
            file=sys.stderr,
        )
        return 1
    block_text, b_start, b_end = block

    # Determine destination + tier (best-effort) for audit payload
    tier = ""
    m_tier = re.search(r"^\s*tier\s*:\s*([A-C])\b",
                       block_text, re.MULTILINE)
    if m_tier:
        tier = m_tier.group(1)

    # Splice block out of CANDIDATES.md
    src_text = candidates_path.read_text(encoding="utf-8", errors="replace")
    new_src = src_text[:b_start] + src_text[b_end:]
    # Trim consecutive blank lines left by removal
    new_src = re.sub(r"\n{3,}", "\n\n", new_src)

    # Append block + audit metadata to destination
    dest_path = accepted_path if args.action == "promote" else rejected_path
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # auth_method classification: HMAC token in env → "hmac"; else "tty".
    # verify_human_operator prefers TTY when a TTY exists, but when both
    # a TTY AND token are present we still tag as "tty" because it was the
    # primary auth signal returned. The env-token presence is the signal
    # for the HMAC/automation escape hatch documented in learn.md.
    _env_token = (os.environ.get("VG_HUMAN_OPERATOR", "") or "").strip()
    auth_method = "hmac" if (_env_token and "." in _env_token) else "tty"
    appended = (
        f"\n<!-- {args.action} L-id={cid} approver={approver or 'tty'} "
        f"auth={auth_method} at={timestamp} -->\n"
        f"{block_text}\n"
        f"<!-- reason: {reason[:500]} -->\n"
    )
    if dest_path.exists():
        dest_text = dest_path.read_text(encoding="utf-8", errors="replace")
        dest_path.write_text(dest_text.rstrip() + "\n" + appended,
                             encoding="utf-8")
    else:
        header = (
            f"# Bootstrap "
            f"{'ACCEPTED' if args.action == 'promote' else 'REJECTED'}\n\n"
        )
        dest_path.write_text(header + appended, encoding="utf-8")

    # Atomic-ish: write candidates.md last so a crash leaves dest+candidates
    # both populated rather than block lost (operator can dedupe by id).
    candidates_path.write_text(new_src, encoding="utf-8")

    # Audit event emission — success path
    try:
        db.append_event(
            run_id=f"learn-{args.action}",
            event_type=f"learn.{'promoted' if args.action == 'promote' else 'rejected'}",
            phase="",
            command="learn",
            actor="user",
            outcome="INFO",
            payload={
                "candidate_id": cid,
                "tier": tier,
                "reason": reason[:500],
                "operator_token": (approver or "tty")[:120],
                "auth_method": auth_method,
            },
        )
    except Exception:
        pass

    verb = "Promoted" if args.action == "promote" else "Rejected"
    print(f"✓ {verb} {cid} → {dest_path.relative_to(_REPO_ROOT)}")
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
    # vg:scope — see harness v2.6 entry below (de-dup) which adds
    # verify-human-language-response. Keeping single canonical entry
    # at bottom of dict for clarity. Python dict-literal: later key
    # wins on duplicate, but explicit is better than implicit.
    "vg:blueprint": ["phase-exists", "context-structure", "plan-granularity",
                     "task-goal-binding", "vg-design-coherence",
                     # Phase C (2026-04-23): warn when scoped mode tasks lack
                     # <context-refs> — executor won't know which decisions to
                     # inject. Advisory only (full fallback if missing).
                     "verify-context-refs",
                     # Phase D v2.5 (2026-04-23): FOUNDATION.md §9 Architecture
                     # Lock present + all 8 subsections substantive. Phase >=
                     # cutover (default 14) → HARD BLOCK if §9 missing.
                     # Pre-cutover phases get WARN (grandfather). UNQUARANTINABLE.
                     "verify-foundation-architecture",
                     # Phase D v2.5 (2026-04-23): SECURITY-TEST-PLAN.md schema
                     # check. Validates all 8 sections, enum values, cross-checks
                     # with FOUNDATION §9.5 (GDPR consistency). Mandatory from
                     # phase 14. critical+DAST=None → HARD BLOCK. UNQUARANTINABLE.
                     "verify-security-test-plan",
                     # Harness v2.6 (2026-04-25): platform-aware TEST-GOALS
                     # essentials registry — fires at 2b5 alongside skill-inline
                     # invocation for defense-in-depth. Manifest-driven via
                     # dispatch-manifest.json. Critical/important goals require
                     # platform-mandatory categories (table+filter+paging on
                     # web; list_screen+touch_target on mobile; ...).
                     "verify-test-goals-platform-essentials",
                     # Codex co-author lane catches missing TEST-GOALS coverage
                     # before CrossAI reviews the already-final artifact.
                     "verify-codex-test-goal-lane",
                     "verify-interface-standards",
                     "verify-crud-surface-contract",
                     # Harness v2.6 (2026-04-25): blueprint META-gate at 2c.
                     # Goal-plan coverage, endpoint-goal coverage, surface
                     # essentials, mutation Layer-4, state-machine guards,
                     # ORG 6-dim, rollback, UI states. Catches under-detailed
                     # blueprints before build wave spawn.
                     "verify-blueprint-completeness",
                     # Harness v2.6 (2026-04-25): contract-stage idempotency
                     # gate for critical-domain mutations. Catches missing
                     # **Idempotency:** declarations BEFORE build wave.
                     "verify-idempotency-coverage",
                     # Harness v2.6 (2026-04-25): auth flow integrity smoke.
                     # Login↔logout pair, **Auth:** declared, sensitive
                     # endpoints rate-limited, email-enumeration protection,
                     # reset token TTL. Skips silently when phase has no
                     # auth endpoints.
                     "verify-auth-flow-smoke",
                     # Harness v2.6 (2026-04-25): rollback procedure gate
                     # at planning stage. Migration profile or destructive
                     # PLAN tasks must declare rollback path. Catches
                     # missing recovery plan BEFORE build wave runs.
                     "verify-rollback-procedure"],
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
                 # B7.2 (2026-04-23): catch contract endpoints declared but
                 # never implemented. Static presence check across framework
                 # patterns (fastify/express/nest/hono). Previously drift only
                 # surfaced at review curl / test 5b (1+ hour later).
                 "verify-contract-runtime",
                 # B8.2 (2026-04-23): catch dormant schemas — Zod/Pydantic/Joi
                 # imported in route file but never .parse()'d. Contract
                 # declares validation but runtime silently accepts anything.
                 "verify-input-validation",
                 # B8.3 (2026-04-23): contract must declare **Auth:** per
                 # endpoint so downstream gates know authz intent. Unclear
                 # declarations block; mutation-generic warns. Runtime
                 # cross-role boundary test deferred (needs live API).
                 "verify-authz-declared",
                 "verify-interface-standards",
                 "verify-api-docs-coverage",
                 "verify-crud-surface-contract",
                 # OHOK-7 (2026-04-22): MANDATORY post-build CrossAI loop.
                 # Must see events.db evidence of ≥1 crossai iteration +
                 # a terminal event (loop_complete / loop_exhausted /
                 # loop_user_override). No way to pass this gate without
                 # actually running .claude/scripts/vg-build-crossai-loop.py.
                 "build-crossai-required",
                 # Graphify is build context infrastructure, not a README
                 # promise. If enabled + installed, /vg:build must cold-build
                 # or refresh graphify and emit events.db evidence before PASS.
                 "build-graphify-required",
                 # Capsule is the anti lazy-read contract. pre-executor-check.py
                 # may resolve perfect task/API/goals/CRUD context, but build is
                 # invalid unless the executor prompt literally receives it.
                 "verify-task-context-capsule",
                 # v2.5 Phase A (2026-04-23): post-wave independent verify.
                 # Per-wave subprocess re-run of typecheck/tests/contract
                 # catches "executor claimed PASS but actually failed"
                 # divergence before next wave stacks on broken state.
                 # Invoked by build.md step 8 sub-step 4b, UNQUARANTINABLE.
                 "wave-verify-isolated",
                 # v2.5 Phase B (2026-04-23): goal-level OWASP security
                 # declaration check. critical_goal_domain missing
                 # owasp_top10_2021 → HARD BLOCK; mutation endpoint
                 # missing csrf/rate_limit → HARD BLOCK. UNQUARANTINABLE.
                 "verify-goal-security",
                 # v2.5 Phase B.2 (2026-04-23): perf_budget declaration.
                 # Mutation endpoint missing budget → HARD BLOCK.
                 # List GET missing p95_ms → HARD BLOCK.
                 "verify-goal-perf",
                 # v2.5 Phase B.3 (2026-04-23): project-wide security
                 # baseline — TLS version, headers middleware,
                 # secrets in .env.example, cookie flags, CORS, lockfile.
                 # Fires per-phase at build (idempotent grep scan).
                 "verify-security-baseline",
                 # Harness v2.6 (2026-04-25): SAST log-leak detection.
                 # Source code MUST NOT pass Authorization headers,
                 # req.body, password, token, secret, raw email to
                 # logger.* / console.log calls. Sanitization middleware
                 # (pino-redact, winston mask) required.
                 "verify-log-hygiene",
                 # Harness v2.6 (2026-04-25): OAuth PKCE enforcement.
                 # Public clients (SPA/mobile) MUST use code_challenge=S256
                 # + state + nonce (OIDC). Confidential server WARN-only.
                 "verify-oauth-pkce-enforcement",
                 # Harness v2.6 (2026-04-25): JWT TTL + signing algo gate.
                 # Access ≤15min, refresh ≤7d rotated, RS256/ES256 (NOT
                 # HS256-shared-weak), revocation mechanism. Catches the
                 # 30d access-token + HS256 misconfigurations real on
                 # this repo's auth.routes.ts.
                 "verify-jwt-session-policy",
                 # Harness v2.6 (2026-04-25): 2FA gate. Self-skips when
                 # phase doesn't touch auth (verdict=SKIP → PASS).
                 # Otherwise asserts TOTP/SMS fallback policy declared.
                 "verify-2fa-gate",
                 # Harness v2.6 (2026-04-25): dependency CVE budget.
                 # Critical CVE in lockfile = BLOCK; high CVE configurable.
                 "verify-dependency-vuln-budget",
                 # Harness v2.6 (2026-04-25): anti grandfather-marker
                 # forge. Phase >= cutover MUST NOT create legacy-bootstrap
                 # manifest entries (would be self-forging the grandfather
                 # exemption).
                 "verify-no-legacy-manifest-creation",
                 # Harness v2.6 (2026-04-25): per-wave executor context
                 # scope check — orchestrator auto-injects --run-id +
                 # --plan-file. Validates scoped <context-refs> mode.
                 "verify-executor-context-scope",
                 # Harness v2.6 (2026-04-25): clean-failure-state check —
                 # auto-injects --run-id. Validates UI components handle
                 # empty/loading/error state, no bare-null returns.
                 "verify-clean-failure-state",
                 # Harness v2.6 (2026-04-25): anti --no-verify bypass.
                 # Source code MUST NOT contain --no-verify / --no-gpg-sign /
                 # HUSKY=0. Pre-commit hooks (typecheck + commit-attribution
                 # + secrets-scan) are non-negotiable.
                 "verify-no-no-verify",
                 # Harness v2.6 (2026-04-25): design-ref honor check.
                 # Tasks with <design-ref> must point to existing assets;
                 # commits must cite slug. Phase 7.14.3 retro fix.
                 "verify-design-ref-honored"],
    # Review doesn't enforce goal-coverage — tests land in /vg:test, so review
    # always fails before tests exist. Enforcement moved to /vg:test + /vg:accept
    # where tests MUST exist. Review's in-skill 0b gate warns advisory only.
    # runtime-evidence: BLOCK if Playwright specs exist but not executed
    # (anti-rationalization — prevents AI from certifying "code evidence only").
    # OHOK v2 Day 3 — review-skip-guard catches skipped_no_browser with
    # critical UI goals (phase 14 dogfood pattern). deferred-evidence catches
    # @deferred-* tags without ticket link.
    # SEC-1 (2026-04-23): Security validators fire at review as part of
    # phase1_code_scan. Previously B8 validators (secrets/input/authz) only
    # ran at build run-complete + pre-push — users running /vg:review saw
    # zero security signal. Now review is a true security checkpoint.
    # B9.1 (2026-04-23): accessibility-scan runs alongside security — UX
    # violations blocking before browser discovery spawn.
    "vg:review": ["phase-exists", "runtime-evidence", "review-skip-guard",
                  "secrets-scan", "verify-input-validation",
                  "verify-authz-declared",
                  "verify-interface-standards",
                  "accessibility-scan",
                  "verify-static-assets-runtime",
                  # B9.2 (2026-04-23): i18n coverage — catches missing
                  # locale keys + hardcoded strings before review browser
                  # discovery. Config-driven (allowlist via .vg/).
                  "i18n-coverage",
                  # B11.2 (2026-04-23): cross-step telemetry feedback —
                  # surface recent build BLOCK/FAIL events so phase 3
                  # fix-loop pre-populates instead of re-discovering.
                  # Non-blocking WARN (build already blocked them).
                  "build-telemetry-surface",
                  # v2.5 Phase B (2026-04-23): goal-level OWASP check at
                  # review entry — catches missing security declarations
                  # before browser discovery + defense-in-depth with build.
                  "verify-goal-security",
                  # v2.5 Phase B.2 (2026-04-23): perf_budget check at review.
                  "verify-goal-perf",
                  "verify-crud-surface-contract",
                  # v2.32.1: block shallow CRUD review evidence. A mutation
                  # goal cannot be READY if RUNTIME-MAP only observed a list
                  # page without POST/PUT/PATCH/DELETE + persistence proof.
                  "verify-runtime-map-crud-depth",
                  # v2.5 Phase B.3 (2026-04-23): project-wide security baseline.
                  "verify-security-baseline",
                  # Harness v2.6 (2026-04-25): test spec selectors must
                  # match impl exposure (data-testid / data-column-id /
                  # aria-current / role=status / input[name]). Catches
                  # Wave-N spec authoring that drifts from Wave-(N-1) impl.
                  "verify-spec-selectors-against-impl",
                  # Harness v2.6 (2026-04-25): user-facing prose narration
                  # must read as a story (preamble + examples + EN gloss).
                  # Reviews summarize work — terse confirmations skip
                  # context the user needs.
                  "verify-human-language-response",
                  # Harness v2.6 (2026-04-25): no hardcoded SSH/VPS paths
                  # in source/skill/command files (must reference
                  # config.environments.<env>.{run_prefix,project_path}).
                  # Allowlist Ansible inventory + Cloudflare DNS configs.
                  "verify-no-hardcoded-paths",
                  # Harness v2.6 (2026-04-25): anti --no-verify at review.
                  "verify-no-no-verify",
                  # Harness v2.6 (2026-04-25): design-ref honor at review.
                  "verify-design-ref-honored"],
    "vg:test": ["phase-exists", "goal-coverage", "runtime-evidence",
                "deferred-evidence",
                # SEC-2 (2026-04-23): test pipeline also runs security pre-ship.
                # Duplication with review is intentional defense-in-depth —
                # review fixes discovered issues, test re-verifies before UAT.
                "secrets-scan", "verify-input-validation",
                "verify-authz-declared",
                "verify-interface-standards",
                # B12.1 (2026-04-23): mutation spec 3-layer verify — extends
                # R7 console check from generated-only → all *.spec.ts.
                # Catches ghost-save bugs (toast shown but data lost on reload).
                "mutation-layers",
                # B11.1 (2026-04-23): cross-step telemetry feedback at test
                # entry. Defense-in-depth for "NOT_SCANNED không được defer
                # sang /vg:test" rule — if review exit with intermediate-status
                # goals (override/crash/bug), test blocks with actionable hints.
                "not-scanned-replay",
                # v2.5 Phase B.2+B.3 (2026-04-23): defense-in-depth security +
                # perf gates at test pipeline. Duplicate with review per SEC-1
                # pattern — review fixes, test re-verifies before UAT.
                "verify-goal-perf",
                "verify-crud-surface-contract",
                # Defense-in-depth for old RUNTIME-MAP/GOAL-COVERAGE artifacts:
                # test must not replay a list-only sequence for a CRUD goal.
                "verify-runtime-map-crud-depth",
                "verify-security-baseline",
                # v2.5 Phase B.5 (2026-04-23): DAST report severity routing.
                # Report path via env or default PHASE_DIR/dast-report.json.
                # Non-blocking if report missing (advisory).
                "dast-scan-report",
                # Harness v2.6 (2026-04-25): spec selectors vs impl —
                # also runs at test step 5d-pre as defense-in-depth. Test
                # pipeline catches selectors that survived review phase 1.
                "verify-spec-selectors-against-impl",
                # Harness v2.6 (2026-04-25): idempotency check at test stage
                # — defense-in-depth. Build phase declares contract,
                # test phase verifies via runtime double-submit (skill
                # vg-test step 5b-2 already does runtime; this catches
                # missing declaration if build skipped).
                "verify-idempotency-coverage",
                # Harness v2.6 (2026-04-25): auth flow smoke at test phase.
                # Login form HTML/JSX shape + contract integrity.
                "verify-auth-flow-smoke",
                # Harness v2.6 (2026-04-25): runtime cookie flag probe.
                # Auto-skips when VG_TARGET_URL env not set; vg-test
                # step 5a deploy sets it before this dispatches. Asserts
                # auth cookies have Secure + HttpOnly + SameSite at
                # runtime (catches CDN/proxy header strip).
                "verify-cookie-flags-runtime",
                # Harness v2.6 (2026-04-25): runtime security headers
                # probe. Asserts HSTS / X-Content-Type-Options /
                # X-Frame-Options / CSP at runtime. Same auto-skip
                # behavior on missing VG_TARGET_URL.
                "verify-security-headers-runtime",
                "verify-static-assets-runtime",
                # Harness v2.6 (2026-04-25): authz negative-paths probe.
                # Wrong-role → 403 verification per endpoint. Auto-skips
                # without VG_TARGET_URL or fixtures file.
                "verify-authz-negative-paths",
                # Harness v2.6 (2026-04-25): VPS deploy evidence — phase
                # claiming deploy/running/installed must have curl 200
                # / pm2 list / health-check in SUMMARY. Closes "execute
                # not just files" rule from CLAUDE.md (Phase 0 incident).
                "verify-vps-deploy-evidence",
                # Harness v2.6 (2026-04-25): anti --no-verify at test stage.
                "verify-no-no-verify"],
    # OHOK v2 Day 4 — add acceptance-reconciliation as final gate.
    # Catches: critical goals not passing, HARD override-debt active,
    # scope branching unresolved, step markers missing after build waves.
    "vg:accept": ["phase-exists", "event-reconciliation",
                  "override-debt-balance", "runtime-evidence",
                  "commit-attribution",
                  "acceptance-reconciliation",
                  # Phase D v2.5 (2026-04-23): final gate — STP schema must
                  # be valid before a phase is accepted as complete.
                  "verify-security-test-plan",
                  "verify-crud-surface-contract",
                  # Harness v2.6 (2026-04-25): final UAT prose narration
                  # must read as a story (user-facing summary must include
                  # context, examples, EN-term gloss).
                  "verify-human-language-response",
                  # Harness v2.6 (2026-04-25): final no-hardcoded-paths
                  # gate at accept — catches drift introduced after build
                  # (manual edits, late-stage hotfixes).
                  "verify-no-hardcoded-paths",
                  # Harness v2.6 (2026-04-25): final container hardening
                  # gate before phase ship. Dockerfile/compose: non-root
                  # user, read-only rootfs, port whitelist, AppArmor/
                  # SELinux profile. WARN if no Dockerfile (project may
                  # not containerize); BLOCK on hardening regression.
                  "verify-container-hardening",
                  # Harness v2.6 (2026-04-25): SAST log-hygiene gate at
                  # accept — final check that no source/recent commit
                  # logs Authorization / password / raw token.
                  "verify-log-hygiene",
                  # Harness v2.6 (2026-04-25): runtime cookie flags +
                  # security headers — final live probe before phase
                  # ship. Auto-skips when VG_TARGET_URL not set
                  # (production deploy MUST set it).
                  "verify-cookie-flags-runtime",
                  "verify-security-headers-runtime",
                  "verify-static-assets-runtime",
                  # Harness v2.6 (2026-04-25): bootstrap rule promotion
                  # behavioral check — promoted Tier-A rule text must
                  # appear in ≥1 captured prompt of next-phase run.
                  # Anti fake-promote.
                  "verify-learn-promotion",
                  # Harness v2.6 (2026-04-25): every /vg:* command must
                  # declare input contract + emit documented telemetry
                  # events. Catches drift between code and contract.
                  "verify-command-contract-coverage",
                  # Harness v2.6 (2026-04-25): aggregated security baseline
                  # — orchestrates cookie-flags + security-headers + dep-
                  # vuln + container-hardening into one verdict. Auto-skips
                  # when VG_TARGET_URL not set.
                  "verify-security-baseline-project",
                  # Harness v2.6 (2026-04-25): override-debt SLA audit.
                  # Open OVERRIDE-DEBT entries past --max-days (default 30)
                  # → WARN. Operator should review/clear/extend.
                  "verify-override-debt-sla",
                  # Harness v2.6 (2026-04-25): allow-flag audit. Detects
                  # rubber-stamping (same flag, no review) / approval
                  # fatigue / repeat-flag use over events.db lookback
                  # window. WARN-level — ops behavior signal.
                  "verify-allow-flag-audit",
                  # Harness v2.6 (2026-04-25): validator drift meta-check.
                  # Always-pass high-FP / never-fires / perf regressions
                  # surfaced as WARN findings. Operator decides demotion
                  # / disable / optimize.
                  "verify-validator-drift",
                  # Harness v2.6 (2026-04-25): .codex/skills/ mirrors stay
                  # synced with .claude/commands/vg/ source-of-truth.
                  # WARN — operator should /vg:sync to align mirrors.
                  "verify-codex-skill-mirror-sync",
                  # Harness v2.6 (2026-04-25): narration coverage audit —
                  # detects hardcoded English Evidence/messages instead
                  # of i18n keys. BLOCK — slows i18n rollout if not enforced.
                  "verify-narration-coverage",
                  # Harness v2.6 (2026-04-25): artifact freshness audit —
                  # auto-injects --run-id. Catches stale CONTEXT/PLAN/
                  # API-CONTRACTS relative to source.
                  "verify-artifact-freshness",
                  # Harness v2.6 (2026-04-25): bootstrap carry-forward —
                  # auto-injects --run-id. Verifies promoted rules
                  # propagate across phase transitions.
                  "verify-bootstrap-carryforward",
                  # Harness v2.6 (2026-04-25): review loop evidence —
                  # auto-injects --phase-dir. Asserts review iter pairs
                  # have verifiable git delta (anti forged-iteration).
                  "verify-review-loop-evidence",
                  # Harness v2.6 (2026-04-25): CrossAI multi-CLI consensus
                  # check. Auto-resolves glob from .vg/phases/<phase>/
                  # crossai/*.xml. WARN on disagreement.
                  "verify-crossai-multi-cli",
                  # Harness v2.6 (2026-04-25): DAST waiver approver gate.
                  # Auto-resolves triage file from .vg/phases/<phase>/
                  # dast-triage.{yaml,json}. WARN on rubber-stamping.
                  "verify-dast-waive-approver",
                  # Harness v2.6 (2026-04-25): VPS deploy evidence at accept.
                  # Defense-in-depth — same check as test stage.
                  "verify-vps-deploy-evidence",
                  # Harness v2.6 (2026-04-25): Vietnamese summary coverage.
                  # User-facing rule: each accepted phase must have
                  # substantive XX-SUMMARY-VI.md (≥500 bytes, ≥3 VN
                  # diacritics, ≥2 headings). Anti English-only ship.
                  "verify-summary-vi-coverage",
                  # Harness v2.6 (2026-04-25): step markers final audit.
                  # Universal rule: every <step> writes .step-markers/<step>.done
                  # as final action. Missing marker = step skipped silently.
                  "verify-step-markers",
                  # Harness v2.6 (2026-04-25): rollback procedure final
                  # check at accept (defense-in-depth with blueprint stage).
                  "verify-rollback-procedure",
                  # Harness v2.6 (2026-04-25): anti --no-verify final gate.
                  # Catches drift introduced after build/review.
                  "verify-no-no-verify",
                  # Harness v2.6 (2026-04-25): design-ref honor final gate.
                  # Catches drift introduced after build/review.
                  "verify-design-ref-honored",
                  # Harness v2.6 (2026-04-25): RULES-CARDS.md fresh check.
                  # Cards extracted from skill bodies — must regenerate
                  # when skills change. Advisory WARN.
                  "verify-rule-cards-fresh",
                  # Harness v2.6 Phase D (2026-04-26): rule-phase scope check.
                  # WARN when an accepted rule has fired in 3+ distinct
                  # phases without an explicit phase_pattern (silent
                  # global drift risk). Hygiene only — never BLOCK.
                  "verify-rule-phase-scope",
                  # Phase 16 hot-fix v2.11.1 (cross-AI consensus BLOCKer 5):
                  # task-schema classifies xml/heading/mixed PLAN tasks +
                  # XML acceptance frontmatter requirement. Mode-aware
                  # (legacy WARN-only by default).
                  "verify-task-schema",
                  # Phase 16 hot-fix v2.11.1: crossai-output enforces
                  # structured-edits contract on cross-AI enrichment diff
                  # (long prose escape via <context-refs>, cross_ai_enriched
                  # frontmatter flag). Validator self-skips when no
                  # PLAN/CONTEXT diff vs --diff-base.
                  "verify-crossai-output"],
    # Add scope command — was missing from orchestrator dispatch (only
    # COMMAND_VALIDATORS keys hit dispatcher; vg:scope previously had
    # "phase-exists, context-structure" hardcoded but no human-language
    # gate. Harness v2.6 fix: scope-round answers must read as stories.
    "vg:scope": ["phase-exists", "context-structure",
                 # Harness v2.6 (2026-04-25): scope rounds emit user-facing
                 # prose. Validator scores text on sentence ratio, examples,
                 # preamble, EN-term gloss. Schema-dump answers fail.
                 "verify-human-language-response",
                 # Phase 16 hot-fix v2.11.1 (cross-AI consensus BLOCKer 5):
                 # crossai-output for scope when --crossai enrichment ran.
                 # Self-skips when no diff (no enrichment).
                 "verify-crossai-output"],
}


QUARANTINE_FILE = _REPO_ROOT / ".vg" / "validator-quarantine.json"
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
    "build-graphify-required",    # graphify enabled => post-build refresh evidence
    "verify-task-context-capsule", # executor prompt must receive compact task context
    "verify-codex-test-goal-lane", # blueprint must reconcile Codex goal proposal
    "context-structure",          # scope contract integrity
    # v2.5 Phase A (2026-04-23): post-wave subprocess divergence check.
    # AI cannot skip this — would defeat entire purpose of independent verify.
    "wave-verify-isolated",
    # v2.5 Phase B (2026-04-23): goal-level security declaration. AI
    # can't game this by repeatedly failing to trigger quarantine —
    # security checks must always fire.
    "verify-goal-security",
    # v2.5 Phase B.2 (2026-04-23): perf_budget declaration.
    "verify-goal-perf",
    # v2.5 Phase B.3 (2026-04-23): project-wide security baseline.
    "verify-security-baseline",
    # v2.5 Phase D (2026-04-23): FOUNDATION.md §9 Architecture Lock.
    # Architecture constraints are critical — AI cannot game this by
    # failing 3x to trigger quarantine. §9 gates blueprint planner.
    "verify-foundation-architecture",
    # v2.5 Phase D (2026-04-23): SECURITY-TEST-PLAN.md schema validation.
    # critical+DAST=None is a hard security mismatch — AI cannot bypass
    # by repeatedly failing to trigger quarantine.
    "verify-security-test-plan",
    # Phase 7.14.3 retro (2026-04-25): catches test-vs-impl selector drift
    # at /vg:review step 1 (code scan) and /vg:test step 5d-pre. Wave-N
    # spec authors can't ship selectors that the Wave-(N-1) impl doesn't
    # expose. AI can't game this by repeatedly failing — would let drift
    # land in main and surface 1+ hour into /vg:test runtime.
    "verify-spec-selectors-against-impl",
    # Phase 7.14.3 retro (2026-04-25): platform-aware TEST-GOALS coverage.
    # Forces every phase touching a list/table/form/auth flow to declare
    # goals covering the platform's mandatory essentials (filter, paging,
    # column count, sort, Layer-4 mutation reload, state guards, ...).
    # AI can't slip ship a phase that never wrote a paging goal.
    "verify-test-goals-platform-essentials",
    "verify-crud-surface-contract",
    "verify-interface-standards",
    "verify-runtime-map-crud-depth",
    # Phase 7.14.3 retro (2026-04-25): user-facing prose must read as a
    # story (preamble → details → close), not bullet/schema dumps.
    # Validator scores text on sentence ratio, examples, EN-term gloss.
    # AI can't pass terse confirmations that skip context the user needs.
    "verify-human-language-response",
    # Harness v2.6 (2026-04-25): meta-gate over the whole blueprint —
    # PLAN + API-CONTRACTS + TEST-GOALS coverage, ORG 6-dimensions,
    # mutation Layer-4, state-machine guards, empty/loading/error UI
    # states, rollback for destructive operations. Per user feedback
    # "blueprint thiếu chi tiết → toàn bộ khâu sau lỏng". AI cannot
    # ship under-detailed blueprints by repeatedly failing the gate.
    "verify-blueprint-completeness",
    # Harness v2.6 (2026-04-25): critical-domain mutation idempotency
    # contract gate. Auth/billing/payout/payment/transaction mutations
    # without **Idempotency:** declaration → BLOCK. Anti retry-storm
    # / double-charge / duplicate-session class of bugs. UNQUARANTINABLE
    # because retry-safety is a hard correctness property, not an
    # advisory — AI must not game this by failing 3x.
    "verify-idempotency-coverage",
    # Harness v2.6 (2026-04-25): JWT signing algo + TTL policy. Found
    # real HS256 + 30d-access-token misconfig on this repo's auth code.
    # UNQUARANTINABLE — JWT weak-algo / long-TTL bypass = full account
    # compromise risk.
    "verify-jwt-session-policy",
    # Harness v2.6 (2026-04-25): anti grandfather-marker forge. Phase
    # past cutover MUST NOT create legacy-bootstrap manifest entries.
    # UNQUARANTINABLE — letting AI fail 3x to disable would let it
    # re-introduce the grandfather exemption to itself.
    "verify-no-legacy-manifest-creation",
    # Harness v2.6.1 audit (2026-04-26): 5 security-critical validators
    # were wired in COMMAND_VALIDATORS but missed UNQUARANTINABLE.
    # If AI subagent intentionally fails them 3x → quarantine →
    # auto-skip on iteration 4 = silent bypass of security gates.
    # All 5 protect against contract/auth/recovery class of bugs;
    # quarantine pattern unacceptable for these.
    "verify-authz-declared",          # endpoint **Auth:** declaration
    "verify-auth-flow-smoke",         # login/logout pair, rate-limit, reset-token TTL
    "verify-oauth-pkce-enforcement",  # SPA/mobile PKCE S256
    "verify-rollback-procedure",      # destructive PLAN tasks need rollback path
    "verify-2fa-gate",                # 2FA declared+missing impl = false advertising

    # Harness v2.6.1 Batch F audit (2026-04-26): 11 BLOCK validators wired
    # in COMMAND_VALIDATORS but missing UNQUARANTINABLE. Same pattern as
    # Batch A — AI subagent could fail 3x to disable then bypass on
    # iteration 4. All 11 protect against security/correctness class of
    # bugs; quarantine pattern unacceptable.
    "verify-container-hardening",         # container security (RUN as root, secrets in image)
    "verify-cookie-flags-runtime",        # HttpOnly/Secure/SameSite
    "verify-dast-waive-approver",         # DAST signoff for critical phases
    "verify-dependency-vuln-budget",      # CVE threshold budget
    "verify-no-hardcoded-paths",          # paths/credentials leak in code
    "verify-no-no-verify",                # pre-commit hook bypass (test_no_no_verify covers)
    "verify-security-baseline-project",   # TLS/headers/CORS/lockfile baseline
    "verify-security-headers-runtime",    # runtime CSP/HSTS/X-Frame-Options
    "verify-static-assets-runtime",       # runtime CSS MIME/body sanity
    "verify-allow-flag-audit",            # override flag misuse audit
    "verify-vps-deploy-evidence",         # actual deploy ran (anti "build-only" forge)
    "verify-clean-failure-state",         # recovery state integrity post-crash

    # Harness v2.7 Phase P (2026-04-26): SKILL.md structural invariants +
    # RULES-CARDS-MANUAL.md schema gate. Single validator, single parser,
    # single CI gate. AI subagent failing 3x to disable this gate cannot
    # be allowed — skill drift (step numbering gap, missing markers,
    # SKILL⇄commands desync) silently breaks the orchestrator's marker-
    # check loop. Even at initial WARN severity (R11 graceful rollout)
    # the gate must always fire.
    "verify-skill-invariants",
}


# Per-validator extra-arg injection. Orchestrator passes `--phase <N>` to
# every validator. Some validators ALSO need run-id / phase-dir / plan-file
# / target-url which orchestrator can derive. This map declares those
# extras so dispatch supplies them automatically.
#
# Format: validator_name → list of (flag, source) tuples where source ∈
#   {"run_id", "phase_dir", "plan_file", "target_url", "events_db"}
VALIDATOR_EXTRA_ARGS: dict[str, list[tuple[str, str]]] = {
    "verify-artifact-freshness":     [("--run-id", "run_id")],
    "verify-clean-failure-state":    [("--run-id", "run_id")],
    "verify-bootstrap-carryforward": [("--run-id", "run_id")],
    "verify-executor-context-scope": [("--run-id", "run_id"),
                                      ("--plan-file", "plan_file")],
    "verify-review-loop-evidence":   [("--phase-dir", "phase_dir")],
    "verify-static-assets-runtime":  [("--target-url", "target_url")],
    # Phase-dir-aware validators that already accept --phase don't need
    # extras here; they resolve phase_dir from --phase internally.
}


def _resolve_extra_arg(source: str, run_id: str, phase: str) -> str | None:
    """Compute the actual value for an extra-arg source key."""
    repo_root = _REPO_ROOT
    if source == "run_id":
        return run_id
    if source == "phase_dir":
        # Resolve phase dir using same logic as phase-resolver.sh
        phases_dir = repo_root / ".vg" / "phases"
        if not phases_dir.exists():
            return None
        for p in phases_dir.iterdir():
            if not p.is_dir():
                continue
            name = p.name
            # Match P{phase}-* OR {phase}-* OR exact phase
            if name == phase or name.startswith(f"{phase}-") or name.startswith(f"{phase.zfill(2)}-"):
                return str(p)
        return None
    if source == "plan_file":
        phase_dir = _resolve_extra_arg("phase_dir", run_id, phase)
        if phase_dir:
            for p in Path(phase_dir).glob("PLAN*.md"):
                return str(p)
        return None
    if source == "target_url":
        # Read from VG_TARGET_URL env (set by deploy step)
        return os.environ.get("VG_TARGET_URL")
    if source == "events_db":
        db = repo_root / ".vg" / "events.db"
        return str(db) if db.exists() else None
    return None


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


def _force_enable_unquarantinable_stale() -> list[str]:
    """Harness v2.6.1 (2026-04-26): clean stale entries.

    UNQUARANTINABLE list grew across versions. Validators promoted to the
    list AFTER being quarantined never get a chance to re-enable — they
    stay disabled because _run_validators skips them (line 2308
    `continue`), so they never PASS, so the auto-recovery path
    (verdict in PASS/WARN → entry["disabled"] = False) never fires.

    Catch-22 closed here: at orchestrator import, scan quarantine state.
    For each UNQUARANTINABLE entry with disabled=true, force-enable +
    reset consecutive_fails + emit audit event. Idempotent — runs every
    boot; later boots find nothing stale.

    Returns list of validator names that were force-enabled (for audit).
    """
    state = _load_quarantine()
    forced: list[str] = []
    for v_name in list(state.keys()):
        if v_name in UNQUARANTINABLE and state[v_name].get("disabled"):
            state[v_name]["disabled"] = False
            state[v_name]["consecutive_fails"] = 0
            state[v_name]["force_enabled_at"] = _now_iso()
            state[v_name]["force_enabled_reason"] = (
                "v2.6.1 stale UNQUARANTINABLE cleanup — validator was "
                "disabled before allowlist promoted it; auto-recovery path "
                "blocked because skipped validators never PASS."
            )
            forced.append(v_name)
    if forced:
        _save_quarantine(state)
    return forced


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

        # v2.6 (2026-04-25): inject extra args from VALIDATOR_EXTRA_ARGS map.
        # Validators needing run-id / phase-dir / plan-file / target-url
        # get them auto-supplied by orchestrator dispatch (no skill-file
        # wiring needed). Sources resolved on demand; missing values are
        # silently skipped (validator handles the absence — usually with
        # auto-skip PASS).
        for flag, source in VALIDATOR_EXTRA_ARGS.get(v_name, []):
            value = _resolve_extra_arg(source, run_id, phase)
            if value:
                args.extend([flag, value])

        try:
            # Timeout 60s — accommodates SAST validators (verify-oauth-pkce-enforcement,
            # verify-log-hygiene SAST mode) that walk the entire project tree.
            # Was 30s before harness v2.6 wired SAST validators (2026-04-25).
            r = subprocess.run(args, capture_output=True, text=True, timeout=60,
                               errors="replace")
            if not r.stdout.strip():
                continue
            # Some validators stream a non-JSON warning before the JSON body
            # (e.g. container-hardening prints "\033[33mNo Dockerfile found\033[0m" then
            # JSON). Find the JSON object by locating the first "{" line.
            stdout = r.stdout
            json_start = stdout.find("{")
            if json_start < 0:
                # No JSON body in stdout — validator emits human-friendly text
                # by default (e.g. "✓ All good", "\033[38;5;208m4 skill(s) drift\033[0m"). Older
                # validators predate the _common.py emit helper or treat --json
                # as opt-in. Synthesize a verdict from the exit code so the
                # orchestrator doesn't quarantine validators that simply haven't
                # been migrated. Bug: harness-v2.7-fixup-N11 (2026-04-26).
                # Re-discovered in /vg:accept 7.14.3: 11 validators crashed with
                # "Expecting value: line 1 column 1 (char 0)" — same root cause.
                text = stdout.strip()
                summary = text if len(text) <= 500 else (text[:500] + "…")
                if r.returncode == 0:
                    out = {
                        "verdict": "PASS",
                        "evidence": [{"type": "stdout", "message": summary}],
                        "_synthesized_from_exit_code": True,
                    }
                elif r.returncode == 1:
                    out = {
                        "verdict": "WARN",
                        "evidence": [{"type": "stdout", "message": summary}],
                        "_synthesized_from_exit_code": True,
                    }
                else:
                    # Exit 2+ usually means missing CLI args or schema error.
                    # Treat as SKIP (don't block) so operators can fix without
                    # losing the rest of the dispatch run.
                    out = {
                        "verdict": "SKIP",
                        "evidence": [{
                            "type": "info",
                            "message": f"exit={r.returncode} stdout={summary}",
                        }],
                        "_synthesized_from_exit_code": True,
                    }
            else:
                if json_start > 0:
                    stdout = stdout[json_start:]
                out = json.loads(stdout)
        except Exception as e:
            _quarantine_record(v_name, "CRASH")
            block_results.append({
                "validator": v_name,
                "verdict": "BLOCK",
                "evidence": [{"type": "info",
                              "message": f"validator crash: {e}"}],
            })
            continue

        # Schema shim — older validators (verify-log-hygiene, verify-oauth-pkce,
        # verify-container-hardening) emit verdict in their own vocabulary
        # (FAIL/OK/success/etc.) instead of the _common.py schema (PASS/WARN/
        # BLOCK). Normalize so the rest of the dispatch code sees one schema.
        raw_verdict = str(out.get("verdict", "PASS")).upper()
        if raw_verdict in ("PASS", "OK", "SUCCESS", "CLEAN", "GREEN"):
            out["verdict"] = "PASS"
        elif raw_verdict in ("SKIP", "SKIPPED", "N/A", "NA", "NOT_APPLICABLE"):
            # Validator self-skipped (e.g. feature not present, runtime probe
            # without target URL). Treat as PASS for gating, but preserve
            # the SKIP info in the evidence trail.
            out["verdict"] = "PASS"
            out.setdefault("evidence", []).append({
                "type": "validator_self_skip",
                "message": f"validator self-skipped (raw verdict: {raw_verdict})",
            })
        elif raw_verdict in ("WARN", "WARNING", "ADVISORY"):
            out["verdict"] = "WARN"
        elif raw_verdict in ("BLOCK", "FAIL", "FAILED", "ERROR", "RED"):
            out["verdict"] = "BLOCK"
        else:
            # Unknown verdict — be conservative and treat as BLOCK so
            # broken validators surface as operator pain (prefer over silent skip)
            out["verdict"] = "BLOCK"
            out.setdefault("evidence", []).append({
                "type": "schema_drift",
                "message": f"validator emitted unknown verdict '{raw_verdict}' — normalized to BLOCK; please normalize to PASS|WARN|BLOCK|SKIP",
            })

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
    # v2.5 anti-forge patch: honor required_unless_flag + glob_min_count
    must_write = contracts.normalize_must_write(contract.get("must_write") or [])
    phase_profile = contracts.detect_phase_profile(phase)
    missing_files = []
    profile_skipped = []  # WARN, not BLOCK
    waived_artifacts = []  # flag waiver → INFO event
    for item in must_write:
        # v2.5: flag-waiver check (anti-forge: user must opt-out explicitly
        # via --skip-crossai etc. — separate from profile-based skip)
        waiver = item.get("required_unless_flag")
        if waiver and waiver in (run_args or ""):
            waived_artifacts.append({"path": item["path"], "flag": waiver})
            continue

        rendered = contracts.substitute(item["path"], phase, phase_dir)

        # v2.5: glob_min_count support — path treated as glob, ≥N matches required
        glob_min = item.get("glob_min_count")
        if glob_min is not None:
            import glob as _glob
            abs_path = rendered if Path(rendered).is_absolute() else str(Path(os.getcwd()) / rendered)
            matches = _glob.glob(abs_path)
            if len(matches) < int(glob_min):
                missing_files.append({
                    "path": rendered,
                    "reason": f"glob matches {len(matches)} < required {glob_min} "
                              f"(pattern matches no files — artifact not produced)",
                })
            continue

        p = Path(rendered)
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        result = evidence.check_artifact(
            p, min_bytes=item["content_min_bytes"],
            required_sections=item["content_required_sections"],
            glob_fallback=True,
        )
        if not result["ok"]:
            # Missing — is this artifact even applicable for the phase profile?
            if not contracts.artifact_applicable(phase_profile, rendered):
                profile_skipped.append({
                    "path": str(p),
                    "reason": result["reason"],
                    "profile": phase_profile,
                })
                continue
            missing_files.append({"path": str(p), "reason": result["reason"]})
            continue

        # v2.5.2 Phase K: artifact-run binding check
        # If contract declares must_be_created_in_run=true, verify evidence
        # manifest entry exists + creator_run_id matches current run + sha256
        # matches (not mutated after emit). Stale artifact from prior run
        # would fail this check even though check_artifact passed on existence.
        if item.get("must_be_created_in_run"):
            binding = _verify_artifact_run_binding(
                p, run_id, item.get("check_provenance", False),
            )
            if not binding["ok"]:
                missing_files.append({
                    "path": str(p),
                    "reason": f"[artifact-run-binding] {binding['reason']}",
                })

    # v2.5: emit INFO event for waived artifacts (audit trail)
    if waived_artifacts:
        try:
            for wa in waived_artifacts:
                db.append_event(
                    run_id=run_id,
                    event_type="contract.artifact_waived",
                    phase=phase,
                    command=command,
                    outcome="INFO",
                    payload={"path": wa["path"], "flag": wa["flag"]},
                )
        except Exception:
            pass

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
    # v2.5 anti-forge patch: honor required_unless_flag per telemetry spec
    telemetry_specs = contracts.normalize_telemetry(
        contract.get("must_emit_telemetry") or []
    )
    if telemetry_specs:
        if is_partial_wave:
            telemetry_specs = [t for t in telemetry_specs
                               if t.get("event_type") not in PARTIAL_EXEMPT_EVENTS]

        # Separate flag-waived from always-checked
        checked_specs = []
        waived_specs = []
        for t in telemetry_specs:
            waiver = t.get("required_unless_flag")
            if waiver and waiver in (run_args or ""):
                waived_specs.append(t)
            else:
                checked_specs.append(t)

        if waived_specs:
            try:
                for ws in waived_specs:
                    db.append_event(
                        run_id=run_id,
                        event_type="contract.telemetry_waived",
                        phase=phase,
                        command=command,
                        outcome="INFO",
                        payload={"event_type": ws["event_type"],
                                 "flag": ws.get("required_unless_flag")},
                    )
            except Exception:
                pass

        events = db.query_events(run_id=run_id)
        missing_tel = evidence.check_telemetry(checked_specs, events)
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
    # v2.46-wave3: import recovery_paths for per-violation actionable fix paths.
    # Closes UX dead-end where BLOCK gives generic options ("Run missing step")
    # without telling user concrete commands to fix the specific validator.
    try:
        from recovery_paths import render_recovery_block
        recovery_available = True
    except ImportError:
        recovery_available = False

    lines = [
        "\033[38;5;208mVG runtime_contract violations — cannot complete run.\033[0m",
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
        # v2.46-wave3 — per-violation recovery paths (★ marks RECOMMENDED)
        if recovery_available:
            recovery_lines = render_recovery_block(v["type"], command, phase)
            if recovery_lines:
                lines.append("")
                lines.extend(recovery_lines)

    lines.extend([
        "",
        "Generic fallback options (if no specific recovery path above):",
        "  1. Run missing step + produce artifacts + mark + emit",
        "  2. vg-orchestrator override --flag <f> --reason <text>",
        "       — logs OVERRIDE-DEBT.md entry ONLY. Does NOT bypass this",
        "       run's runtime_contract violations. Stop hook will re-fire",
        "       at next /vg command unless underlying evidence is produced.",
        "       Use --skip-<validator> CLI flag at command invocation for",
        "       per-run bypass (e.g., /vg:build 3.1 --skip-build-crossai).",
        "  3. vg-orchestrator run-abort --reason <text> (gives up)",
        "",
        "Tip: Run `/vg:doctor recovery` to interactively pick + execute a recovery path.",
        "",
        "Log: .vg/events.db",
    ])
    return "\n".join(lines)


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# ─── Phase D — orphan validator triage (delegated to _orphans module) ───

def cmd_orphans_list(args) -> int:
    if _orphans_mod is None:
        print(
            "\033[38;5;208morchestrator: _orphans module unavailable\033[0m", file=sys.stderr,
        )
        return 1
    return _orphans_mod.orphans_list(args)


def cmd_orphans_collect(args) -> int:
    if _orphans_mod is None:
        print(
            "\033[38;5;208morchestrator: _orphans module unavailable\033[0m", file=sys.stderr,
        )
        return 1
    return _orphans_mod.orphans_collect(args)


def cmd_orphans_apply(args) -> int:
    if _orphans_mod is None:
        print(
            "\033[38;5;208morchestrator: _orphans module unavailable\033[0m", file=sys.stderr,
        )
        return 1
    return _orphans_mod.orphans_apply(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vg-orchestrator",
                                description="VG pipeline state machine",
                                allow_abbrev=False)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("run-start", help="Register new run")
    s.add_argument("command", help="vg:* command name")
    s.add_argument("phase", help="phase number")
    s.add_argument("extra", nargs=argparse.REMAINDER,
                   help="flags/args (captured verbatim; use -- prefix or quote)")
    s.set_defaults(func=cmd_run_start)

    s = sub.add_parser("run-status", help="Show active run")
    s.add_argument("--pretty", action="store_true",
                   help="Render taskboard/progress instead of raw JSON")
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

    s = sub.add_parser(
        "tasklist-projected",
        help="Bind native task UI projection to tasklist-contract.json",
    )
    s.add_argument(
        "--adapter",
        required=True,
        choices=["claude", "codex", "fallback"],
        help="Runtime surface used to project the tasklist contract",
    )
    s.set_defaults(func=cmd_tasklist_projected)

    s = sub.add_parser("mark-step", help="Touch step marker")
    s.add_argument("namespace", help="e.g. 'build', 'blueprint', 'shared'")
    s.add_argument("step_name")
    s.set_defaults(func=cmd_mark_step)

    s = sub.add_parser("step-active", help="Mark current active step for progress surfaces")
    s.add_argument("step_name")
    s.set_defaults(func=cmd_step_active)

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

    # Issue #21: backfill run.completed for runs predating Stop-hook contract.
    # Refuses unless run.started exists + required artifacts present + reason
    # ≥ 10 chars; logs critical-severity OVERRIDE-DEBT entry on success.
    s = sub.add_parser(
        "run-backfill",
        help=("Backfill run.completed for legacy runs (issue #21). "
              "Refuses without artifacts or run.started; logs critical "
              "OVERRIDE-DEBT entry on success."),
    )
    s.add_argument("--run-id", required=True,
                   help="Target run_id (find via query-events --event-type=run.started)")
    s.add_argument("--reason", required=True,
                   help="Audit reason ≥ 10 chars (e.g. 'predates Stop-hook v2.5.2 contract')")
    s.set_defaults(func=cmd_run_backfill)

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

    # Harness v2.6.1 (2026-04-26): quarantine inspection + manual recovery
    s = sub.add_parser("quarantine", help="Inspect/manage validator quarantine state")
    s.add_argument("action", choices=["status", "re-enable", "force-enable-stale"],
                   help="status: list quarantined; re-enable: force one validator; force-enable-stale: clean UNQUARANTINABLE entries")
    s.add_argument("--validator", default=None,
                   help="Validator name (required for re-enable)")
    s.add_argument("--reason", default="",
                   help="Justification for re-enable (logged to audit)")
    # Phase E (2026-04-26): structured JSON output for dogfood-dashboard.py
    s.add_argument("--json", action="store_true", default=False,
                   help="Emit status as structured JSON (machine-readable)")
    s.set_defaults(func=cmd_quarantine)

    # Harness v2.6 Phase F (2026-04-26): severity calibration subcommand
    s = sub.add_parser(
        "calibrate",
        help=("Per-validator severity calibration — review/apply "
              "BLOCK↔WARN suggestions"),
    )
    s.add_argument(
        "action",
        choices=["status", "apply", "apply-all", "apply-decay"],
        help=("status: compute + write CALIBRATION-SUGGESTIONS.md; "
              "apply: mutate dispatch-manifest.json for one suggestion; "
              "apply-all: bulk-apply current suggestions; "
              "apply-decay: retire stale suggestions per "
              "calibration.decay_after_phases (Phase Q, v2.7)"),
    )
    s.add_argument(
        "--suggestion-id", default="",
        help="Suggestion id from CALIBRATION-SUGGESTIONS.md (apply only)",
    )
    s.add_argument(
        "--reason", default="",
        help=("Audit text for apply/apply-all/apply-decay "
              "(min 50 chars)"),
    )
    s.add_argument(
        "--lookback-phases", type=int, default=5,
        help="Decay-policy footer for status output (advisory)",
    )
    s.add_argument(
        "--decay-after-phases", type=int, default=5,
        help=("Age threshold in phases for apply-decay (default 5, "
              "mirrors calibration.decay_after_phases config key)"),
    )
    s.add_argument(
        "--dry-run", action="store_true", default=False,
        help="apply-decay only: preview retirements without mutating",
    )
    s.add_argument(
        "--json", action="store_true", default=False,
        help="Status: emit suggestions as JSON to stdout",
    )
    s.set_defaults(func=cmd_calibrate)

    # Harness v2.6 Phase G (2026-04-26): /vg:learn TTY/HMAC parity
    s = sub.add_parser(
        "learn",
        help=("Bootstrap learn candidate gate — list/review (read-only) "
              "and promote/reject (TTY/HMAC + --reason)"),
    )
    s.add_argument(
        "action",
        choices=["list", "review", "promote", "reject"],
        help=("list: enumerate non-retired candidates; "
              "review: print one candidate block; "
              "promote: move candidate → ACCEPTED.md (TTY/HMAC gated); "
              "reject: move candidate → REJECTED.md (TTY/HMAC gated)"),
    )
    s.add_argument(
        "--candidate", default="",
        help="Candidate id L-XXX (required for review/promote/reject)",
    )
    s.add_argument(
        "--reason", default="",
        help=("Audit text for promote/reject (min 50 chars). "
              "Read-only actions ignore this flag."),
    )
    s.add_argument(
        "--include-retired", action="store_true", default=False,
        help="list: include RETIRED candidates in output",
    )
    s.set_defaults(func=cmd_learn)

    # Harness v2.7 Phase D (2026-04-26): orphan validator triage
    s = sub.add_parser(
        "orphans-list",
        help=("Compute 3-way diff (script vs registry vs dispatch), "
              "partition into 3 agent slices, write orphan-list.json"),
        allow_abbrev=False,
    )
    s.set_defaults(func=cmd_orphans_list)

    s = sub.add_parser(
        "orphans-collect",
        help=("Merge per-agent decision JSONs, validate coverage, "
              "aggregate stats, write orphan-decisions.json"),
        allow_abbrev=False,
    )
    s.set_defaults(func=cmd_orphans_collect)

    s = sub.add_parser(
        "orphans-apply",
        help=("Apply WIRE/RETIRE/MERGE/NEEDS_HUMAN decisions atomically — "
              "patch registry+dispatch, git-mv retired scripts"),
        allow_abbrev=False,
    )
    s.add_argument("--dry-run", action="store_true",
                   help="Print apply log without writing any files")
    s.set_defaults(func=cmd_orphans_apply)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as e:
        print(f"\033[38;5;208morchestrator error: {e}\033[0m", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
