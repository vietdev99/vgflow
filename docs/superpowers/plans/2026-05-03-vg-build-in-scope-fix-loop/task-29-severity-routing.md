<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 29: Severity routing functional (Diagnostic-v2)

**Why:** Codex GPT-5.5 round 6 missing-proposal #3: today block payloads can carry a `severity` field but it's cosmetic — every block exits 2 (BLOCK). This task makes the field actually steer hook behavior:

| Severity | Stop hook behavior | Pairing requirement |
|---|---|---|
| `warn` | log to stderr (no orange title), DO NOT exit 2 | optional handled (warns accumulate) |
| `error` (default) | orange ANSI title, exit 2 | handled REQUIRED for Stop pass |
| `critical` | red ANSI title, exit 2, force AskUserQuestion banner injection | handled REQUIRED + escalation if refire ≥ 2 |

**Depends on Task 28** because severity changes the dedupe behavior for warn-tier (warns can refire freely; critical-tier escalates on refire).

**Files:**
- Create: `scripts/lib/block_severity.py`
- Create: `tests/test_block_severity_routing.py`
- Modify: `scripts/hooks/vg-stop.sh` (severity-aware pairing)
- Modify: `scripts/hooks/vg-pre-tool-use-bash.sh` (pass --severity to emit-event)
- Modify: `scripts/hooks/vg-pre-tool-use-write.sh` (same)
- Modify: `scripts/hooks/vg-pre-tool-use-agent.sh` (same)
- Modify: `scripts/vg-verify-claim.py::_emit_stale_block` (severity=error default; Stop-stale-run can be warn after Task 31 cross-session label)
- Modify: `.claude/scripts/vg-orchestrator/__main__.py::cmd_emit_event` (validate severity, default to "error", merge into payload)

- [ ] **Step 1: Write the severity helper module**

Create `scripts/lib/block_severity.py`:

```python
"""block_severity — single source of truth for severity → behavior mapping.

Severity levels:
  warn     — log only; Stop hook does NOT exit 2 on warn-only obligations
  error    — default; orange ANSI; Stop hook exits 2 if unpaired
  critical — red ANSI; Stop hook exits 2 + injects AskUserQuestion hint;
             refire (Task 28) ≥ 2 escalates to mandatory user question

Behavior table is LOCKED. Adding a new severity requires updating this
module, the Stop hook query, AND the test matrix.
"""
from __future__ import annotations

from dataclasses import dataclass

VALID_SEVERITIES = ("warn", "error", "critical")
DEFAULT_SEVERITY = "error"


@dataclass(frozen=True)
class SeverityBehavior:
    severity: str
    ansi_color: str               # ANSI escape code (orange/red/yellow)
    exits_stop_hook: bool         # True if unpaired blocks exit 2
    requires_handled: bool        # True if Stop hook pairing requires handled
    forces_user_question: bool    # True if SessionStart should inject AskUserQuestion banner

ANSI_ORANGE = "\033[38;5;208m"
ANSI_RED = "\033[31m"
ANSI_YELLOW = "\033[33m"

BEHAVIORS: dict[str, SeverityBehavior] = {
    "warn": SeverityBehavior(
        severity="warn",
        ansi_color=ANSI_YELLOW,
        exits_stop_hook=False,
        requires_handled=False,
        forces_user_question=False,
    ),
    "error": SeverityBehavior(
        severity="error",
        ansi_color=ANSI_ORANGE,
        exits_stop_hook=True,
        requires_handled=True,
        forces_user_question=False,
    ),
    "critical": SeverityBehavior(
        severity="critical",
        ansi_color=ANSI_RED,
        exits_stop_hook=True,
        requires_handled=True,
        forces_user_question=True,
    ),
}


def normalize(s: str | None) -> str:
    """Map None/empty/invalid → DEFAULT_SEVERITY. Lowercase normalize."""
    if not s:
        return DEFAULT_SEVERITY
    s = s.strip().lower()
    return s if s in VALID_SEVERITIES else DEFAULT_SEVERITY


def behavior(severity: str | None) -> SeverityBehavior:
    return BEHAVIORS[normalize(severity)]


def ansi_for(severity: str | None) -> str:
    return behavior(severity).ansi_color
```

- [ ] **Step 2: Update emit-event parser to accept --severity**

In `.claude/scripts/vg-orchestrator/__main__.py`, find the `emit-event` subparser block (added in P0 fix `ae498ed`, lines around 4355-4395). Add a `--severity` flag with the same merge-into-payload pattern:

```python
# After --block-file:
s.add_argument("--severity", default=None,
               choices=["warn", "error", "critical"],
               help="Block severity tier (warn=log-only, error=default-block, critical=force-question)")
```

In `cmd_emit_event` (around line 1228-1290), extend the merge loop:

```python
for flag_name, payload_key in (
    ("gate", "gate"),
    ("cause", "cause"),
    ("resolution", "resolution"),
    ("block_file", "block_file"),
    ("severity", "severity"),
):
    flag_val = getattr(args, flag_name, None)
    if flag_val is not None and payload_key not in payload:
        payload[payload_key] = flag_val

# After the merge: default block-event severity to "error" if not set
if args.event_type in ("vg.block.fired", "vg.block.refired") and "severity" not in payload:
    payload["severity"] = "error"
```

Mirror to `scripts/vg-orchestrator/__main__.py`.

- [ ] **Step 3: Update bash hooks to pass --severity**

Each hook chooses severity per gate. Most existing block emits stay at `error` default. Make these explicitly:

- `vg-pre-tool-use-bash.sh::emit_block` → severity=error (current behavior preserved)
- `vg-pre-tool-use-write.sh::emit_block` → severity=critical for protected paths (data integrity risk)
- `vg-pre-tool-use-agent.sh::emit_block` → severity=error (allowlist violation)
- `vg-verify-claim.py::_emit_stale_block` → severity=warn (stale runs are usually idle; not a contract violation)

For each emit-event call, add `--severity X` flag (after `--block-file`). Bash example:

```bash
vg-orchestrator emit-event "$EVENT_TYPE" \
  --gate "$gate_id" --cause "$cause" --block-file "$block_file" \
  --severity error \
  >/dev/null 2>&1 || true
```

Bash hooks that print to stderr should use the severity color:

```bash
# Pick color from severity
case "$severity" in
  warn)     ansi="\033[33m" ;;       # yellow
  critical) ansi="\033[31m" ;;       # red
  *)        ansi="\033[38;5;208m" ;; # orange (error default)
esac
printf "${ansi}%s: %s\033[0m\n" "$gate_id" "$cause" >&2
```

- [ ] **Step 4: Update Stop hook pairing for severity**

In `scripts/hooks/vg-stop.sh`, the pairing query (now from Task 28) treats every fired gate as obligation. Add severity gating:

```bash
# After Task 28 dedupe wiring, refine to count only error+critical-tier gates as
# obligations. Warn-tier gates can be unpaired and still pass.

fired_obligation_gates="$(sqlite3 "$db" "
  SELECT COUNT(DISTINCT json_extract(payload_json, '\$.gate'))
  FROM events
  WHERE run_id='$run_id' AND event_type IN ('vg.block.fired', 'vg.block.refired')
  AND COALESCE(json_extract(payload_json, '\$.severity'), 'error') IN ('error', 'critical')
")"

handled_gates="$(sqlite3 "$db" "
  SELECT COUNT(DISTINCT json_extract(payload_json, '\$.gate'))
  FROM events
  WHERE run_id='$run_id' AND event_type='vg.block.handled'
")"

# Critical-tier escalation: refire count ≥ 2 → force user question banner
critical_refires="$(sqlite3 "$db" "
  SELECT json_extract(payload_json, '\$.gate'), COUNT(*) cnt
  FROM events
  WHERE run_id='$run_id' AND event_type='vg.block.refired'
  AND json_extract(payload_json, '\$.severity') = 'critical'
  GROUP BY json_extract(payload_json, '\$.gate')
  HAVING cnt >= 2
")"

if [ "$fired_obligation_gates" -gt "$handled_gates" ]; then
  failures+=("UNHANDLED DIAGNOSTIC: ${fired_obligation_gates} obligation gates fired, ${handled_gates} handled")
fi

if [ -n "$critical_refires" ]; then
  failures+=("CRITICAL ESCALATION: gate(s) refired ≥ 2 times at critical severity — must AskUserQuestion before retry")
fi
```

- [ ] **Step 5: Tests**

Create `tests/test_block_severity_routing.py`:

```python
"""Task 29 — severity actually changes hook behavior.

Pin the table:
  warn     → no exit 2, can be unpaired
  error    → exit 2 if unpaired (current default)
  critical → exit 2 + escalation hint when refire ≥ 2
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCH = str(REPO_ROOT / ".claude/scripts/vg-orchestrator")
STOP_HOOK = str(REPO_ROOT / "scripts/hooks/vg-stop.sh")

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))


def _setup_run(tmp: Path) -> dict:
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp)
    env["CLAUDE_SESSION_ID"] = "test-severity"
    rs = subprocess.run(
        [sys.executable, ORCH, "run-start", "vg:accept", "99.9.9"],
        env=env, capture_output=True, text=True, cwd=str(tmp), timeout=15,
    )
    assert rs.returncode == 0, rs.stderr
    return env


def _emit(env, tmp, etype, gate, severity=None, **extra):
    cmd = [sys.executable, ORCH, "emit-event", etype,
           "--actor", "hook", "--outcome", "BLOCK",
           "--gate", gate, "--cause", "t"]
    if severity:
        cmd += ["--severity", severity]
    if extra:
        cmd += ["--payload", json.dumps(extra)]
    proc = subprocess.run(cmd, env=env, cwd=str(tmp), capture_output=True,
                          text=True, timeout=10)
    return proc


def test_helper_normalizes_severity():
    from block_severity import normalize, DEFAULT_SEVERITY
    assert normalize(None) == DEFAULT_SEVERITY
    assert normalize("") == DEFAULT_SEVERITY
    assert normalize("BOGUS") == DEFAULT_SEVERITY
    assert normalize("WARN") == "warn"
    assert normalize("Critical") == "critical"


def test_helper_behavior_table_locked():
    from block_severity import BEHAVIORS, VALID_SEVERITIES
    assert set(BEHAVIORS.keys()) == set(VALID_SEVERITIES)
    assert BEHAVIORS["warn"].exits_stop_hook is False
    assert BEHAVIORS["error"].exits_stop_hook is True
    assert BEHAVIORS["critical"].forces_user_question is True


def test_emit_with_severity_flag(tmp_path):
    env = _setup_run(tmp_path)
    proc = _emit(env, tmp_path, "vg.block.fired", "g1", severity="warn")
    assert proc.returncode == 0


def test_emit_invalid_severity_rejected(tmp_path):
    env = _setup_run(tmp_path)
    proc = _emit(env, tmp_path, "vg.block.fired", "g1", severity="bogus")
    assert proc.returncode != 0


def test_warn_unpaired_does_not_block_stop(tmp_path):
    """Severity=warn fired without handled should NOT cause Stop exit 2."""
    env = _setup_run(tmp_path)
    _emit(env, tmp_path, "vg.block.fired", "g_warn", severity="warn")
    proc = subprocess.run(
        ["bash", STOP_HOOK], input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": env["CLAUDE_SESSION_ID"]},
        cwd=str(tmp_path),
    )
    # Stop may still fail for OTHER reasons (state machine etc.) but
    # not specifically for unpaired warn block.
    assert "UNHANDLED DIAGNOSTIC" not in proc.stderr


def test_error_unpaired_blocks_stop(tmp_path):
    """Severity=error fired without handled MUST cause Stop UNHANDLED."""
    env = _setup_run(tmp_path)
    _emit(env, tmp_path, "vg.block.fired", "g_err", severity="error")
    proc = subprocess.run(
        ["bash", STOP_HOOK], input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": env["CLAUDE_SESSION_ID"]},
        cwd=str(tmp_path),
    )
    assert proc.returncode == 2
    assert "UNHANDLED" in proc.stderr.upper()


def test_critical_refire_two_escalates(tmp_path):
    """Critical fired + 2× refire (no handled) → CRITICAL ESCALATION line."""
    env = _setup_run(tmp_path)
    _emit(env, tmp_path, "vg.block.fired", "g_crit", severity="critical")
    _emit(env, tmp_path, "vg.block.refired", "g_crit", severity="critical", fire_count=2)
    _emit(env, tmp_path, "vg.block.refired", "g_crit", severity="critical", fire_count=3)
    proc = subprocess.run(
        ["bash", STOP_HOOK], input="{}", capture_output=True, text=True,
        env={**os.environ, "CLAUDE_HOOK_SESSION_ID": env["CLAUDE_SESSION_ID"]},
        cwd=str(tmp_path),
    )
    assert proc.returncode == 2
    assert "CRITICAL ESCALATION" in proc.stderr or "AskUserQuestion" in proc.stderr


def test_default_severity_is_error_for_block_events(tmp_path):
    """vg.block.fired without --severity flag → payload.severity == 'error'."""
    env = _setup_run(tmp_path)
    _emit(env, tmp_path, "vg.block.fired", "g_default")
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / ".vg/events.db"))
    row = conn.execute(
        "SELECT payload_json FROM events WHERE event_type='vg.block.fired' "
        "AND json_extract(payload_json, '$.gate') = 'g_default' LIMIT 1"
    ).fetchone()
    conn.close()
    payload = json.loads(row[0])
    assert payload.get("severity") == "error"
```

- [ ] **Step 6: Smoke run**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_block_severity_routing.py -v
```

Expected: 8/8 PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/block_severity.py \
        scripts/vg-orchestrator/__main__.py \
        .claude/scripts/vg-orchestrator/__main__.py \
        scripts/hooks/vg-stop.sh \
        scripts/hooks/vg-pre-tool-use-bash.sh \
        scripts/hooks/vg-pre-tool-use-write.sh \
        scripts/hooks/vg-pre-tool-use-agent.sh \
        scripts/vg-verify-claim.py \
        .claude/scripts/vg-verify-claim.py \
        tests/test_block_severity_routing.py
git commit -m "$(cat <<'EOF'
feat(diag-v2): severity routing functional — warn/error/critical (Task 29)

Pre-fix: severity field in block payload was cosmetic. All blocks
exited 2 regardless of label.

Post-fix:
- warn   → log-only (yellow ANSI), Stop does NOT exit 2 on unpaired
- error  → orange ANSI, Stop exits 2 if unpaired (current default)
- critical → red ANSI, Stop exits 2 + CRITICAL ESCALATION line on
             refire ≥ 2 (force AskUserQuestion before retry)

scripts/lib/block_severity.py is single source of truth for the
severity → behavior mapping. emit-event parser validates --severity
choice. Stop hook query branches on severity for pairing requirement.

Existing block sites set severity explicitly:
- protected-path violation → critical (data integrity)
- stale-run BLOCK → warn (idle session, not a contract violation)
- everything else → error (default)

8 tests covering normalize/behavior/CLI/pairing/escalation/default.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Codex round 6 correction notes (inlined)

- **Q:** Why not three separate event types (`vg.block.warn_fired` etc.) instead of one type with a payload field?
  **A:** Stop hook pairing already queries on `event_type IN ('vg.block.fired', 'vg.block.refired')`. Doubling that surface to 6 types complicates every consumer. JSON1 path lookup on payload is fast.

- **Q:** Could a misconfigured hook silently downgrade everything to warn?
  **A:** Possible but observable: Task 32 correlator's high-velocity rule treats warn+error+critical equally. Warn gates accumulating with no handled = visible in correlator output. Operator can grep events.db payload.severity distribution.
