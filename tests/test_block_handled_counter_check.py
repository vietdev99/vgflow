"""Task 44b — Rule V4 (block.handled counter-check).

Audit P1 (15+ PV3 bypass instances): AI emits ``vg.block.handled``
without performing TodoWrite + tasklist-projected, satisfying the
diagnostic textually but leaving evidence file unchanged. Next
``step-active`` blocks again — infinite loop.

This suite locks: when a ``vg.block.handled`` event for gate
``PreToolUse-tasklist`` exists for the current run, the next
``step-active`` invocation MUST verify that
``.tasklist-projected.evidence.json`` mtime is GREATER than the
``vg.block.handled`` event timestamp. If not (handled-without-refresh)
→ HARD BLOCK exit 1/2 (not exit 2 diagnostic loop).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_HOOK = str(REPO_ROOT / "scripts/hooks/vg-pre-tool-use-bash.sh")
EMIT_SIGNED = str(REPO_ROOT / "scripts/vg-orchestrator-emit-evidence-signed.py")


def _setup_run(tmp: Path, run_id: str) -> None:
    runs_dir = tmp / ".vg" / "runs" / run_id
    runs_dir.mkdir(parents=True)
    contract = {
        "schema": "native-tasklist.v2",
        "run_id": run_id,
        "command": "vg:test",
        "phase": "test-1.0",
        "checklists": [
            {"id": "g1", "title": "Group One", "items": ["s1"], "status": "pending"},
        ],
    }
    (runs_dir / "tasklist-contract.json").write_text(
        json.dumps(contract, sort_keys=True), encoding="utf-8"
    )

    active_dir = tmp / ".vg" / "active-runs"
    active_dir.mkdir(parents=True)
    (active_dir / "test-session.json").write_text(
        json.dumps({"run_id": run_id, "command": "vg:test", "phase": "test-1.0"}),
        encoding="utf-8",
    )


def _mk_key(tmp: Path) -> Path:
    key_path = tmp / ".vg" / ".evidence-key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(b"H" * 48)
    os.chmod(key_path, 0o600)
    return key_path


def _seed_signed_evidence(tmp: Path, run_id: str) -> Path:
    contract_path = tmp / ".vg" / "runs" / run_id / "tasklist-contract.json"
    sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    payload = {
        "run_id": run_id,
        "todowrite_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "todo_count": 1,
        "contract_sha256": sha,
        "todo_ids": ["g1"],
        "contract_ids": ["g1"],
        "match": True,
        "depth_valid": True,
        "groups_with_subs_count": 1,
        "flat_groups": [],
    }
    out = tmp / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
    subprocess.run(
        ["python3", EMIT_SIGNED, "--out", str(out), "--payload", json.dumps(payload)],
        env={
            **os.environ,
            "VG_EVIDENCE_KEY_PATH": str(tmp / ".vg" / ".evidence-key"),
        },
        check=True,
        capture_output=True,
    )
    return out


def _seed_events_db(tmp: Path, run_id: str, events: list[dict]) -> None:
    """Append rows directly to events.db. Each event: {event_type, ts, payload?}."""
    db_path = tmp / ".vg" / "events.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT '',
            command TEXT NOT NULL DEFAULT '',
            step TEXT,
            actor TEXT NOT NULL DEFAULT 'hook',
            outcome TEXT NOT NULL DEFAULT 'INFO',
            payload_json TEXT NOT NULL DEFAULT '{}',
            prev_hash TEXT NOT NULL DEFAULT '',
            this_hash TEXT NOT NULL UNIQUE
        )
    """)
    for i, ev in enumerate(events):
        conn.execute(
            "INSERT INTO events(run_id, ts, event_type, phase, command, payload_json, this_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                run_id,
                ev["ts"],
                ev["event_type"],
                "test-1.0",
                "vg:test",
                json.dumps(ev.get("payload") or {}),
                f"hash-{run_id}-{i}-{ev['ts']}",
            ),
        )
    conn.commit()
    conn.close()


def _run_pre_hook(tmp: Path, command: str, session_id: str = "test-session"):
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        ["bash", PRE_HOOK],
        input=payload,
        env={
            **os.environ,
            "CLAUDE_HOOK_SESSION_ID": session_id,
            "VG_REPO_ROOT": str(tmp),
            "VG_EVIDENCE_KEY_PATH": str(tmp / ".vg" / ".evidence-key"),
        },
        capture_output=True,
        text=True,
        cwd=str(tmp),
        timeout=15,
    )


def test_block_handled_without_evidence_refresh_blocks_next_step_active(
    tmp_path: Path,
) -> None:
    """vg.block.handled emitted AFTER evidence mtime → BLOCK on next step-active."""
    run_id = "run-handled-stale"
    _setup_run(tmp_path, run_id)
    _mk_key(tmp_path)

    # Seed evidence FIRST (older mtime).
    _seed_signed_evidence(tmp_path, run_id)
    ev_path = tmp_path / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
    # Force evidence mtime to a known earlier instant.
    old_ts = time.time() - 60
    os.utime(ev_path, (old_ts, old_ts))

    # Then emit vg.block.handled with timestamp NEWER than evidence mtime
    # (evidence has not been refreshed since the handled event).
    handled_ts_iso = datetime.fromtimestamp(
        old_ts + 30, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_events_db(tmp_path, run_id, [
        {
            "event_type": "vg.block.fired",
            "ts": datetime.fromtimestamp(old_ts + 10, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "payload": {"gate": "PreToolUse-tasklist", "cause": "test"},
        },
        {
            "event_type": "vg.block.handled",
            "ts": handled_ts_iso,
            "payload": {"gate": "PreToolUse-tasklist", "resolution": "noop"},
        },
    ])

    cmd = "python3 .claude/scripts/vg-orchestrator step-active s1"
    result = _run_pre_hook(tmp_path, cmd)
    assert result.returncode != 0, (
        f"expected BLOCK; got {result.returncode}\nstderr: {result.stderr}"
    )
    diag = result.stderr
    assert (
        "block.handled" in diag
        or "evidence not refreshed" in diag.lower()
        or "unresolved" in diag.lower()
    ), f"diagnostic must mention block.handled/evidence-not-refreshed; got:\n{diag}"


def test_block_handled_with_evidence_refresh_passes(tmp_path: Path) -> None:
    """vg.block.handled emitted, then evidence refreshed (mtime newer) → exit 0."""
    run_id = "run-handled-fresh"
    _setup_run(tmp_path, run_id)
    _mk_key(tmp_path)

    # Emit vg.block.fired + vg.block.handled at known time.
    base_ts = time.time() - 60
    handled_iso = datetime.fromtimestamp(
        base_ts + 30, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_events_db(tmp_path, run_id, [
        {
            "event_type": "vg.block.fired",
            "ts": datetime.fromtimestamp(base_ts + 10, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "payload": {"gate": "PreToolUse-tasklist", "cause": "test"},
        },
        {
            "event_type": "vg.block.handled",
            "ts": handled_iso,
            "payload": {"gate": "PreToolUse-tasklist", "resolution": "todowrite"},
        },
    ])

    # Then write evidence (mtime > handled).
    _seed_signed_evidence(tmp_path, run_id)
    ev_path = tmp_path / ".vg" / "runs" / run_id / ".tasklist-projected.evidence.json"
    fresh_mtime = base_ts + 60
    os.utime(ev_path, (fresh_mtime, fresh_mtime))

    cmd = "python3 .claude/scripts/vg-orchestrator step-active s1"
    result = _run_pre_hook(tmp_path, cmd)
    assert result.returncode == 0, (
        f"expected PASS exit 0; got {result.returncode}\nstderr: {result.stderr}"
    )
