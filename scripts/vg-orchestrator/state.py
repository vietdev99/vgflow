"""
Run state machine. v2.28.0: per-session active-run keying.

Two parallel Claude Code sessions on the same project (e.g. session A
running /vg:scope phase 1 while session B runs /vg:build phase 2) used
to race on a single global current-run.json — session B's run-start
either blocked on session A's active run (cmd_run_start), or overwrote
it (entry-hook), losing audit trail. Now each session owns its own
state file, multiple active runs coexist, run-status surfaces all of
them.

Storage:
  - .vg/active-runs/{session_id}.json — authoritative per-session state
  - .vg/current-run.json              — latest-snapshot mirror (legacy
                                        compat + run-status aggregate)

Authoritative ledger remains .vg/events.db (runs + events tables);
files are convenience caches.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from _repo_root import find_repo_root

REPO_ROOT = find_repo_root(__file__)
ACTIVE_RUNS_DIR = REPO_ROOT / ".vg" / "active-runs"
LEGACY_CURRENT_RUN = REPO_ROOT / ".vg" / "current-run.json"
CURRENT_RUN_FILE = LEGACY_CURRENT_RUN  # back-compat alias
SESSION_CONTEXT = REPO_ROOT / ".vg" / ".session-context.json"
SESSION_CONTEXTS_DIR = REPO_ROOT / ".vg" / "session-contexts"


def _session_context_path(session_id: str) -> Path:
    return SESSION_CONTEXTS_DIR / f"{_safe_session_filename(session_id)}.json"


def _normalize_command_hint(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("/vg:"):
        raw = raw[1:]
    if raw.startswith("vg:"):
        return raw
    if re.fullmatch(r"[a-z][a-z0-9_-]*", raw):
        return f"vg:{raw}"
    return raw


def _intent_hints_from_env(
    command_hint: str | None = None,
    phase_hint: str | None = None,
    run_id_hint: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    command = _normalize_command_hint(
        command_hint
        or os.environ.get("VG_CURRENT_COMMAND")
        or os.environ.get("VG_SESSION_CMD")
    )
    phase_raw = (
        phase_hint
        or os.environ.get("VG_CURRENT_PHASE")
        or os.environ.get("VG_SESSION_PHASE")
        or os.environ.get("PHASE_NUMBER")
    )
    run_id_raw = run_id_hint or os.environ.get("VG_RUN_ID")
    phase = str(phase_raw).strip() if phase_raw and str(phase_raw).strip() else None
    run_id = str(run_id_raw).strip() if run_id_raw and str(run_id_raw).strip() else None
    return run_id, command, phase


def _run_matches_intent(
    run: dict | None,
    *,
    session_id: str | None = None,
    run_id: str | None = None,
    command: str | None = None,
    phase: str | None = None,
) -> bool:
    if not _has_run_id(run):
        return False
    run_sid = run.get("session_id")
    if session_id and run_sid and run_sid != session_id:
        return False
    if run_id and run.get("run_id") != run_id:
        return False
    if command:
        run_cmd = _normalize_command_hint(run.get("command"))
        if run_cmd and run_cmd != command:
            return False
    if phase and run.get("phase") and str(run.get("phase")) != str(phase):
        return False
    return True


def _select_matching_active_run(
    *,
    session_id: str | None = None,
    run_id_hint: str | None = None,
    command_hint: str | None = None,
    phase_hint: str | None = None,
    allow_ambiguous_latest: bool = False,
) -> dict | None:
    run_id, command, phase = _intent_hints_from_env(
        command_hint=command_hint,
        phase_hint=phase_hint,
        run_id_hint=run_id_hint,
    )

    candidates: list[dict] = []
    seen: set[str] = set()

    def _add_candidate(run: dict | None) -> None:
        if not _run_matches_intent(
            run,
            session_id=session_id,
            run_id=run_id,
            command=command,
            phase=phase,
        ):
            return
        rid = str(run.get("run_id") or "")
        if not rid or rid in seen or _is_run_terminal(rid):
            return
        seen.add(rid)
        candidates.append(run)

    if session_id:
        _add_candidate(_read_json(_active_run_path(session_id)))

    if ACTIVE_RUNS_DIR.exists():
        for f in sorted(ACTIVE_RUNS_DIR.glob("*.json")):
            _add_candidate(_read_json(f))

    _add_candidate(_read_json(LEGACY_CURRENT_RUN))

    if not candidates:
        return None

    if len(candidates) > 1 and not allow_ambiguous_latest and not run_id:
        return None

    candidates.sort(key=lambda r: (r.get("started_at") or "", r.get("run_id") or ""))
    return candidates[-1]


def _session_id_from_session_context(
    command_hint: str | None = None,
    phase_hint: str | None = None,
    run_id_hint: str | None = None,
) -> str | None:
    """Best-effort session recovery for Codex command-body shells.

    Codex hooks receive `session_id` and write per-session active-run state,
    but later shell tool calls do not inherit environment mutations from the
    hook process. When `CLAUDE_SESSION_ID` is absent, recover the session from
    `.vg/.session-context.json` so `run-start` reconciles with the hook-seeded
    run instead of creating a synthetic `session-unknown-*` run.
    """
    run_id_hint, command_hint, phase_hint = _intent_hints_from_env(
        command_hint=command_hint,
        phase_hint=phase_hint,
        run_id_hint=run_id_hint,
    )

    direct_match = _select_matching_active_run(
        run_id_hint=run_id_hint,
        command_hint=command_hint,
        phase_hint=phase_hint,
        allow_ambiguous_latest=False,
    )
    if direct_match and isinstance(direct_match.get("session_id"), str) and direct_match.get("session_id"):
        return direct_match["session_id"]

    def _ctx_matches_run(run: dict | None) -> bool:
        if not _has_run_id(run):
            return False
        run_id = run.get("run_id")
        if _is_run_terminal(run_id):
            return False
        ctx_run_id = ctx.get("run_id")
        if isinstance(ctx_run_id, str) and ctx_run_id and run_id != ctx_run_id:
            return False
        ctx_sid = ctx.get("session_id")
        run_sid = run.get("session_id")
        if (
            isinstance(ctx_sid, str) and ctx_sid
            and isinstance(run_sid, str) and run_sid
            and run_sid != ctx_sid
        ):
            return False
        for key in ("command", "phase"):
            ctx_value = ctx.get(key)
            run_value = run.get(key)
            if ctx_value and run_value and str(ctx_value) != str(run_value):
                return False
        return True

    def _ctx_matches_intent(ctx: dict | None) -> bool:
        if not isinstance(ctx, dict):
            return False
        if run_id_hint and ctx.get("run_id") and ctx.get("run_id") != run_id_hint:
            return False
        ctx_cmd = _normalize_command_hint(ctx.get("command"))
        if command_hint and ctx_cmd and ctx_cmd != command_hint:
            return False
        if phase_hint and ctx.get("phase") and str(ctx.get("phase")) != str(phase_hint):
            return False
        return bool(ctx.get("run_id") or ctx.get("session_id"))

    context_candidates: list[dict] = []
    if SESSION_CONTEXTS_DIR.exists():
        for f in sorted(SESSION_CONTEXTS_DIR.glob("*.json")):
            ctx = _read_json(f)
            if _ctx_matches_intent(ctx):
                context_candidates.append(ctx)
    legacy_ctx = _read_json(SESSION_CONTEXT)
    if _ctx_matches_intent(legacy_ctx):
        context_candidates.append(legacy_ctx)

    for ctx in context_candidates:
        ctx_sid = ctx.get("session_id")
        if isinstance(ctx_sid, str) and ctx_sid:
            run = _select_matching_active_run(
                session_id=ctx_sid,
                run_id_hint=ctx.get("run_id") or run_id_hint,
                command_hint=ctx.get("command") or command_hint,
                phase_hint=ctx.get("phase") or phase_hint,
                allow_ambiguous_latest=False,
            )
            if _ctx_matches_run(run):
                return ctx_sid

    return None


def _session_id_from_env(
    command_hint: str | None = None,
    phase_hint: str | None = None,
    run_id_hint: str | None = None,
) -> str | None:
    return (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CODEX_SESSION_ID")
        or _session_id_from_session_context(
            command_hint=command_hint,
            phase_hint=phase_hint,
            run_id_hint=run_id_hint,
        )
        or None
    )


def current_session_id(
    command_hint: str | None = None,
    phase_hint: str | None = None,
    run_id_hint: str | None = None,
) -> str | None:
    return _session_id_from_env(
        command_hint=command_hint,
        phase_hint=phase_hint,
        run_id_hint=run_id_hint,
    )


def _safe_session_filename(sid: str) -> str:
    """Sanitize session_id for filesystem use. Empty/None → 'unknown'."""
    if not sid:
        return "unknown"
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")
    return safe or "unknown"


def _is_unknown_orphan_session(sid: str | None) -> bool:
    """Return True for synthetic no-session run ids.

    `run-start` tags no-env callers as `session-unknown-{run_id_prefix}`.
    Later subprocesses still have no session env, so they resolve as
    `unknown`; treat the synthetic id as compatible with that orphan reader.
    """
    return sid == "unknown" or (
        isinstance(sid, str) and sid.startswith("session-unknown-")
    )


def _is_run_terminal(run_id: str | None) -> bool:
    """True if run_id has a terminal event in events.db.

    Used by read_active_run to filter stale terminated runs out of the
    legacy current-run.json fallback path. Without this check, a per-
    session file deletion (manual rm, FS cleanup, /tmp eviction) silently
    falls back to legacy mirror which may still contain a run that was
    aborted or completed long ago — every subsequent mark-step / step-
    active / emit-event would land on the dead run, write_active_run
    would resurrect the per-session file, and the cycle persists until
    the legacy mirror is cleared too.

    Direct sqlite3 to avoid circular import with db.py. Returns False on
    any error (events.db missing, locked, schema drift) so the legacy
    fallback path remains available — fail-open preserves self-heal.
    """
    if not run_id:
        return False
    db_path = REPO_ROOT / ".vg" / "events.db"
    if not db_path.exists():
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT 1 FROM events WHERE run_id = ? AND event_type IN "
                "('run.completed', 'run.aborted', 'run.stale_cleared') "
                "LIMIT 1",
                (run_id,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception:
        return False


def _active_run_path(session_id: str) -> Path:
    return ACTIVE_RUNS_DIR / f"{_safe_session_filename(session_id)}.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _has_run_id(run: dict | None) -> bool:
    return bool(isinstance(run, dict) and run.get("run_id"))


# ─── Per-session API (v2.28.0+) ────────────────────────────────────────────


def read_active_run(
    session_id: str | None = None,
    command_hint: str | None = None,
    phase_hint: str | None = None,
    run_id_hint: str | None = None,
) -> dict | None:
    """Read active run for the given session.

    Resolution order:
      1. .vg/active-runs/{session_id}.json (per-session state)
      2. Legacy .vg/current-run.json fallback — fires when the per-session
         file is missing AND the legacy snapshot is compatible:
            - legacy has no session_id (pre-v2.24 install), OR
            - legacy session_id matches `sid` exactly, OR
            - legacy session_id is the "unknown" sentinel or synthetic
              "session-unknown-*" id (orphan run
              written by a subshell with no CLAUDE_SESSION_ID; the Stop
              hook must still be able to read + clean it up using the
              real session_id).
      3. None.
    """
    sid = session_id or _session_id_from_env(
        command_hint=command_hint,
        phase_hint=phase_hint,
        run_id_hint=run_id_hint,
    ) or "unknown"

    run = _read_json(_active_run_path(sid))
    if _has_run_id(run):
        return run

    # The pre-v2.28 guard `if not ACTIVE_RUNS_DIR.exists()` was too strict:
    # once the per-session directory existed, orphan-written legacy
    # snapshots became unreachable from any session that did not share
    # their sid, even though they still represented a real active run.
    # Symptom: Stop hook firing run-complete with the real Claude session_id
    # reported "No active run to complete" while run-status (called from
    # the same subshell that wrote the run with sid="unknown") saw the
    # legacy snapshot via list_active_runs aggregation. Same physical
    # file, divergent readers — the symmetry break blocked run-complete
    # cleanup. Drop the directory guard; rely on the per-session lookup
    # at line 85 to take precedence whenever the per-session file exists.
    legacy = _read_json(LEGACY_CURRENT_RUN)
    if _has_run_id(legacy):
        legacy_sid = legacy.get("session_id")
        if not legacy_sid or legacy_sid == sid or _is_unknown_orphan_session(legacy_sid):
            # OHOK-FIX-2 (2026-05-03): filter terminal runs out of legacy
            # fallback. Without this, a per-session file deletion (manual
            # rm or FS cleanup) silently substitutes a stale aborted/
            # completed run from the legacy mirror — every subsequent
            # mark-step/step-active/emit-event lands on the dead run,
            # write_active_run resurrects the per-session file, and the
            # zombie persists across user attempts. PrintwayV3 dogfood
            # session 2026-05-03 hit this: 5 zombie /vg:build phase 2
            # runs, all events landing on a stale blueprint 4.1 run_id.
            # See vgflow-bugfix branch fix/orchestrator-orphan-active-run-reconcile.
            legacy_rid = legacy.get("run_id")
            if _is_run_terminal(legacy_rid):
                return None
            return legacy

    # No-env callers read as sid="unknown", while run-start stores them under
    # a synthetic per-session file named session-unknown-{run_id_prefix}. If
    # the legacy mirror is temporarily unavailable or belongs to a self-test
    # session, still recover the active no-env run from active-runs/.
    if _is_unknown_orphan_session(sid) and ACTIVE_RUNS_DIR.exists():
        candidates = []
        for f in sorted(ACTIVE_RUNS_DIR.glob("*.json")):
            r = _read_json(f)
            if _has_run_id(r) and _is_unknown_orphan_session(r.get("session_id")):
                # Same OHOK-FIX-2 filter — don't surface terminal orphan runs.
                if _is_run_terminal(r.get("run_id")):
                    continue
                candidates.append(r)
        if candidates:
            candidates.sort(key=lambda r: r.get("started_at") or "")
            return candidates[-1]

    return None


def write_active_run(run: dict, session_id: str | None = None) -> None:
    """Write per-session active run + mirror to current-run.json snapshot.

    The mirror file is an aggregate latest-write view used by run-status
    aggregate path, NOT authoritative. Per-session files are.
    """
    sid = session_id or run.get("session_id") or _session_id_from_env() or "unknown"
    _atomic_write_json(_active_run_path(sid), run)
    _atomic_write_json(LEGACY_CURRENT_RUN, run)


def clear_active_run(session_id: str | None = None) -> None:
    """Clear per-session active run + the latest-snapshot mirror if it
    belongs to that session, or to an orphan (sid="unknown"), or has
    no session_id (pre-v2.24 install). Symmetric with read_active_run
    so a run that was readable from a given sid is also clearable.
    """
    sid = session_id or _session_id_from_env() or "unknown"
    try:
        _active_run_path(sid).unlink()
    except FileNotFoundError:
        pass

    legacy = _read_json(LEGACY_CURRENT_RUN)
    if legacy:
        legacy_sid = legacy.get("session_id")
        if not legacy_sid or legacy_sid == sid or _is_unknown_orphan_session(legacy_sid):
            try:
                LEGACY_CURRENT_RUN.unlink()
            except FileNotFoundError:
                pass
            # Best-effort: orphan run may also live under active-runs/unknown.json
            # or active-runs/session-unknown-*.json depending on writer version.
            for orphan_sid in {"unknown", legacy_sid}:
                if orphan_sid and orphan_sid != sid:
                    try:
                        _active_run_path(orphan_sid).unlink()
                    except FileNotFoundError:
                        pass


def list_active_runs() -> list[dict]:
    """Return all active runs across sessions on this project.

    Pre-v2.28.0 install (no active-runs/) returns legacy snapshot as a
    single-element list, or empty list. Used by run-status aggregate
    view + cross-session collision detection in cmd_run_start.
    """
    runs: list[dict] = []
    if ACTIVE_RUNS_DIR.exists():
        for f in sorted(ACTIVE_RUNS_DIR.glob("*.json")):
            r = _read_json(f)
            if _has_run_id(r):
                runs.append(r)
        return runs

    legacy = _read_json(LEGACY_CURRENT_RUN)
    if _has_run_id(legacy):
        runs.append(legacy)
    return runs


# ─── Legacy facade (pre-v2.28.0 callsites) ─────────────────────────────────
#
# Existing orchestrator callsites use these names — keep working without
# changes. They route to the per-session API based on env CLAUDE_SESSION_ID,
# which subprocesses inherit naturally from the firing hook.


def write_current_run(run: dict) -> None:
    write_active_run(run)


def read_current_run() -> dict | None:
    return read_active_run()


def clear_current_run() -> None:
    clear_active_run()


# ─── Step markers (unchanged from v2.27.x) ─────────────────────────────────


def mark_step(phase_dir: Path, namespace: str, step_name: str) -> Path:
    """Touch a step marker file. Namespaced to avoid cross-command conflicts."""
    if namespace == "shared":
        marker_dir = phase_dir / ".step-markers"
    else:
        marker_dir = phase_dir / ".step-markers" / namespace
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / f"{step_name}.done"
    marker.touch()
    return marker


def check_markers(phase_dir: Path, markers: list[dict],
                  fallback_namespaces: list[str] | None = None) -> list[str]:
    """
    Returns list of missing marker names.
    A marker is considered present if found in its declared namespace OR any
    fallback namespace. This makes frontmatter declarations forgiving across
    v1 (shared) and v2 (per-command) marker layouts.
    """
    fallbacks = fallback_namespaces or []
    missing = []
    for m in markers:
        ns = m.get("namespace", "shared")
        name = m["name"]
        candidates = []
        if ns == "shared":
            candidates.append(phase_dir / ".step-markers" / f"{name}.done")
        else:
            candidates.append(phase_dir / ".step-markers" / ns / f"{name}.done")

        for fb in fallbacks:
            if fb == ns:
                continue
            if fb == "shared":
                candidates.append(phase_dir / ".step-markers" / f"{name}.done")
            else:
                candidates.append(phase_dir / ".step-markers" / fb / f"{name}.done")

        shared_path = phase_dir / ".step-markers" / f"{name}.done"
        if shared_path not in candidates:
            candidates.append(shared_path)

        if not any(c.exists() for c in candidates):
            label = f"{ns}/{name}" if ns != "shared" else name
            missing.append(label)
    return missing
