"""
OHOK Batch 5 — honour-system loophole closures.

B8: Regression loop counter persistence
- test.md 5c_auto_escalate previously had prose "max 3 iterations" but
  NO file was read/written. Each /vg:test started fresh.
- Now persists .fix-loop-state.json with iteration_count + first_run_ts.

B9: Override-debt event correlation
- accept.md 3c gate previously accepted `resolved_by_event_id` values
  without verifying the event existed in telemetry. Fake UUID would pass.
- New validator check-override-events.py scans telemetry.jsonl + events.db,
  flags phantom event_ids.

E1 deferred: marker content schema — breaking change, needs migration
plan, not in this commit.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "test.md"
VALIDATOR = (REPO_ROOT / ".claude" / "scripts" / "validators"
             / "check-override-events.py")


@pytest.fixture(scope="module")
def test_text() -> str:
    return TEST_MD.read_text(encoding="utf-8")


def _extract_step(text: str, name: str) -> str:
    match = re.search(
        rf'<step name="{re.escape(name)}"[^>]*>(.+?)</step>',
        text, re.DOTALL,
    )
    assert match, f'step "{name}" missing'
    return match.group(1)


# ═══════════════════════════ B8: loop counter bash ═══════════════════════════

def test_b8_auto_escalate_has_real_counter_bash(test_text):
    """Step must have bash that reads/writes .fix-loop-state.json."""
    block = _extract_step(test_text, "5c_auto_escalate")
    assert "```bash" in block, "no bash block in 5c_auto_escalate"
    # Must reference the state file
    assert ".fix-loop-state.json" in block
    # Must have load + persist logic
    assert "FIX_LOOP_STATE" in block


def test_b8_counter_initializes_when_missing(test_text):
    block = _extract_step(test_text, "5c_auto_escalate")
    assert re.search(r'if \[ ! -f "\$FIX_LOOP_STATE" \]', block), (
        "missing initial-state check"
    )
    assert '"iteration_count": 0' in block
    assert "first_run_ts" in block


def test_b8_counter_reads_persisted_state(test_text):
    block = _extract_step(test_text, "5c_auto_escalate")
    # Must read iteration_count from JSON on subsequent runs
    assert re.search(
        r'json\.load.*FIX_LOOP_STATE.*iteration_count',
        block, re.DOTALL,
    ), "missing json.load of persisted state"


def test_b8_counter_enforces_budget_limit(test_text):
    """TOTAL_ITER >= MAX_ITER must trigger hard-stop path."""
    block = _extract_step(test_text, "5c_auto_escalate")
    assert re.search(r'TOTAL_ITER.*-ge.*MAX_ITER', block), (
        "missing budget-limit comparison"
    )
    assert "budget exhausted" in block.lower()
    # Must emit telemetry event so audit trail exists
    assert "test.fix_loop_exhausted" in block


def test_b8_counter_increments_persistently(test_text):
    block = _extract_step(test_text, "5c_auto_escalate")
    # Must do TOTAL_ITER+1 and write back to JSON
    assert re.search(r'TOTAL_ITER=\$\(\(TOTAL_ITER \+ 1\)\)', block), (
        "missing increment"
    )
    # And persist via json.dumps back to FIX_LOOP_STATE
    assert re.search(r'json\.dumps.*FIX_LOOP_STATE', block, re.DOTALL) or \
           re.search(r'json\.dumps.*iteration_count.*last_run_ts',
                     block, re.DOTALL), (
        "missing persist-after-increment"
    )


def test_b8_config_driven_max(test_text):
    """Max iterations threshold must be config-driven."""
    block = _extract_step(test_text, "5c_auto_escalate")
    assert "vg_config_get test.max_fix_loop_iterations" in block, (
        "threshold must read from config.test.max_fix_loop_iterations"
    )


# ═══════════════════════════ B9: validator ═══════════════════════════

def test_b9_validator_exists_and_executable():
    assert VALIDATOR.exists(), f"validator missing at {VALIDATOR}"
    # Python file syntax-valid
    r = subprocess.run(
        [sys.executable, "-c",
         f"import ast; ast.parse(open(r'{VALIDATOR}', encoding='utf-8').read())"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"validator syntax error:\n{r.stderr}"


def test_b9_validator_passes_on_missing_register(tmp_path):
    """No register = no overrides to verify = PASS."""
    r = subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--register", str(tmp_path / "does-not-exist.md")],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS"


def test_b9_validator_blocks_phantom_event_id(tmp_path):
    """Phantom resolved_by_event_id → BLOCK."""
    register = tmp_path / "OVERRIDE-DEBT.md"
    register.write_text("""\
# Override Debt Register

## Entry OD-001
- gate_id: accept-sandbox-verdict
- status: RESOLVED
- resolved_by_event_id: phantom-fake-1234-5678
- legacy: false
""", encoding="utf-8")

    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        json.dumps({"event_type": "other", "event_id": "real-uuid-aaaa"}) + "\n",
        encoding="utf-8",
    )

    r = subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--register", str(register),
         "--telemetry", str(telemetry),
         "--events-db", str(tmp_path / "nonexistent.db")],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 1, f"expected BLOCK rc=1, got {r.returncode}"
    out = json.loads(r.stdout)
    assert out["verdict"] == "BLOCK"
    evidence = out["evidence"]
    assert any("phantom" in e.get("type", "") for e in evidence)


def test_b9_validator_passes_verified_event_id(tmp_path):
    """Real resolved_by_event_id matches telemetry → PASS."""
    register = tmp_path / "OVERRIDE-DEBT.md"
    register.write_text("""\
# Override Debt Register

## Entry OD-002
- gate_id: review-goal-coverage
- status: RESOLVED
- resolved_by_event_id: real-aaaa-bbbb-cccc
- legacy: false
""", encoding="utf-8")

    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        json.dumps({"event_type": "override_resolved",
                    "event_id": "real-aaaa-bbbb-cccc",
                    "gate_id": "review-goal-coverage"}) + "\n",
        encoding="utf-8",
    )

    r = subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--register", str(register),
         "--telemetry", str(telemetry),
         "--events-db", str(tmp_path / "nonexistent.db")],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, f"expected PASS, got rc={r.returncode}:\n{r.stdout}\n{r.stderr}"
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS"


def test_b9_validator_accepts_legacy_entries_without_event_id(tmp_path):
    """legacy:true pre-v1.8.0 entries allowed without event_id."""
    register = tmp_path / "OVERRIDE-DEBT.md"
    register.write_text("""\
# Override Debt Register

## Entry OD-003
- gate_id: old-gate
- status: RESOLVED
- resolved_by_event_id:
- legacy: true
""", encoding="utf-8")

    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(json.dumps({"event_type": "x", "event_id": "some-uuid"}) + "\n",
                         encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--register", str(register),
         "--telemetry", str(telemetry),
         "--events-db", str(tmp_path / "nonexistent.db")],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, f"legacy entries should PASS, got {r.returncode}"


def test_b9_validator_reads_events_db_too(tmp_path):
    """v2.2 orchestrator stores events in sqlite — validator must read both."""
    register = tmp_path / "OVERRIDE-DEBT.md"
    register.write_text("""\
## Entry OD-004
- status: RESOLVED
- resolved_by_event_id: hash-abc-from-db
- legacy: false
""", encoding="utf-8")

    # Empty jsonl
    (tmp_path / "telemetry.jsonl").write_text("", encoding="utf-8")

    # events.db with the hash
    db_path = tmp_path / "events.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            this_hash TEXT,
            event_type TEXT
        )
    """)
    conn.execute("INSERT INTO events(this_hash, event_type) VALUES (?, ?)",
                 ("hash-abc-from-db", "override_resolved"))
    conn.commit()
    conn.close()

    r = subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--register", str(register),
         "--telemetry", str(tmp_path / "telemetry.jsonl"),
         "--events-db", str(db_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, f"expected PASS, got rc={r.returncode}:\n{r.stdout}\n{r.stderr}"


def test_b9_validator_unresolved_entries_skip_check(tmp_path):
    """status=UNRESOLVED shouldn't trigger event verification."""
    register = tmp_path / "OVERRIDE-DEBT.md"
    register.write_text("""\
## Entry OD-005
- gate_id: pending-gate
- status: UNRESOLVED
- resolved_by_event_id:
- legacy: false
""", encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--register", str(register),
         "--telemetry", str(tmp_path / "empty.jsonl"),
         "--events-db", str(tmp_path / "empty.db")],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, (
        f"UNRESOLVED entries shouldn't need event check, got {r.returncode}"
    )
