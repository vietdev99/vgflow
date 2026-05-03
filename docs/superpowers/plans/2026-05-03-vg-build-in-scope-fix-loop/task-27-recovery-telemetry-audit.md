<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 27: Recovery telemetry audit (Diagnostic-v2 P5 revised)

**Why:** `vg-recovery.py --auto` (`.claude/scripts/vg-recovery.py:239-244`) records actions in stdout only. The Stop hook auto-fire path (`scripts/vg-verify-claim.py:599-605`) emits `hook.marker_drift_recovered` on success but NOT on attempt or failure — so when migrate-state runs but doesn't fully resolve, the partial fix is invisible to telemetry. Codex GPT-5.5 round 6 finding: silent auto-recovery is worse than a block; the same drift will recur next run with no audit trail. This task introduces a uniform `emit_recovery_event(kind, ...)` helper and wires it into every auto-fire path so events.db tells the full story.

**Files:**
- Create: `scripts/lib/recovery_telemetry.py`
- Create: `scripts/validators/audit-recovery-telemetry.py`
- Create: `tests/test_recovery_telemetry.py`
- Modify: `scripts/vg-verify-claim.py` (auto-fire success path + new failure path)
- Modify: `.claude/scripts/vg-recovery.py` (every auto-recovery action emits attempted + result)

- [ ] **Step 1: Write the helper module**

Create `scripts/lib/recovery_telemetry.py`:

```python
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
        raise ValueError(f"unknown recovery kind: {kind!r}; expected one of {RECOVERY_KINDS}")
    if outcome not in {"attempted", "succeeded", "failed"}:
        raise ValueError(f"unknown outcome: {outcome!r}")

    event_type = f"hook.recovery_{outcome}"
    full_payload = {"recovery_kind": kind}
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
        # Telemetry is best-effort; do NOT raise from here (would break
        # the recovery path itself).
        return 1
```

- [ ] **Step 2: Wire into vg-verify-claim.py auto-fire path**

Find the existing `_auto_fire_markers` block in `scripts/vg-verify-claim.py` (around line 334-351). Wrap it with attempted + result emissions. After Step 2 is complete, the block looks like:

```python
# AT TOP OF FILE (with other imports), add:
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
try:
    from recovery_telemetry import emit as emit_recovery
except ImportError:
    emit_recovery = None  # graceful degradation if helper missing

# IN THE auto-fire branch (currently around line 492-535), ADD before _auto_fire_markers call:
if emit_recovery is not None:
    emit_recovery("marker_drift", "attempted",
                  run_id=run_id,
                  payload={"phase": phase, "drift_count": new_count},
                  session_id=session_id,
                  repo_root=str(REPO_ROOT))

ar_rc, ar_out, ar_err = _auto_fire_markers(phase, session_id=session_id)

if ar_rc == 0:
    rc2, sout2, serr2 = run_orchestrator_complete(session_id=session_id)
    if rc2 == 0:
        # SUCCESS path — replace the existing _emit_telemetry call (which emitted
        # hook.marker_drift_recovered) with the unified helper:
        if emit_recovery is not None:
            emit_recovery("marker_drift", "succeeded",
                          run_id=run_id,
                          payload={"phase": phase, "drift_count": new_count,
                                   "violations": sorted(violation_types),
                                   "migrate_state_stdout": ar_out[:500]},
                          session_id=session_id,
                          repo_root=str(REPO_ROOT))
        # ... rest of approve flow unchanged
    else:
        # NEW: explicit failure emit (post-migrate-state still BLOCKs)
        if emit_recovery is not None:
            emit_recovery("marker_drift", "failed",
                          run_id=run_id,
                          payload={"phase": phase, "drift_count": new_count,
                                   "stage": "post_migrate_run_complete",
                                   "stdout": sout2[:500], "stderr": serr2[:500]},
                          session_id=session_id,
                          repo_root=str(REPO_ROOT))
        # ... fall-through unchanged
else:
    # NEW: migrate-state itself failed
    if emit_recovery is not None:
        emit_recovery("marker_drift", "failed",
                      run_id=run_id,
                      payload={"phase": phase, "drift_count": new_count,
                               "stage": "migrate_state_apply",
                               "rc": ar_rc, "stderr": ar_err[:500]},
                      session_id=session_id,
                      repo_root=str(REPO_ROOT))
    # ... fall-through unchanged
```

NOTE: keep the legacy `_emit_telemetry("hook.marker_drift_recovered", ...)` call as well — it's referenced by an existing test (`scripts/tests/test_verify_claim_hybrid.py:201-205`). Both are emitted; once Task 21 dogfood lands, follow-up cleanup PR can remove the legacy event in favor of the unified `hook.recovery_succeeded` payload.

Also wire `vg-recovery.py` v2.46 auto-recovery branch (around line 547-594 in `scripts/vg-verify-claim.py`) the same way — add `emit_recovery("vg_recovery_auto", "attempted"/"succeeded"/"failed", ...)` around the `subprocess.run([...recovery-script..., '--auto', '--json'])` call.

- [ ] **Step 3: Wire into .claude/scripts/vg-recovery.py**

Find the `--auto` mode in `.claude/scripts/vg-recovery.py` (around line 200-260, where `auto_executable` paths are run). Each path that subprocess-invokes a recovery action should:
1. Call `emit_recovery(kind="vg_recovery_auto", outcome="attempted", payload={"path_id": ..., "violation_type": ...})` BEFORE.
2. Call `emit_recovery(kind="vg_recovery_auto", outcome="succeeded"/"failed", payload={..., "rc": ..., "stderr_excerpt": ...})` AFTER, branching on subprocess.returncode.

Use the same `sys.path.insert + import` pattern as Step 2.

- [ ] **Step 4: Write the audit validator**

Create `scripts/validators/audit-recovery-telemetry.py`:

```python
"""audit-recovery-telemetry — static validator that runs in CI.

Walks every Python file that imports `subprocess` AND mentions
`migrate-state` OR `vg-recovery` in the same file, and asserts that
each `subprocess.run([...migrate-state...])` call site has a sibling
`emit_recovery(...)` call within ±20 lines (proxy for "in same code
path").

Goal: prevent silent regression where a future PR adds a new auto-fire
path without paired telemetry. Empirical cost of letting that slip:
Codex GPT-5.5 round 6 found the existing `marker_drift_recovered` was
referenced in code comments but never emitted across hundreds of runs.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

AUTO_FIRE_TARGETS = [
    "migrate-state",
    "vg-recovery.py",
]

EMIT_PATTERN = re.compile(r"emit_recovery\s*\(", re.MULTILINE)


def find_violations() -> list[tuple[str, int, str]]:
    """Return list of (file, line, snippet) for unpaired auto-fire calls."""
    violations: list[tuple[str, int, str]] = []
    for py in REPO_ROOT.rglob("*.py"):
        # Skip the helper itself + tests + .worktrees
        if "recovery_telemetry.py" in str(py):
            continue
        if "/tests/" in str(py).replace("\\", "/"):
            continue
        if "/.worktrees/" in str(py).replace("\\", "/"):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(t in text for t in AUTO_FIRE_TARGETS):
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "subprocess.run" not in line:
                continue
            # Look ahead 5 lines for the target string (typical run() spans
            # 1-5 lines for the cmd list).
            window = "\n".join(lines[i:i + 6])
            if not any(t in window for t in AUTO_FIRE_TARGETS):
                continue
            # Found an auto-fire subprocess. Look ±20 lines for emit_recovery.
            start = max(0, i - 20)
            end = min(len(lines), i + 20)
            ctx = "\n".join(lines[start:end])
            if not EMIT_PATTERN.search(ctx):
                violations.append((str(py.relative_to(REPO_ROOT)), i + 1,
                                   line.strip()[:120]))
    return violations


def main() -> int:
    v = find_violations()
    if not v:
        print("audit-recovery-telemetry: PASS (every auto-fire path has paired emit_recovery)")
        return 0
    print(f"audit-recovery-telemetry: FAIL — {len(v)} unpaired auto-fire call(s):", file=sys.stderr)
    for f, ln, snip in v:
        print(f"  {f}:{ln}  {snip}", file=sys.stderr)
    print("\nFix: wrap the subprocess.run call with emit_recovery('<kind>', 'attempted'/...)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Write tests**

Create `tests/test_recovery_telemetry.py`:

```python
"""Task 27 — recovery telemetry contract.

Empirical pin: every auto-fire path emits attempted + result events.
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

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))


def _setup_run(tmp: Path) -> dict:
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp)
    env["CLAUDE_SESSION_ID"] = "test-recovery-telemetry"
    rs = subprocess.run(
        [sys.executable, ORCH, "run-start", "vg:accept", "99.9.9"],
        env=env, capture_output=True, text=True, cwd=str(tmp), timeout=15,
    )
    assert rs.returncode == 0, rs.stderr
    return env


def _events(repo: Path, prefix: str) -> list[dict]:
    conn = sqlite3.connect(str(repo / ".vg/events.db"))
    rows = conn.execute(
        "SELECT event_type, outcome, payload_json FROM events "
        "WHERE event_type LIKE ? ORDER BY id", (f"{prefix}%",)
    ).fetchall()
    conn.close()
    return [{"type": r[0], "outcome": r[1], "payload": json.loads(r[2])}
            for r in rows]


def test_emit_attempted_succeeded_pair(tmp_path):
    from recovery_telemetry import emit
    env = _setup_run(tmp_path)
    rc1 = emit("marker_drift", "attempted",
               run_id="testrun", payload={"phase": "9.9.9"},
               orchestrator_path=ORCH,
               session_id=env["CLAUDE_SESSION_ID"], repo_root=tmp_path)
    rc2 = emit("marker_drift", "succeeded",
               run_id="testrun", payload={"phase": "9.9.9"},
               orchestrator_path=ORCH,
               session_id=env["CLAUDE_SESSION_ID"], repo_root=tmp_path)
    assert rc1 == 0 and rc2 == 0
    evts = _events(tmp_path, "hook.recovery_")
    types = [e["type"] for e in evts]
    assert "hook.recovery_attempted" in types
    assert "hook.recovery_succeeded" in types
    assert evts[0]["payload"]["recovery_kind"] == "marker_drift"


def test_emit_failed_records_stage_and_stderr(tmp_path):
    from recovery_telemetry import emit
    env = _setup_run(tmp_path)
    emit("marker_drift", "attempted", run_id="r", payload={"phase": "9.9.9"},
         orchestrator_path=ORCH, session_id=env["CLAUDE_SESSION_ID"],
         repo_root=tmp_path)
    emit("marker_drift", "failed",
         run_id="r",
         payload={"phase": "9.9.9", "stage": "migrate_state_apply",
                  "rc": 127, "stderr": "no such file"},
         orchestrator_path=ORCH, session_id=env["CLAUDE_SESSION_ID"],
         repo_root=tmp_path)
    evts = _events(tmp_path, "hook.recovery_")
    failed = [e for e in evts if e["type"] == "hook.recovery_failed"]
    assert len(failed) == 1
    assert failed[0]["payload"]["stage"] == "migrate_state_apply"
    assert failed[0]["payload"]["rc"] == 127


def test_unknown_kind_rejected():
    from recovery_telemetry import emit
    import pytest
    with pytest.raises(ValueError, match="unknown recovery kind"):
        emit("not_a_real_kind", "attempted")


def test_unknown_outcome_rejected():
    from recovery_telemetry import emit
    import pytest
    with pytest.raises(ValueError, match="unknown outcome"):
        emit("marker_drift", "completed_maybe")


def test_audit_validator_passes_on_clean_tree():
    """Run the audit validator against the live repo. After Steps 2-3 of
    this task land, every auto-fire site must have paired emit_recovery."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/validators/audit-recovery-telemetry.py")],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, (
        f"audit failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
```

- [ ] **Step 6: Smoke run**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_recovery_telemetry.py -v
python3 scripts/validators/audit-recovery-telemetry.py
```

Expected: 5/5 tests PASS, audit validator exits 0.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/recovery_telemetry.py \
        scripts/validators/audit-recovery-telemetry.py \
        scripts/vg-verify-claim.py \
        .claude/scripts/vg-verify-claim.py \
        .claude/scripts/vg-recovery.py \
        tests/test_recovery_telemetry.py
git commit -m "$(cat <<'EOF'
feat(diag-v2): recovery telemetry audit + uniform emit helper (Task 27)

Pre-fix: vg-recovery.py --auto logged actions to stdout only;
vg-verify-claim Tier C auto-fire emitted hook.marker_drift_recovered on
success but not on attempt or failure. Codex GPT-5.5 round 6: silent
auto-recovery is worse than a block — same drift recurs next run with
no audit trail.

Fix:
- New scripts/lib/recovery_telemetry.py with emit() helper enforcing
  3-tuple contract: attempted → (succeeded|failed). Reserved kinds list
  prevents typo drift.
- Wire into vg-verify-claim.py auto-fire paths (marker_drift kind) +
  vg-recovery.py --auto safe-paths (vg_recovery_auto kind).
- New scripts/validators/audit-recovery-telemetry.py: static check that
  every subprocess.run(migrate-state | vg-recovery) has paired
  emit_recovery within ±20 lines. Prevents future regression.
- 5 tests covering attempted/succeeded/failed pairing + reserved kinds +
  audit validator gate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Codex GPT-5.5 round 6 correction notes (inlined)

- **Q:** Why keep legacy `hook.marker_drift_recovered` event alongside `hook.recovery_succeeded`?
  **A:** Existing test `scripts/tests/test_verify_claim_hybrid.py:201-205` asserts the legacy event is emitted. Removing it would break the test in this commit. Cleanup PR after Task 21 dogfood: remove legacy emit + update test to assert `hook.recovery_succeeded` with `recovery_kind: marker_drift` payload key.

- **Q:** Why not auto-emit from `emit-event` parser when event_type starts with `hook.recovery_`?
  **A:** Tempting but dangerous: it would emit twice when the helper is also called explicitly. Single-source-of-truth is `recovery_telemetry.emit()`. Audit validator catches future violators.

- **Q:** Why static audit instead of runtime gate?
  **A:** Runtime gate would need to count attempts vs results per-run, which means a new SQL query in Stop hook (latency budget). Static validator runs once in CI; CI cost amortized over many PRs.
