"""
Tests for verify-allow-flag-audit.py + allow_flag_gate.py — Phase O of v2.5.2.

Covers:
  - Empty DB → ok=True
  - Missing DB path → ok=True (note)
  - Rubber-stamp pattern: (approver, flag, reason_fp) x3 → detected
  - Approval fatigue: single approver 5+ distinct flags → detected
  - Repeat flag: single flag used 10+ times → detected
  - Distinct approvers on same flag → NOT rubber-stamp
  - Lookback window excludes old events
  - allow_flag_gate.check_rubber_stamp sanity
  - allow_flag_gate.verify_human_operator: TTY / env-var / blocked paths
  - allow_flag_gate.log_allow_flag_used returns audit_id even without db
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-allow-flag-audit.py"
ORCH_DIR = REPO_ROOT_REAL / ".claude" / "scripts" / "vg-orchestrator"


def _mk_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript("""
    CREATE TABLE events (
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
    conn.commit()
    conn.close()


_INSERT_COUNTER = [0]


def _insert(path: Path, ts: str, payload: dict) -> None:
    conn = sqlite3.connect(str(path))
    # hash fields don't matter for validator; use unique sentinel per-insert
    _INSERT_COUNTER[0] += 1
    uniq = hashlib.sha256(
        (ts + json.dumps(payload, sort_keys=True) +
         str(_INSERT_COUNTER[0])).encode()
    ).hexdigest()
    conn.execute(
        "INSERT INTO events(run_id, ts, event_type, phase, command, "
        "actor, outcome, payload_json, prev_hash, this_hash) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("r", ts, "allow_flag.used", "7", "vg:build",
         "user", "INFO", json.dumps(payload),
         "0" * 64, uniq),
    )
    conn.commit()
    conn.close()


def _reason_fp(reason: str) -> str:
    head = " ".join(reason.strip().split())[:120].lower()
    return hashlib.sha256(head.encode()).hexdigest()[:16]


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30,
        cwd=str(cwd), env=env, encoding="utf-8", errors="replace",
    )


class TestValidator:
    def test_missing_db_ok(self, tmp_path):
        r = _run(["--db-path", str(tmp_path / "missing.db"), "--json"],
                 tmp_path)
        assert r.returncode == 0
        out = json.loads(r.stdout)
        assert out["ok"] is True

    def test_empty_db_ok(self, tmp_path):
        db = tmp_path / "events.db"
        _mk_db(db)
        r = _run(["--db-path", str(db), "--json"], tmp_path)
        assert r.returncode == 0
        out = json.loads(r.stdout)
        assert out["ok"] is True
        assert out["event_count"] == 0

    def test_rubber_stamp_detected(self, tmp_path):
        db = tmp_path / "events.db"
        _mk_db(db)
        reason = "Need to ship before EOD, not enough time to investigate"
        fp = _reason_fp(reason)
        for _ in range(3):
            _insert(db, "2026-04-20T12:00:00Z", {
                "flag": "--skip-coverage",
                "approver": "alice",
                "reason": reason,
                "reason_fp": fp,
            })
        r = _run(["--db-path", str(db), "--lookback-days", "30",
                  "--rubber-stamp-threshold", "3", "--json"], tmp_path)
        assert r.returncode == 1
        out = json.loads(r.stdout)
        assert len(out["rubber_stamps"]) >= 1
        assert out["rubber_stamps"][0]["approver"] == "alice"
        assert out["rubber_stamps"][0]["flag"] == "--skip-coverage"

    def test_distinct_approvers_not_rubber_stamp(self, tmp_path):
        db = tmp_path / "events.db"
        _mk_db(db)
        reason = "CI blocker, see JIRA-123"
        fp = _reason_fp(reason)
        for approver in ["alice", "bob", "carol"]:
            _insert(db, "2026-04-20T12:00:00Z", {
                "flag": "--skip-x", "approver": approver,
                "reason": reason, "reason_fp": fp,
            })
        r = _run(["--db-path", str(db), "--rubber-stamp-threshold", "3",
                  "--json"], tmp_path)
        out = json.loads(r.stdout)
        assert len(out["rubber_stamps"]) == 0

    def test_approval_fatigue_detected(self, tmp_path):
        db = tmp_path / "events.db"
        _mk_db(db)
        for i in range(5):
            _insert(db, "2026-04-20T12:00:00Z", {
                "flag": f"--skip-{i}",
                "approver": "overworked-pm",
                "reason": f"ticket-{i}",
                "reason_fp": _reason_fp(f"ticket-{i}"),
            })
        r = _run(["--db-path", str(db), "--fatigue-threshold", "5",
                  "--json"], tmp_path)
        assert r.returncode == 1
        out = json.loads(r.stdout)
        assert len(out["approval_fatigue"]) == 1
        assert out["approval_fatigue"][0]["approver"] == "overworked-pm"
        assert out["approval_fatigue"][0]["distinct_flag_count"] == 5

    def test_repeat_flag_detected(self, tmp_path):
        db = tmp_path / "events.db"
        _mk_db(db)
        for i in range(12):
            _insert(db, "2026-04-20T12:00:00Z", {
                "flag": "--skip-coverage",
                "approver": f"user-{i}",
                "reason": f"unique-{i}",
                "reason_fp": _reason_fp(f"unique-{i}"),
            })
        r = _run(["--db-path", str(db),
                  "--repeat-flag-threshold", "10",
                  "--fatigue-threshold", "50",  # avoid fatigue trigger
                  "--rubber-stamp-threshold", "50",
                  "--json"], tmp_path)
        assert r.returncode == 1
        out = json.loads(r.stdout)
        assert len(out["repeat_flags"]) == 1
        assert out["repeat_flags"][0]["flag"] == "--skip-coverage"

    def test_lookback_excludes_old(self, tmp_path):
        db = tmp_path / "events.db"
        _mk_db(db)
        reason = "old event"
        # Ancient event before the lookback window
        _insert(db, "2020-01-01T00:00:00Z", {
            "flag": "--skip-z", "approver": "old-alice",
            "reason": reason, "reason_fp": _reason_fp(reason),
        })
        r = _run(["--db-path", str(db), "--lookback-days", "1",
                  "--json"], tmp_path)
        assert r.returncode == 0
        out = json.loads(r.stdout)
        assert out["event_count"] == 0


# ─── allow_flag_gate.py ────────────────────────────────────────────

@pytest.fixture
def gate_mod():
    sys.path.insert(0, str(ORCH_DIR))
    if "allow_flag_gate" in sys.modules:
        del sys.modules["allow_flag_gate"]
    import allow_flag_gate
    return allow_flag_gate


class TestAllowFlagGate:
    def test_verify_human_env_override(self, gate_mod, monkeypatch):
        # v2.5.2.1: raw-string env in non-strict mode now appends
        # [unsigned-warning] suffix to surface that this is legacy
        # compat, not a cryptographically verified approval.
        monkeypatch.setenv("VG_HUMAN_OPERATOR", "alice@co")
        monkeypatch.delenv("VG_ALLOW_FLAGS_STRICT_MODE", raising=False)
        is_human, approver = gate_mod.verify_human_operator("--skip-x")
        assert is_human is True
        assert approver is not None
        assert "alice@co" in approver
        assert "unsigned-warning" in approver

    def test_verify_human_blocked_no_tty_no_env(self, gate_mod, monkeypatch):
        # Test harness is already non-TTY; clear env
        monkeypatch.delenv("VG_HUMAN_OPERATOR", raising=False)
        # Clear any fallback env
        is_human, approver = gate_mod.verify_human_operator("--skip-x")
        assert is_human is False
        assert approver is None

    def test_check_rubber_stamp_hit(self, gate_mod):
        reason = "see JIRA-456 for root cause"
        fp = gate_mod._reason_fingerprint(reason)
        events = [
            {"event_type": "allow_flag.used",
             "payload": {"flag": "--skip-x", "approver": "u1",
                         "reason_fp": fp}},
            {"event_type": "allow_flag.used",
             "payload": {"flag": "--skip-x", "approver": "u1",
                         "reason_fp": fp}},
            {"event_type": "allow_flag.used",
             "payload": {"flag": "--skip-x", "approver": "u1",
                         "reason_fp": fp}},
        ]
        assert gate_mod.check_rubber_stamp(events, "u1", "--skip-x",
                                           reason, threshold=3) is True

    def test_check_rubber_stamp_miss_under_threshold(self, gate_mod):
        reason = "see JIRA-789"
        fp = gate_mod._reason_fingerprint(reason)
        events = [
            {"event_type": "allow_flag.used",
             "payload": {"flag": "--skip-x", "approver": "u1",
                         "reason_fp": fp}},
        ]
        assert gate_mod.check_rubber_stamp(events, "u1", "--skip-x",
                                           reason, threshold=3) is False

    def test_log_allow_flag_returns_audit_id(self, gate_mod):
        # db module not accessible in isolated test — expect fallback AF-<fp>
        audit = gate_mod.log_allow_flag_used(
            "--skip-z", "alice", "JIRA-101 legit",
            run_id="run-x", phase="7", command="vg:test",
        )
        assert audit.startswith("AF-")
