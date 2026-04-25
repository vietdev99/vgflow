"""
SQLite event store with hash chain + WAL + flock single-writer serialization.

Primitives:
- connect(): opens DB with WAL, busy_timeout, hash-chain PRAGMA
- append_event(): atomic insert with hash chain — only path to write events
- query_events(): read-only projection
- verify_hash_chain(): walk events table, recompute + assert each hash

Design:
- Plaintext .vg/events.jsonl is a READ-ONLY projection written after each
  append. Authoritative source is .vg/events.db. Projection exists for human
  readability + grep compat; never trusted for decisions.
- Hash chain = sha256(prev_hash + event_type + phase + command + payload_json + ts).
  Edit any row → hash mismatches subsequent rows → detected at next query.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1
LOCK_STALE_SECONDS = 30

from _repo_root import find_repo_root  # noqa: E402

REPO_ROOT = find_repo_root(__file__)
DB_PATH = REPO_ROOT / ".vg" / "events.db"
LOCK_PATH = REPO_ROOT / ".vg" / ".events.lock"
PROJECTION_PATH = REPO_ROOT / ".vg" / "events.jsonl"

ZERO_HASH = "0" * 64


class IntegrityError(Exception):
    """Raised when hash chain verification fails."""


@contextlib.contextmanager
def _flock() -> Iterator[None]:
    """Cross-platform advisory lock via lockfile. Stale locks (>30s) auto-broken."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    while True:
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            # Check staleness
            try:
                age = time.time() - LOCK_PATH.stat().st_mtime
                if age > LOCK_STALE_SECONDS:
                    try:
                        LOCK_PATH.unlink()
                    except FileNotFoundError:
                        pass
                    continue
            except FileNotFoundError:
                continue
            if time.time() - start > 10:
                raise TimeoutError(f"flock held >10s on {LOCK_PATH}")
            time.sleep(0.05)

    try:
        yield
    finally:
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        command TEXT NOT NULL,
        phase TEXT NOT NULL,
        args TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        outcome TEXT,
        session_id TEXT,
        git_sha TEXT
    );

    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        ts TEXT NOT NULL,
        event_type TEXT NOT NULL,
        phase TEXT NOT NULL,
        command TEXT NOT NULL,
        step TEXT,
        actor TEXT NOT NULL,
        outcome TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        this_hash TEXT NOT NULL UNIQUE,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );

    CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
    CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
    CREATE INDEX IF NOT EXISTS idx_events_phase ON events(phase);
    CREATE INDEX IF NOT EXISTS idx_events_command ON events(command);
    """)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def connect() -> sqlite3.Connection:
    """Open DB with WAL + busy timeout. Safe for concurrent readers."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    _init_schema(conn)
    return conn


def _compute_hash(prev_hash: str, ts: str, event_type: str, phase: str,
                  command: str, payload_json: str) -> str:
    blob = f"{prev_hash}|{ts}|{event_type}|{phase}|{command}|{payload_json}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _latest_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT this_hash FROM events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["this_hash"] if row else ZERO_HASH


def create_run(command: str, phase: str, args: str = "",
               session_id: str | None = None, git_sha: str | None = None) -> str:
    """Write runs table row. Returns run_id."""
    run_id = str(uuid.uuid4())
    ts = _utc_now()
    with _flock():
        conn = connect()
        try:
            conn.execute(
                "INSERT INTO runs(run_id, command, phase, args, started_at, "
                "session_id, git_sha) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, command, phase, args, ts, session_id, git_sha),
            )
            conn.commit()
        finally:
            conn.close()
    return run_id


def complete_run(run_id: str, outcome: str = "PASS") -> None:
    ts = _utc_now()
    with _flock():
        conn = connect()
        try:
            conn.execute(
                "UPDATE runs SET completed_at = ?, outcome = ? WHERE run_id = ?",
                (ts, outcome, run_id),
            )
            conn.commit()
        finally:
            conn.close()


def get_run(run_id: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_active_run() -> dict | None:
    """Find the most recent run with completed_at IS NULL."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE completed_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# OHOK v2 Day 6 — per-event schema version for forward-compat migrations.
# Bump when payload shape changes in a backward-incompatible way. Readers
# (validators, reflector, reconciliation) check _schema and can reject
# unknown versions to fail-closed instead of silently misinterpreting.
EVENT_SCHEMA_VERSION = 1


def append_event(run_id: str, event_type: str, phase: str, command: str,
                 actor: str = "orchestrator", outcome: str = "INFO",
                 step: str | None = None, payload: dict | None = None) -> dict:
    """Atomic event insert with hash chain. Returns the inserted event row."""
    ts = _utc_now()
    # Inject schema version into every event payload (non-destructive — caller
    # payloads don't need to know about it). Readers can do
    # `json.loads(e.payload_json).get("_schema", 0)` to detect version.
    merged_payload = dict(payload or {})
    merged_payload.setdefault("_schema", EVENT_SCHEMA_VERSION)
    payload_json = json.dumps(merged_payload, sort_keys=True,
                              separators=(",", ":"))

    with _flock():
        conn = connect()
        try:
            prev_hash = _latest_hash(conn)
            this_hash = _compute_hash(
                prev_hash, ts, event_type, phase, command, payload_json,
            )
            conn.execute(
                "INSERT INTO events(run_id, ts, event_type, phase, command, "
                "step, actor, outcome, payload_json, prev_hash, this_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, ts, event_type, phase, command, step, actor,
                 outcome, payload_json, prev_hash, this_hash),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM events WHERE this_hash = ?", (this_hash,)
            ).fetchone()
            event_dict = dict(row)
        finally:
            conn.close()

    _append_projection(event_dict)
    return event_dict


def query_events(run_id: str | None = None, event_type: str | None = None,
                 phase: str | None = None, command: str | None = None,
                 since: str | None = None, limit: int = 1000) -> list[dict]:
    conn = connect()
    try:
        sql = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if run_id:
            sql += " AND run_id = ?"
            params.append(run_id)
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        if phase:
            sql += " AND phase = ?"
            params.append(phase)
        if command:
            sql += " AND command = ?"
            params.append(command)
        if since:
            sql += " AND ts >= ?"
            params.append(since)
        sql += " ORDER BY id ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def verify_hash_chain(since_id: int = 0) -> tuple[bool, int | None, str | None]:
    """
    Walk events table recomputing hashes. Returns (ok, broken_at_id, reason).
    On ok=True, broken_at_id and reason are None.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, ts, event_type, phase, command, payload_json, "
            "prev_hash, this_hash FROM events WHERE id > ? ORDER BY id ASC",
            (since_id,),
        ).fetchall()
        expected_prev = ZERO_HASH if since_id == 0 else _hash_at(conn, since_id)
        for r in rows:
            if r["prev_hash"] != expected_prev:
                return False, r["id"], (
                    f"prev_hash mismatch at id={r['id']}: "
                    f"expected {expected_prev[:12]}…, got {r['prev_hash'][:12]}…"
                )
            computed = _compute_hash(
                r["prev_hash"], r["ts"], r["event_type"], r["phase"],
                r["command"], r["payload_json"],
            )
            if computed != r["this_hash"]:
                return False, r["id"], (
                    f"this_hash mismatch at id={r['id']}: "
                    f"computed {computed[:12]}…, stored {r['this_hash'][:12]}…"
                )
            expected_prev = r["this_hash"]
        return True, None, None
    finally:
        conn.close()


def _hash_at(conn: sqlite3.Connection, event_id: int) -> str:
    row = conn.execute(
        "SELECT this_hash FROM events WHERE id = ?", (event_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"event id {event_id} not found")
    return row["this_hash"]


def _utc_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _append_projection(event: dict) -> None:
    """Write to .vg/events.jsonl as human-readable projection. NOT authoritative."""
    try:
        PROJECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PROJECTION_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "id": event["id"],
                "run_id": event["run_id"],
                "ts": event["ts"],
                "event_type": event["event_type"],
                "phase": event["phase"],
                "command": event["command"],
                "step": event["step"],
                "actor": event["actor"],
                "outcome": event["outcome"],
                "payload": json.loads(event["payload_json"]),
                "this_hash": event["this_hash"][:16],
            }) + "\n")
    except Exception:
        # Projection failure never blocks — .vg/events.db is source of truth
        pass
