"""Stage 5 task 4/6 of meta-memory v1.1 — Phase 3 Consolidate.

Locks the Anthropic Auto Dream in-place merge invariants (design Section 13.1):

  * MERGE not side-by-side: no CONSOLIDATION-{date}.md file is created;
    overlay.yml + ACCEPTED.md are updated in place; CONSOLIDATION-LOG.md
    is the single append-only audit trail.
  * Default mode = dry-run: no --apply -> nothing on disk changes.
  * NEVER auto-retract: a contradiction signal surfaces as a log warning
    only; rules/{slug}.md content is NOT modified.
  * Idempotent: re-running the same phase doesn't double-promote a rule.
  * Absolute timestamps only (UTC ISO 8601).

Phase 3 chains off Phase 2 internally — driving it via the CLI runs gather
+ consolidate with the same events.db.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

CONSOLIDATE = ".claude/scripts/bootstrap-consolidate.py"


def _make_events_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
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
            this_hash TEXT NOT NULL UNIQUE
        );
        """)
        conn.execute(
            "INSERT INTO runs(run_id, command, phase, started_at) "
            "VALUES (?, ?, ?, ?)",
            ("fake-run", "test", "test", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_event(db_path: Path, *, outcome: str, payload: dict) -> None:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    fake_hash = hashlib.sha256(
        (str(uuid.uuid4()) + payload_json).encode()).hexdigest()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO events(run_id, ts, event_type, phase, command, step, "
            "actor, outcome, payload_json, prev_hash, this_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fake-run", ts, "bootstrap.outcome_recorded", "test", "test",
             None, "test", outcome, payload_json, "0" * 64, fake_hash),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_proc_passes(db: Path, slug: str, count: int) -> None:
    payload = {
        "slug": slug,
        "rule_type": "procedural",
        "attribution": {"executed_step_ids": ["s1", "s2"],
                        "total_steps": 2,
                        "matched_signals_count": 2},
    }
    for _ in range(count):
        _insert_event(db, outcome="PASS", payload=payload)


def _run_consolidate(state_dir: Path, db: Path | None = None,
                     apply: bool = False) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_BOOTSTRAP_STATE_DIR"] = str(state_dir)
    if db is not None:
        env["VG_EVENTS_DB_PATH"] = str(db)
    argv = [sys.executable, CONSOLIDATE, "--phase", "consolidate", "--json"]
    if apply:
        argv.append("--apply")
    return subprocess.run(argv, capture_output=True, text=True, env=env)


# ---------- tests ----------

def test_consolidate_dry_run_writes_nothing(tmp_path):
    """Default mode (no --apply) -> filesystem unchanged."""
    db = tmp_path / "events.db"
    _make_events_db(db)
    _seed_proc_passes(db, "fast-rule", 5)

    # Snapshot existing files (should still be empty after run)
    files_before = sorted(p.name for p in tmp_path.iterdir())

    result = _run_consolidate(tmp_path, db, apply=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["apply"] is False
    assert report["promotions"] == ["fast-rule"]  # signal detected
    assert report["files_modified"] == []          # but nothing written

    files_after = sorted(p.name for p in tmp_path.iterdir())
    # Only the events.db should exist; no overlay.yml/ACCEPTED.md/log written.
    assert files_after == files_before
    assert not (tmp_path / "overlay.yml").exists()
    assert not (tmp_path / "ACCEPTED.md").exists()
    assert not (tmp_path / "CONSOLIDATION-LOG.md").exists()


def test_consolidate_recurrence_promotes_to_tier_a(tmp_path):
    """4 attributed PASS -> tier A promotion when --apply."""
    db = tmp_path / "events.db"
    _make_events_db(db)
    _seed_proc_passes(db, "deploy-fly", 4)

    result = _run_consolidate(tmp_path, db, apply=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["promotions"] == ["deploy-fly"]
    assert "overlay.yml" in report["files_modified"]
    assert "ACCEPTED.md" in report["files_modified"]
    assert "CONSOLIDATION-LOG.md" in report["files_modified"]

    overlay_text = (tmp_path / "overlay.yml").read_text(encoding="utf-8")
    assert "deploy-fly" in overlay_text
    assert "tier_a_count" in overlay_text
    assert "tier: A" in overlay_text or '"tier": "A"' in overlay_text

    accepted = (tmp_path / "ACCEPTED.md").read_text(encoding="utf-8")
    assert "deploy-fly" in accepted
    assert "tier A" in accepted

    log = (tmp_path / "CONSOLIDATION-LOG.md").read_text(encoding="utf-8")
    assert "deploy-fly" in log
    assert "Promotions" in log


def test_consolidate_contradiction_no_auto_retract(tmp_path):
    """3 PASS + 3 FAIL -> warn-only; rules/{slug}.md and ACCEPTED.md untouched."""
    db = tmp_path / "events.db"
    _make_events_db(db)

    # Pre-create a rule file we expect to be UNTOUCHED.
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    rule_file = rules_dir / "flaky-rule.md"
    original = "---\nslug: flaky-rule\ntype: procedural\n---\nbody\n"
    rule_file.write_text(original, encoding="utf-8")

    payload = {
        "slug": "flaky-rule",
        "rule_type": "procedural",
        "attribution": {"executed_step_ids": ["s1"],
                        "total_steps": 1,
                        "matched_signals_count": 1},
    }
    for _ in range(3):
        _insert_event(db, outcome="PASS", payload=payload)
    for _ in range(3):
        _insert_event(db, outcome="FAIL", payload=payload)

    result = _run_consolidate(tmp_path, db, apply=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["contradictions"] == ["flaky-rule"]
    assert report["promotions"] == []

    # Rule body MUST be byte-identical (no auto-retract).
    assert rule_file.read_text(encoding="utf-8") == original

    # ACCEPTED.md MUST NOT have a flaky-rule entry.
    accepted_path = tmp_path / "ACCEPTED.md"
    if accepted_path.exists():
        assert "flaky-rule" not in accepted_path.read_text(encoding="utf-8")

    # CONSOLIDATION-LOG.md MUST contain the warn-only contradiction line.
    log = (tmp_path / "CONSOLIDATION-LOG.md").read_text(encoding="utf-8")
    assert "flaky-rule" in log
    assert "Contradiction" in log
    assert "human review" in log.lower() or "no auto-retract" in log.lower()


def test_consolidate_idempotent_no_double_promote(tmp_path):
    """Running --apply twice -> overlay.tier_a_count incremented once only,
    ACCEPTED.md has the slug listed exactly once."""
    db = tmp_path / "events.db"
    _make_events_db(db)
    _seed_proc_passes(db, "stable-rule", 3)

    r1 = _run_consolidate(tmp_path, db, apply=True)
    assert r1.returncode == 0, r1.stderr
    r2 = _run_consolidate(tmp_path, db, apply=True)
    assert r2.returncode == 0, r2.stderr

    overlay_text = (tmp_path / "overlay.yml").read_text(encoding="utf-8")
    # Either YAML "tier_a_count: 1" or JSON "\"tier_a_count\": 1" — both valid
    # outputs from _dump_yaml_overlay. Just check it's NOT 2.
    assert "tier_a_count: 1" in overlay_text or '"tier_a_count": 1' in overlay_text, (
        f"tier_a_count should not double-increment on idempotent re-run; "
        f"overlay:\n{overlay_text}")

    accepted = (tmp_path / "ACCEPTED.md").read_text(encoding="utf-8")
    assert accepted.count("- stable-rule") == 1, (
        f"ACCEPTED.md should list stable-rule exactly once; got:\n{accepted}")


def test_consolidate_log_uses_absolute_timestamp(tmp_path):
    """CONSOLIDATION-LOG.md entries use UTC ISO 8601 (no "yesterday" etc)."""
    import re
    db = tmp_path / "events.db"
    _make_events_db(db)
    _seed_proc_passes(db, "ts-rule", 3)

    _run_consolidate(tmp_path, db, apply=True)
    log = (tmp_path / "CONSOLIDATION-LOG.md").read_text(encoding="utf-8")
    # Match "## 2026-05-08T12:34:56Z" style header
    assert re.search(r"## \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", log), (
        f"expected UTC ISO 8601 header in log; got:\n{log}")
    # Reject relative date words (design Section 13.1 validator concern)
    assert "yesterday" not in log.lower()
    assert "today" not in log.lower()


def test_consolidate_no_signals_writes_log_only(tmp_path):
    """Even with no actionable signals, --apply still writes a log entry
    (so absence-of-rerun is detectable). overlay.yml + ACCEPTED.md untouched."""
    db = tmp_path / "events.db"
    _make_events_db(db)
    # No events seeded -> no signals.

    result = _run_consolidate(tmp_path, db, apply=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["promotions"] == []
    assert report["contradictions"] == []
    assert "CONSOLIDATION-LOG.md" in report["files_modified"]

    log = (tmp_path / "CONSOLIDATION-LOG.md").read_text(encoding="utf-8")
    assert "no actionable signals" in log.lower()
    assert not (tmp_path / "overlay.yml").exists()
    assert not (tmp_path / "ACCEPTED.md").exists()
