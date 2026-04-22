"""
Negative test suite — 10 bypass scenarios that MUST block.

Each test sets up a bypass attempt from the v2.2 audit and asserts
vg-orchestrator correctly rejects it. Failure here = someone weakened
enforcement + regression catchable in CI.

Run: pytest .claude/scripts/tests/test_bypass_negative.py -v
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from conftest import assert_expected_block, assert_nonzero


ORCH = Path(__file__).resolve().parents[1] / "vg-orchestrator"
PYTHON = sys.executable


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Isolated repo with .vg + .claude structure for each test."""
    # Copy minimal structure
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".vg" / "phases" / "99-test-phase").mkdir(parents=True)
    (repo / ".claude" / "commands" / "vg").mkdir(parents=True)

    # Copy orchestrator + schemas
    src_root = Path(__file__).resolve().parents[2]
    for sub in ("scripts/vg-orchestrator", "scripts/validators", "schemas"):
        dst = repo / ".claude" / sub
        shutil.copytree(src_root / sub, dst, dirs_exist_ok=True)

    # Minimal skill-MD with runtime_contract for test command
    skill = repo / ".claude" / "commands" / "vg" / "scope.md"
    skill.write_text(textwrap.dedent("""\
        ---
        name: vg:scope
        runtime_contract:
          must_write:
            - "${PHASE_DIR}/CONTEXT.md"
            - "${PHASE_DIR}/DISCUSSION-LOG.md"
          must_touch_markers:
            - "0_parse_and_validate"
            - "1_deep_discussion"
            - "2_artifact_generation"
          must_emit_telemetry:
            - event_type: "scope.completed"
              phase: "${PHASE_NUMBER}"
          forbidden_without_override:
            - "--skip-crossai"
        ---

        # Test scope skill
        """), encoding="utf-8")

    # Minimal SPECS for phase-exists validator
    (repo / ".vg" / "phases" / "99-test-phase" / "SPECS.md").write_text(
        "# SPECS\n\nTest phase " + ("x" * 120), encoding="utf-8"
    )

    monkeypatch.setenv("VG_REPO_ROOT", str(repo))
    monkeypatch.chdir(repo)
    return repo


def orch(sandbox, *args, stdin_str: str | None = None):
    """Run orchestrator subcommand in sandbox."""
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(sandbox)
    r = subprocess.run(
        [PYTHON, str(ORCH), *args],
        cwd=str(sandbox),
        capture_output=True, text=True, env=env, timeout=30,
        input=stdin_str,
    )
    return r


def start_scope(sandbox):
    """Helper — register a vg:scope run for phase 99."""
    r = orch(sandbox, "run-start", "vg:scope", "99")
    assert r.returncode == 0, f"run-start failed: {r.stderr}"
    return r.stdout.strip()


# ─────────────────────── BYPASS SCENARIOS ───────────────────────

def test_bypass_1_fake_artifacts_and_markers(sandbox):
    """BV-2/3: echo TODO > artifact + touch marker without real work.
    Expect: BLOCK on content_min_bytes + missing scope.completed event."""
    start_scope(sandbox)
    phase_dir = sandbox / ".vg" / "phases" / "99-test-phase"
    (phase_dir / "CONTEXT.md").write_text("TODO", encoding="utf-8")
    (phase_dir / "DISCUSSION-LOG.md").write_text("", encoding="utf-8")
    # Attacker touches markers without calling mark-step
    for m in ("0_parse_and_validate", "1_deep_discussion",
              "2_artifact_generation"):
        (phase_dir / ".step-markers" / m).parent.mkdir(
            parents=True, exist_ok=True)
        (phase_dir / ".step-markers" / f"{m}.done").touch()

    r = orch(sandbox, "run-complete")
    assert_expected_block(r, "BV-2/3: fake artifacts + touched markers bypass")
    assert "must_emit_telemetry" in r.stderr or "scope.completed" in r.stderr


def test_bypass_2_forged_telemetry_jsonl(sandbox):
    """BV-4: echo fake event JSON to telemetry.jsonl (legacy path).
    Expect: v2.2 reads events.db (hash-chained), ignores jsonl forgery."""
    start_scope(sandbox)
    # Forge event in legacy telemetry.jsonl
    (sandbox / ".vg" / "telemetry.jsonl").write_text(
        json.dumps({
            "event_type": "scope.completed",
            "phase": "99",
            "command": "vg:scope",
            "outcome": "PASS",
        }) + "\n",
        encoding="utf-8",
    )
    # Still missing markers + real events → BLOCK
    r = orch(sandbox, "run-complete")
    assert_expected_block(r, "BV-4: forged telemetry.jsonl must not bypass events.db hash chain")


def test_bypass_3_concurrent_run_start(sandbox):
    """Attacker starts 2nd run while first active.
    Expect: 2nd run-start rejected."""
    start_scope(sandbox)
    r = orch(sandbox, "run-start", "vg:blueprint", "99")
    assert_nonzero(r, "BV: concurrent run-start must be rejected while another run is active")
    assert "Active run exists" in r.stderr


def test_bypass_4_empty_context_md(sandbox):
    """CONTEXT.md exists but has no decisions.
    Expect: context-structure validator BLOCK."""
    start_scope(sandbox)
    phase_dir = sandbox / ".vg" / "phases" / "99-test-phase"
    (phase_dir / "CONTEXT.md").write_text("x" * 600, encoding="utf-8")
    (phase_dir / "DISCUSSION-LOG.md").write_text("x" * 100, encoding="utf-8")

    # Mark steps + emit completed properly to isolate context-structure check
    for m in ("0_parse_and_validate", "1_deep_discussion",
              "2_artifact_generation"):
        orch(sandbox, "mark-step", "scope", m)
    orch(sandbox, "emit-event", "scope.completed")

    r = orch(sandbox, "run-complete")
    assert_expected_block(r, "BV-4: empty CONTEXT.md (no decisions) must block context-structure validator")
    assert "context-structure" in r.stderr or "decision" in r.stderr.lower()


def test_bypass_5_missing_completion_event(sandbox):
    """All artifacts + markers exist but scope.completed never emitted.
    Expect: must_emit_telemetry BLOCK."""
    start_scope(sandbox)
    phase_dir = sandbox / ".vg" / "phases" / "99-test-phase"
    (phase_dir / "CONTEXT.md").write_text(
        "# CONTEXT\n\n### P99.D-01: Test\n\n**Endpoints:** /api/test\n\n"
        "**Test Scenarios:** TS-01\n", encoding="utf-8"
    )
    (phase_dir / "DISCUSSION-LOG.md").write_text("log", encoding="utf-8")
    for m in ("0_parse_and_validate", "1_deep_discussion",
              "2_artifact_generation"):
        orch(sandbox, "mark-step", "scope", m)
    # deliberately skip scope.completed emit

    r = orch(sandbox, "run-complete")
    assert_expected_block(r, "BV-5: missing scope.completed event must block must_emit_telemetry")
    assert "scope.completed" in r.stderr


def test_bypass_6_forbidden_flag_without_override(sandbox):
    """Run uses --skip-crossai but no override.used event.
    Expect: forbidden_without_override BLOCK."""
    r = orch(sandbox, "run-start", "vg:scope", "99", "--skip-crossai")
    assert r.returncode == 0
    phase_dir = sandbox / ".vg" / "phases" / "99-test-phase"
    (phase_dir / "CONTEXT.md").write_text(
        "# CONTEXT\n\n### P99.D-01: Test\n\n**Endpoints:** /api/test\n\n"
        "**Test Scenarios:** TS-01\n", encoding="utf-8"
    )
    (phase_dir / "DISCUSSION-LOG.md").write_text("log", encoding="utf-8")
    for m in ("0_parse_and_validate", "1_deep_discussion",
              "2_artifact_generation"):
        orch(sandbox, "mark-step", "scope", m)
    orch(sandbox, "emit-event", "scope.completed")

    r = orch(sandbox, "run-complete")
    assert_expected_block(r, "BV-6: --skip-crossai without override.used event must block forbidden_without_override")
    assert "forbidden_without_override" in r.stderr or \
           "--skip-crossai" in r.stderr


def test_bypass_7_missing_phase_dir(sandbox):
    """run-start for phase that doesn't exist.
    Expect: phase-exists validator BLOCK at run-complete."""
    r = orch(sandbox, "run-start", "vg:scope", "99999")
    assert r.returncode == 0  # start itself succeeds
    r = orch(sandbox, "run-complete")
    assert_expected_block(r, "BV-7: non-existent phase dir must block phase-exists validator")


def test_bypass_8_hash_chain_tamper(sandbox):
    """Manually edit events table row → hash chain verify catches it.
    Expect: verify-hash-chain rc=2."""
    start_scope(sandbox)
    orch(sandbox, "emit-event", "scope.started")
    # Tamper: modify payload of an existing event
    db = sandbox / ".vg" / "events.db"
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE events SET payload_json = ? WHERE id = 1",
                 ('{"tampered": true}',))
    conn.commit()
    conn.close()

    r = orch(sandbox, "verify-hash-chain")
    assert_expected_block(r, "BV-8: tampered events row must be caught by hash-chain verify")
    assert "BROKEN" in r.stderr or "BROKEN" in r.stdout


def test_bypass_9_fake_current_run_json(sandbox):
    """Attacker writes fake current-run.json without orchestrator.
    Expect: run-complete catches because runs table has no matching row."""
    # No run-start — fake file directly
    fake = {
        "run_id": "deadbeef-fake-0000-0000-000000000000",
        "command": "vg:scope",
        "phase": "99",
        "args": "",
        "started_at": "2026-04-21T00:00:00Z",
    }
    (sandbox / ".vg" / "current-run.json").write_text(
        json.dumps(fake), encoding="utf-8"
    )

    r = orch(sandbox, "run-complete")
    # Either rc=1 (no run row) or rc=2 (contract check on fake run)
    # The point: CAN'T succeed with PASS
    assert_nonzero(r, "BV-9: fake current-run.json without run-start must not PASS")


def test_bypass_10_events_db_deleted_midrun(sandbox):
    """Delete events.db while run active. Expect: run-complete detects.
    This is a degraded-correct scenario: AI destroying evidence =
    fresh run, but orchestrator refuses to allow complete-without-events."""
    start_scope(sandbox)
    orch(sandbox, "emit-event", "scope.round_1_done")
    (sandbox / ".vg" / "events.db").unlink()
    # WAL files too
    for f in sandbox.glob(".vg/events.db-*"):
        f.unlink()

    r = orch(sandbox, "run-complete")
    # Without events.db, run-complete either rebuilds empty (no run_id match
    # → some error) OR runs validators and they BLOCK on missing events
    assert_nonzero(r, "BV-10: events.db deleted midrun must not PASS run-complete")
