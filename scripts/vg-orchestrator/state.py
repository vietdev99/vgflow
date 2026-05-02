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
from pathlib import Path

from _repo_root import find_repo_root

REPO_ROOT = find_repo_root(__file__)
ACTIVE_RUNS_DIR = REPO_ROOT / ".vg" / "active-runs"
LEGACY_CURRENT_RUN = REPO_ROOT / ".vg" / "current-run.json"
CURRENT_RUN_FILE = LEGACY_CURRENT_RUN  # back-compat alias


def _session_id_from_env() -> str | None:
    return (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or None
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


# ─── Per-session API (v2.28.0+) ────────────────────────────────────────────


def read_active_run(session_id: str | None = None) -> dict | None:
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
    sid = session_id or _session_id_from_env() or "unknown"

    run = _read_json(_active_run_path(sid))
    if run:
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
    if legacy:
        legacy_sid = legacy.get("session_id")
        if not legacy_sid or legacy_sid == sid or _is_unknown_orphan_session(legacy_sid):
            return legacy

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
            if r:
                runs.append(r)
        return runs

    legacy = _read_json(LEGACY_CURRENT_RUN)
    if legacy:
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
