"""recovery_telemetry — uniform emit helper for auto-recovery code paths.

Every auto-recovery action MUST emit a paired set of events:
  - hook.recovery_attempted   (BEFORE the action runs; payload describes intent)
  - hook.recovery_succeeded   (action exit 0 + post-condition met)
  - hook.recovery_failed      (action exit != 0 OR post-condition not met)

The pairing lets `/vg:gate-stats recovery` compute success rate per
recovery_kind. Pre-fix only success was emitted, so `failures / attempts`
was always 0 / 0 = NaN.

Reserved-event guard (vg-orchestrator OHOK-8) does NOT cover hook.* events,
so emit-event accepts these directly.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RECOVERY_KINDS = {
    "marker_drift",          # vg-verify-claim Tier C migrate-state auto-fire
    "vg_recovery_auto",      # vg-recovery.py --auto safe-paths
    "stale_run_abort",       # future: auto-abort stale orphan runs
}

_VALID_OUTCOMES = {"attempted", "succeeded", "failed"}


def emit(kind: str, outcome: str, *,
         run_id: str | None = None,
         payload: dict | None = None,
         orchestrator_path: str | Path = ".claude/scripts/vg-orchestrator",
         session_id: str | None = None,
         repo_root: str | Path | None = None) -> int:
    """Emit a recovery telemetry event. Returns subprocess returncode (0 on success).

    `kind` MUST be in RECOVERY_KINDS. `outcome` MUST be one of
    'attempted', 'succeeded', 'failed' — converted to event_type
    `hook.recovery_attempted` etc.
    """
    if kind not in RECOVERY_KINDS:
        raise ValueError(f"unknown recovery kind: {kind!r}; expected one of {sorted(RECOVERY_KINDS)}")
    if outcome not in _VALID_OUTCOMES:
        raise ValueError(f"unknown outcome: {outcome!r}; expected one of {sorted(_VALID_OUTCOMES)}")

    event_type = f"hook.recovery_{outcome}"
    full_payload: dict = {"recovery_kind": kind}
    if run_id:
        full_payload["run_id"] = run_id
    if payload:
        full_payload.update(payload)

    env = os.environ.copy()
    if session_id:
        env["CLAUDE_SESSION_ID"] = session_id
    if repo_root:
        env["VG_REPO_ROOT"] = str(repo_root)

    try:
        proc = subprocess.run(
            [sys.executable, str(orchestrator_path), "emit-event",
             event_type,
             "--actor", "hook",
             "--outcome", "INFO" if outcome != "failed" else "WARN",
             "--payload", json.dumps(full_payload)],
            capture_output=True, text=True, timeout=10, env=env,
        )
        return proc.returncode
    except (subprocess.TimeoutExpired, OSError):
        # Telemetry is best-effort; do NOT raise (would break the recovery path itself).
        return 1
