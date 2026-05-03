"""
Shared helpers for validator scripts. Every validator outputs
vg.validator-output schema (see .claude/schemas/validator-output.json).
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    type: str
    message: str
    file: str | None = None
    line: int | None = None
    expected: Any = None
    actual: Any = None
    fix_hint: str | None = None


@dataclass
class Output:
    validator: str
    verdict: str = "PASS"  # PASS | BLOCK | WARN
    evidence: list[Evidence] = field(default_factory=list)
    duration_ms: int = 0
    cache_key: str | None = None

    def add(self, evidence: Evidence, escalate: bool = True) -> None:
        self.evidence.append(evidence)
        if escalate and self.verdict == "PASS":
            self.verdict = "BLOCK"

    def warn(self, evidence: Evidence) -> None:
        self.evidence.append(evidence)
        if self.verdict == "PASS":
            self.verdict = "WARN"

    def to_json(self) -> str:
        return json.dumps({
            "validator": self.validator,
            "verdict": self.verdict,
            "evidence": [
                {k: v for k, v in e.__dict__.items() if v is not None}
                for e in self.evidence
            ],
            "duration_ms": self.duration_ms,
            "cache_key": self.cache_key,
        })


class timer:
    """Context manager that records ms into Output.duration_ms."""
    def __init__(self, output: Output):
        self.output = output

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.output.duration_ms = int((time.time() - self.start) * 1000)


def emit_and_exit(output: Output) -> None:
    """Print JSON + exit 0 (PASS/WARN) or 1 (BLOCK). Orchestrator reads both."""
    print(output.to_json())
    if output.verdict == "BLOCK":
        sys.exit(1)
    sys.exit(0)


def find_phase_dir(phase: str):
    """Resolve phase input to on-disk directory.

    Mirrors orchestrator contracts.resolve_phase_dir + bash phase-resolver.sh
    (OHOK v2 follow-up fix 2026-04-22). Handles zero-padding of decimal phases
    (`7.13` → `07.13-*`), bare dirs (legacy GSD `07/`), three-level decimals
    (`07.0.1`), and exact-beats-prefix (`07.12` not matching `07.12.1-*`).

    Previously every validator had inline `PHASES_DIR.glob(f"{phase}-*")` +
    buggy `zfill(2)` fallback that never zero-padded decimals correctly.
    Centralized here so fixes land once.

    Args:
      phase: user-provided phase string (e.g. "7.13", "14", "07.0.1")

    Returns:
      Path to phase dir if found, else None.
    """
    import os
    from pathlib import Path as _Path
    repo = _Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    phases_dir = repo / ".vg" / "phases"
    if not phase or not phases_dir.exists():
        return None

    # Step 1: exact dash-suffix match (prevents 07.12 matching 07.12.1-*)
    candidates = list(phases_dir.glob(f"{phase}-*"))
    if candidates:
        return candidates[0]

    # Step 1b: exact bare-dir match
    bare = phases_dir / phase
    if bare.is_dir():
        return bare

    # Step 2: zero-pad major part of decimal phase
    if "." in phase:
        major, _, rest = phase.partition(".")
    else:
        major, rest = phase, ""
    if major.isdigit() and len(major) < 2:
        normalized = f"{major.zfill(2)}.{rest}" if rest else major.zfill(2)
        if normalized != phase:
            candidates = list(phases_dir.glob(f"{normalized}-*"))
            if candidates:
                return candidates[0]
            bare_norm = phases_dir / normalized
            if bare_norm.is_dir():
                return bare_norm

    return None


def read_active_run_id(repo_root=None, command_filter: str | None = None) -> str | None:
    """Resolve the active run_id for the CURRENT session.

    Closes the multi-session current-run.json race: when two Claude sessions
    run /vg:* commands concurrently (e.g. session A doing /vg:build 3.3 while
    session B starts /vg:blueprint 3.5), each `vg-orchestrator run-start`
    overwrites .vg/current-run.json. Validators that read that file raw end up
    seeing the OTHER session's run_id and report "no evidence" / "no active
    run" / wrong-phase outcomes during run-complete.

    Resolution mirrors vg-orchestrator.state.read_active_run +
    vg-build-crossai-loop._resolve_active_run (4-tier, in order):

      1. Per-session file: ``.vg/active-runs/{session_id}.json`` keyed by
         CLAUDE_SESSION_ID / CLAUDE_CODE_SESSION_ID env. Authoritative.
      2. Legacy snapshot: ``.vg/current-run.json``. Trusted only when its
         session_id matches the env, is empty, or is the "unknown" sentinel
         (orphan run from a subshell with no session env). Stale-pointer
         from foreign session falls through to step 3.
      3. SQLite ``runs`` table: most recent open row whose session_id matches
         the env, optionally filtered by ``command_filter`` prefix
         (e.g. "vg:build" / "vg:review"). This handles run-abort + chicken-
         and-egg cases where current-run.json was cleared mid-flow.
      4. None.

    Args:
      repo_root:        Path to repo root. Defaults to $VG_REPO_ROOT or cwd.
      command_filter:   Optional command prefix for DB fallback (no LIKE wildcards
                        needed; the function appends ``%``). When set, only matches
                        runs whose ``command`` column starts with this string.

    Returns:
      run_id string, or None when nothing matches the current session.
    """
    import os
    import sqlite3
    from pathlib import Path as _Path

    if repo_root is None:
        repo_root = _Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    else:
        repo_root = _Path(repo_root)

    sid = (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or ""
    )
    safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_") or ""

    # 1. Per-session active-run file
    if safe_sid:
        per = repo_root / ".vg" / "active-runs" / f"{safe_sid}.json"
        if per.exists():
            try:
                run = json.loads(per.read_text(encoding="utf-8"))
                rid = run.get("run_id")
                if rid:
                    return rid
            except Exception:
                pass

    # 2. Legacy snapshot — trust only when compatible with the current session
    legacy = repo_root / ".vg" / "current-run.json"
    if legacy.exists():
        try:
            run = json.loads(legacy.read_text(encoding="utf-8"))
            legacy_sid = run.get("session_id") or ""
            compatible = (
                not sid
                or not legacy_sid
                or legacy_sid == sid
                or legacy_sid == "unknown"
            )
            if compatible:
                rid = run.get("run_id")
                if rid:
                    return rid
        except Exception:
            pass

    # 3. SQLite fallback — most recent open run for this session
    if sid:
        try:
            db_path = repo_root / ".vg" / "events.db"
            if db_path.exists():
                conn = sqlite3.connect(str(db_path), timeout=2.0)
                try:
                    where = ["session_id = ?", "completed_at IS NULL"]
                    params: list[Any] = [sid]
                    if command_filter:
                        where.append("command LIKE ?")
                        params.append(f"{command_filter}%")
                    row = conn.execute(
                        "SELECT run_id FROM runs WHERE "
                        + " AND ".join(where)
                        + " ORDER BY started_at DESC LIMIT 1",
                        params,
                    ).fetchone()
                    if row:
                        return row[0]
                finally:
                    conn.close()
        except Exception:
            pass

    return None
