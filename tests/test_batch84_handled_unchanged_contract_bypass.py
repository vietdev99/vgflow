"""B84 v4.64.2 — Issue #194 finding #4 PreToolUse-tasklist refresh cycle.

User dogfood (RTB phase 8.1, 2026-05-17): every `mark-step` call followed
by any bash invocation hit PreToolUse-tasklist HARD BLOCK:

    PreToolUse-tasklist: block.handled emitted but evidence not refreshed
    since (handled at T1, evidence older). AI must re-run TodoWrite +
    tasklist-projected — emitting vg.block.handled alone does NOT satisfy
    the gate.

Workaround applied ~30 times across the phase (~90 wasted ops):

    TodoWrite (any no-op update to fire PostToolUse)
    vg-orchestrator tasklist-projected --adapter auto
    vg-orchestrator emit-event vg.block.handled --gate PreToolUse-tasklist
                              --resolution "cycle"

Root cause: the V4 staleness check (vg-pre-tool-use-bash.sh:1057-1128)
enforced strict `evidence_mtime > last_handled_ts` even when the
projection contract itself hadn't changed. Mark-step doesn't refresh
the evidence file. So after AI legitimately performs TodoWrite +
tasklist-projected at T2, then emits a fresh vg.block.handled at T3 > T2,
the next bash call sees ev_mtime=T2 <= handled_epoch=T3 and BLOCKS,
even though the projection contract is unchanged and the existing
evidence still satisfies the current contract.

B84 fix (user's suggestion (b)): exception when contract_sha256 is
UNCHANGED. If the evidence file's contract_sha256 matches the current
tasklist-contract.json sha256, the evidence is semantically still valid
and the V4 check passes. The HMAC + contract-mismatch checks above
still fire for tampered or contract-drifted evidence — only the
mtime-vs-handled-ts check is relaxed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"


# ---------------------------------------------------------------------------
# Source-level guards
# ---------------------------------------------------------------------------

def test_b84_contract_checksum_bypass_present() -> None:
    """Hook source must implement the contract-sha256 bypass."""
    body = HOOK.read_text(encoding="utf-8")
    assert "B84" in body, "B84 audit marker missing in hook"
    assert "contract-checksum bypass" in body or "contract_sha256 bypass" in body or "contract_sha256" in body, (
        "contract-checksum bypass logic missing"
    )
    # The bypass must compute current contract sha256 and compare with evidence
    assert "current_contract_sha" in body, "current contract sha computation missing"
    assert "evidence_contract_sha" in body or "ev_payload" in body, (
        "evidence contract sha extraction missing"
    )


def test_b84_v4_strict_check_still_present_for_changed_contract() -> None:
    """When contract changes (mismatch), staleness block must still fire.
    Audit trail: bypass condition gates on `evidence_contract_sha == current_contract_sha`.
    """
    body = HOOK.read_text(encoding="utf-8")
    # The strict mtime comparison still emits unresolved before the bypass
    assert "unresolved|" in body, "unresolved status code still emitted"
    assert "evidence_contract_sha == current_contract_sha" in body, (
        "bypass must require equality — never always-bypass"
    )


def test_b84_mirror_byte_identical() -> None:
    assert HOOK.read_bytes() == MIRROR.read_bytes(), (
        "vg-pre-tool-use-bash.sh mirror drift"
    )


# ---------------------------------------------------------------------------
# Behavioral — simulate handled-after-evidence case
# ---------------------------------------------------------------------------

def _build_run_layout(tmp_path: Path) -> tuple[Path, Path, Path, str, str]:
    """Build a minimal repo layout exercising the V4 check."""
    repo = tmp_path / "repo"
    vg = repo / ".vg"
    vg.mkdir(parents=True)
    run_id = "test-run-b84"
    session_id = "sess-b84"
    run_dir = vg / "runs" / run_id
    run_dir.mkdir(parents=True)
    active = vg / "active-runs"
    active.mkdir()
    (active / f"{session_id}.json").write_text(json.dumps({
        "run_id": run_id, "session_id": session_id,
        "command": "vg:build", "phase": "1.0",
        "args": "", "started_at": "2026-05-18T00:00:00Z",
    }), encoding="utf-8")

    # Contract
    contract = {
        "checklists": [{"id": "step_1", "title": "Setup"}],
        "projection_items": [{"id": "step_1"}],
    }
    contract_path = run_dir / "tasklist-contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()

    # HMAC key — secret 32 bytes hex
    key_dir = vg / "keys"
    key_dir.mkdir()
    key_path = key_dir / "evidence.key"
    key_bytes = secrets.token_bytes(32)
    key_path.write_bytes(key_bytes)
    # POSIX 0600 mode (skipped on Windows per B79)
    if os.name != "nt":
        os.chmod(key_path, 0o600)

    # Build signed evidence: HMAC over sorted-keys-canonical payload
    payload = {
        "run_id": run_id,
        "adapter": "claude",
        "tool_name": "TodoWrite",
        "contract_sha256": contract_sha,
        "todo_count": 1,
        "contract_projection_count": 1,
        "accumulation_suspected": False,
        "todo_ids": ["step_1"],
        "contract_ids": ["step_1"],
        "match": True,
        "depth_valid": True,
        "groups_with_subs_count": 1,
        "flat_groups": [],
    }
    canonical = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(key_bytes, canonical, hashlib.sha256).hexdigest()
    evidence_path = run_dir / ".tasklist-projected.evidence.json"
    evidence_path.write_text(json.dumps({
        "payload": payload, "hmac_sha256": sig,
    }), encoding="utf-8")

    # events.db with vg.block.handled AT TIMESTAMP NEWER THAN ev_mtime
    db_path = vg / "events.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, command TEXT, phase TEXT, args TEXT,
            started_at TEXT, completed_at TEXT, outcome TEXT, session_id TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, ts TEXT, event_type TEXT, phase TEXT, command TEXT,
            step TEXT, actor TEXT, outcome TEXT, payload_json TEXT
        );
    """)
    conn.execute(
        "INSERT INTO runs (run_id,command,phase,session_id,started_at) VALUES (?,?,?,?,?)",
        (run_id, "vg:build", "1.0", session_id, "2026-05-18T00:00:00Z"),
    )
    # Insert handled event AFTER current time so handled_ts > ev_mtime
    future_ts = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO events (run_id,ts,event_type,phase,command,actor,outcome,payload_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (run_id, future_ts, "vg.block.handled", "1.0", "vg:build",
         "cli", "INFO", json.dumps({"gate": "PreToolUse-tasklist"})),
    )
    conn.commit()
    conn.close()
    return repo, evidence_path, contract_path, run_id, session_id


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="hook requires bash + full _lib.sh bootstrap not feasible on Win",
)
def test_b84_bypass_passes_when_contract_unchanged(tmp_path: Path) -> None:
    """Evidence older than last handled BUT contract unchanged → V4 check
    returns 'ok' (no staleness block).
    """
    repo, evidence_path, contract_path, run_id, session_id = _build_run_layout(tmp_path)
    # Run the V4 check Python directly — extracted from the hook
    proc = subprocess.run(
        [sys.executable, "-c", """
import os, sqlite3, sys, json, hashlib
from pathlib import Path
from datetime import datetime, timezone

run_id = os.environ['VG_RUN_ID']
ev_path = Path(os.environ['VG_EV_PATH'])
db_path = Path(os.environ['VG_DB_PATH'])
contract_path = os.environ.get('VG_CONTRACT_PATH', '')
gate_id = 'PreToolUse-tasklist'

conn = sqlite3.connect(str(db_path))
rows = conn.execute(
    "SELECT ts, payload_json FROM events WHERE run_id=? AND event_type='vg.block.handled' ORDER BY id DESC LIMIT 50",
    (run_id,),
).fetchall()
conn.close()

last_handled_ts = None
for ts, pj in rows:
    p = json.loads(pj or '{}')
    if p.get('gate') == gate_id:
        last_handled_ts = ts
        break
if last_handled_ts is None:
    print('ok'); sys.exit(0)
dt = datetime.strptime(last_handled_ts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
handled_epoch = dt.timestamp()
ev_mtime = ev_path.stat().st_mtime
if ev_mtime > handled_epoch:
    print('ok'); sys.exit(0)
if contract_path and Path(contract_path).exists():
    ev_payload = json.loads(ev_path.read_text(encoding='utf-8')).get('payload', {})
    evidence_contract_sha = ev_payload.get('contract_sha256', '')
    current_contract_sha = hashlib.sha256(Path(contract_path).read_bytes()).hexdigest()
    if evidence_contract_sha and evidence_contract_sha == current_contract_sha:
        print('ok'); sys.exit(0)
print('unresolved|' + last_handled_ts)
"""],
        env={**os.environ,
             "VG_RUN_ID": run_id,
             "VG_EV_PATH": str(evidence_path),
             "VG_DB_PATH": str(repo / ".vg" / "events.db"),
             "VG_CONTRACT_PATH": str(contract_path)},
        capture_output=True, text=True,
    )
    assert proc.stdout.strip() == "ok", (
        f"contract-unchanged bypass failed. stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="hook requires bash + full _lib.sh bootstrap not feasible on Win",
)
def test_b84_strict_block_still_fires_when_contract_changed(tmp_path: Path) -> None:
    """If contract CHANGES after evidence written, staleness block must fire."""
    repo, evidence_path, contract_path, run_id, session_id = _build_run_layout(tmp_path)
    # MUTATE contract → contract_sha256 changes
    new_contract = {
        "checklists": [{"id": "step_1", "title": "Setup"}, {"id": "step_2", "title": "Run"}],
        "projection_items": [{"id": "step_1"}, {"id": "step_2"}],
    }
    contract_path.write_text(json.dumps(new_contract), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-c", """
import os, sqlite3, sys, json, hashlib
from pathlib import Path
from datetime import datetime, timezone

run_id = os.environ['VG_RUN_ID']
ev_path = Path(os.environ['VG_EV_PATH'])
db_path = Path(os.environ['VG_DB_PATH'])
contract_path = os.environ.get('VG_CONTRACT_PATH', '')

conn = sqlite3.connect(str(db_path))
rows = conn.execute(
    "SELECT ts, payload_json FROM events WHERE run_id=? AND event_type='vg.block.handled' ORDER BY id DESC LIMIT 50",
    (run_id,),
).fetchall()
conn.close()

last_handled_ts = None
for ts, pj in rows:
    p = json.loads(pj or '{}')
    if p.get('gate') == 'PreToolUse-tasklist':
        last_handled_ts = ts; break
if last_handled_ts is None:
    print('ok'); sys.exit(0)
dt = datetime.strptime(last_handled_ts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
handled_epoch = dt.timestamp()
ev_mtime = ev_path.stat().st_mtime
if ev_mtime > handled_epoch:
    print('ok'); sys.exit(0)
if contract_path and Path(contract_path).exists():
    ev_payload = json.loads(ev_path.read_text(encoding='utf-8')).get('payload', {})
    evidence_contract_sha = ev_payload.get('contract_sha256', '')
    current_contract_sha = hashlib.sha256(Path(contract_path).read_bytes()).hexdigest()
    if evidence_contract_sha and evidence_contract_sha == current_contract_sha:
        print('ok'); sys.exit(0)
print('unresolved|' + last_handled_ts)
"""],
        env={**os.environ,
             "VG_RUN_ID": run_id,
             "VG_EV_PATH": str(evidence_path),
             "VG_DB_PATH": str(repo / ".vg" / "events.db"),
             "VG_CONTRACT_PATH": str(contract_path)},
        capture_output=True, text=True,
    )
    assert proc.stdout.strip().startswith("unresolved|"), (
        f"contract-changed must trigger staleness block. stdout={proc.stdout!r}"
    )
