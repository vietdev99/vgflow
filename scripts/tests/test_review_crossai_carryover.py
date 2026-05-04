"""
R7-A Task 1 — Tests for build CrossAI terminal carryover into /vg:review.

Closes G5 (codex audit 2026-05-05): build CrossAI defer path emits
`build.crossai_loop_exhausted` event + `findings-iter5.json` file. Review
preflight ignored both → silent leak. New validator
`verify-build-crossai-carryover.py` audits this carryover and the preflight
must wire to it.

Coverage (7 cases):

  Validator behaviour (5 verdict cases):
    - test_validator_passes_on_clean_terminal       (rc=0 PASS)
    - test_validator_blocks_on_exhausted_with_findings   (rc=1 BLOCK)
    - test_validator_warns_on_user_override         (rc=0 WARN)
    - test_validator_blocks_on_corrupted_state      (rc=1 BLOCK)
    - test_validator_passes_on_no_crossai_run       (rc=0 PASS)

  Wiring (2 frontmatter/preflight assertions):
    - test_review_md_frontmatter_has_override_flag
    - test_preflight_allowlist_has_override_flag

Validator emit_and_exit semantics (per scripts/validators/_common.py):
  - rc 0 → PASS or WARN
  - rc 1 → BLOCK
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-build-crossai-carryover.py"
REVIEW_MD = REPO_ROOT / "commands" / "vg" / "review.md"
PREFLIGHT_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "preflight.md"


# ─── Helpers ──────────────────────────────────────────────────────────


def _make_phase_dir(tmp_path: Path, phase_id: str = "9.99") -> Path:
    """Create a tmp phase dir matching `${PHASES_DIR}/${phase_id}-slug` shape."""
    phases_dir = tmp_path / ".vg" / "phases"
    phases_dir.mkdir(parents=True)
    phase_dir = phases_dir / f"{phase_id}-rfc-test"
    phase_dir.mkdir()
    return phase_dir


def _init_events_db(tmp_path: Path) -> Path:
    """Create a minimal events.db with the schema needed by the validator."""
    db_path = tmp_path / ".vg" / "events.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
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
        CREATE INDEX IF NOT EXISTS idx_events_phase ON events(phase);
        """)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _emit_event(
    db_path: Path,
    *,
    event_type: str,
    phase: str,
    payload: dict | None = None,
) -> None:
    """Insert one event row directly. Hash chain not validated by the
    carryover validator — we just need rows queryable by phase + type."""
    conn = sqlite3.connect(str(db_path))
    try:
        # Generate unique hashes for the UNIQUE constraint
        nonce = uuid.uuid4().hex
        this_hash = hashlib.sha256(f"{event_type}:{phase}:{nonce}".encode()).hexdigest()
        prev_hash = hashlib.sha256(f"prev:{nonce}".encode()).hexdigest()
        conn.execute(
            "INSERT INTO events "
            "(run_id, ts, event_type, phase, command, step, actor, outcome, "
            " payload_json, prev_hash, this_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "test-run-" + nonce[:8],
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                event_type,
                phase,
                "vg:build",
                None,
                "orchestrator",
                "INFO",
                json.dumps(payload or {}),
                prev_hash,
                this_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _write_findings(phase_dir: Path, findings: list[dict]) -> Path:
    findings_dir = phase_dir / "crossai-build-verify"
    findings_dir.mkdir(parents=True, exist_ok=True)
    findings_path = findings_dir / "findings-iter5.json"
    findings_path.write_text(json.dumps(findings), encoding="utf-8")
    return findings_path


def _run_validator(phase_dir: Path, repo_root: Path) -> subprocess.CompletedProcess:
    """Run the validator with VG_REPO_ROOT pointed at the tmp tree.

    The validator reads $VG_REPO_ROOT/.vg/events.db. We point it at tmp_path.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(repo_root)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase-dir", str(phase_dir)],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace",
    )


def _parse_output(proc: subprocess.CompletedProcess) -> dict:
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(line)


# ─── Validator behavioural tests (5 verdict cases) ────────────────────


def test_validator_passes_on_clean_terminal(tmp_path):
    """terminal=build.crossai_loop_complete → PASS (rc=0)."""
    phase_dir = _make_phase_dir(tmp_path, "9.99")
    db_path = _init_events_db(tmp_path)
    _emit_event(
        db_path,
        event_type="build.crossai_loop_complete",
        phase="9.99",
        payload={"iterations": 3},
    )

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["validator"] == "build-crossai-carryover"
    assert out["verdict"] in ("PASS", "WARN")


def test_validator_blocks_on_exhausted_with_findings(tmp_path):
    """terminal=exhausted + findings-iter5.json present → BLOCK (rc=1)."""
    phase_dir = _make_phase_dir(tmp_path, "9.99")
    db_path = _init_events_db(tmp_path)
    _emit_event(
        db_path,
        event_type="build.crossai_loop_exhausted",
        phase="9.99",
        payload={"iterations": 5, "reason": "user_deferred"},
    )
    _write_findings(phase_dir, [
        {"id": "F-001", "severity": "BLOCK", "title": "stack trace leak"},
        {"id": "F-002", "severity": "BLOCK", "title": "missing CSRF token"},
    ])

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "build_crossai_deferred_findings" in types, types


def test_validator_warns_on_user_override(tmp_path):
    """terminal=user_override + findings → WARN (rc=0)."""
    phase_dir = _make_phase_dir(tmp_path, "9.99")
    db_path = _init_events_db(tmp_path)
    _emit_event(
        db_path,
        event_type="build.crossai_loop_user_override",
        phase="9.99",
        payload={"reason": "ticket://VG-1234 emergency hotfix"},
    )
    _write_findings(phase_dir, [
        {"id": "F-099", "severity": "BLOCK", "title": "left over"},
    ])

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 0, (
        f"Expected WARN rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "WARN"
    types = {e.get("type") for e in out["evidence"]}
    assert "build_crossai_user_override_acknowledged" in types, types


def test_validator_blocks_on_corrupted_state(tmp_path):
    """No terminal event + findings file present → BLOCK (rc=1)."""
    phase_dir = _make_phase_dir(tmp_path, "9.99")
    _init_events_db(tmp_path)  # empty db, no events
    _write_findings(phase_dir, [
        {"id": "F-orphan", "severity": "BLOCK"},
    ])

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 1, (
        f"Expected BLOCK rc=1, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "BLOCK"
    types = {e.get("type") for e in out["evidence"]}
    assert "build_crossai_state_corrupted" in types, types


def test_validator_passes_on_no_crossai_run(tmp_path):
    """No terminal + no findings → PASS (CrossAI never ran or completed clean before validator wired)."""
    phase_dir = _make_phase_dir(tmp_path, "9.99")
    _init_events_db(tmp_path)  # empty db
    # No findings file written

    proc = _run_validator(phase_dir, tmp_path)
    assert proc.returncode == 0, (
        f"Expected PASS rc=0, got rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    out = _parse_output(proc)
    assert out["verdict"] == "PASS"


# ─── Frontmatter wiring tests (2 cases) ───────────────────────────────


def test_review_md_frontmatter_has_override_flag():
    """commands/vg/review.md `forbidden_without_override` list must include
    `--allow-build-crossai-deferred`."""
    text = REVIEW_MD.read_text(encoding="utf-8")
    # Locate the forbidden_without_override block
    assert "forbidden_without_override:" in text, (
        "review.md missing `forbidden_without_override:` block"
    )
    # The flag must appear in that block (as a YAML list entry).
    # Match both quoting styles for resilience.
    assert (
        '"--allow-build-crossai-deferred"' in text
        or "'--allow-build-crossai-deferred'" in text
        or "- --allow-build-crossai-deferred" in text
    ), (
        "review.md `forbidden_without_override` does not list "
        "`--allow-build-crossai-deferred`"
    )


def test_preflight_allowlist_has_override_flag():
    """commands/vg/_shared/review/preflight.md case-statement that parses
    flags must accept `--allow-build-crossai-deferred` (so it is not
    silently dropped before override-debt logging)."""
    text = PREFLIGHT_MD.read_text(encoding="utf-8")
    assert "--allow-build-crossai-deferred" in text, (
        "preflight.md does not mention `--allow-build-crossai-deferred` "
        "— flag will be silently dropped by case-statement allowlist"
    )
