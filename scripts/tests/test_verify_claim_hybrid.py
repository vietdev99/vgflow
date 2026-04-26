"""
test_verify_claim_hybrid.py — Tier C coverage for vg-verify-claim Stop hook
hybrid marker-drift auto-recovery (v2.8.3).

Pins:
1. Pure marker-drift first hit → BLOCK with hint, drift_count=1.
2. Pure marker-drift second hit → auto-fire migrate-state, retry,
   APPROVE on retry pass + emit hook.marker_drift_recovered telemetry.
3. Mixed violations (marker + telemetry) → never auto-fire, drift_count
   NOT bumped (so unrelated drift doesn't accumulate while real gaps
   remain).
4. Auto-fire migrate-state FAILURE → BLOCK with explicit failure message.
5. Auto-fire OK but retry still BLOCKs → fall through, no approve.
6. _parse_violation_types correctly extracts type tags from
   _format_block_message stderr format.
7. Drift-state file GC drops entries older than DRIFT_STATE_TTL_MINUTES.
8. No active run → approve, no drift bookkeeping.

Strategy: import vg-verify-claim as module under VG_REPO_ROOT pointing at
fake repo. Monkeypatch run_orchestrator_complete + _auto_fire_markers +
_emit_telemetry to control rc/stdout/stderr. Drive main() via stdin JSON.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = REPO_ROOT / ".claude" / "scripts" / "vg-verify-claim.py"


def _load_hook_module(repo_root: Path):
    """Load vg-verify-claim.py as 'vc' module, with REPO_ROOT pinned to
    `repo_root`. Module-level constants (CURRENT_RUN, SESSION_DRIFT, etc.)
    are evaluated at exec_module time, so VG_REPO_ROOT must be set first.
    """
    import os
    os.environ["VG_REPO_ROOT"] = str(repo_root)
    spec = importlib.util.spec_from_file_location("vc_test", HOOK_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _cleanup_vg_repo_root_env():
    """Restore VG_REPO_ROOT env var after each test to prevent pollution
    bleed into other test files. Harness fix 2026-04-26."""
    import os
    original = os.environ.get("VG_REPO_ROOT")
    yield
    if original is None:
        os.environ.pop("VG_REPO_ROOT", None)
    else:
        os.environ["VG_REPO_ROOT"] = original


def _setup_fake_repo(tmp_path: Path, *, current_run: dict | None = None) -> Path:
    """Create .vg/ with optional current-run.json, no orchestrator.
    Tests stub orchestrator/migrate-state via monkeypatch instead of real files.
    """
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir(parents=True)
    if current_run is not None:
        (vg_dir / "current-run.json").write_text(
            json.dumps(current_run), encoding="utf-8"
        )
    return tmp_path


def _drive_main(mod, capsys, stdin_payload: dict | None = None) -> tuple[int, str, str]:
    """Invoke mod.main() with controlled stdin. Returns (rc, stdout, stderr)."""
    payload = stdin_payload or {"session_id": "test-session"}
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        rc = mod.main()
    finally:
        sys.stdin = sys.__stdin__
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _fresh_started_at() -> str:
    """ISO timestamp 1 minute ago — within STALE_MINUTES window."""
    ts = datetime.utcnow() - timedelta(minutes=1)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_active_run_approves(tmp_path, capsys, monkeypatch):
    repo = _setup_fake_repo(tmp_path, current_run=None)
    mod = _load_hook_module(repo)
    rc, out, err = _drive_main(mod, capsys)
    assert rc == 0
    decision = json.loads(out.strip().splitlines()[-1])
    assert decision["decision"] == "approve"
    assert decision["reason"] == "no-active-run"


def test_orchestrator_pass_approves(tmp_path, capsys, monkeypatch):
    run = {
        "command": "vg:accept",
        "phase": "7.14.3",
        "run_id": "abcd1234ef",
        "started_at": _fresh_started_at(),
    }
    repo = _setup_fake_repo(tmp_path, current_run=run)
    mod = _load_hook_module(repo)
    monkeypatch.setattr(mod, "run_orchestrator_complete",
                        lambda: (0, "", ""))
    rc, out, err = _drive_main(mod, capsys)
    assert rc == 0
    decision = json.loads(out.strip().splitlines()[-1])
    assert decision["reason"] == "orchestrator-pass"


def test_marker_drift_first_blocks_with_hint(tmp_path, capsys, monkeypatch):
    """1st marker-drift: BLOCK, drift_count=1, hint visible."""
    run = {"command": "vg:accept", "phase": "7.14.3",
           "run_id": "run-aaaa-1111",
           "started_at": _fresh_started_at()}
    repo = _setup_fake_repo(tmp_path, current_run=run)
    mod = _load_hook_module(repo)

    stderr_block = (
        "⛔ VG runtime_contract violations — cannot complete run.\n"
        "\n"
        "Command: /vg:accept 7.14.3\n"
        "\n"
        "Missing evidence:\n"
        "  [must_touch_markers]\n"
        "    - 8_execute_waves\n"
        "    - 9_post_execution\n"
    )
    monkeypatch.setattr(mod, "run_orchestrator_complete",
                        lambda: (2, "", stderr_block))
    auto_fire_called = []
    monkeypatch.setattr(mod, "_auto_fire_markers",
                        lambda phase: (auto_fire_called.append(phase) or (0, "", "")))

    rc, out, err = _drive_main(mod, capsys)
    assert rc == 2
    assert auto_fire_called == [], "1st drift must NOT trigger auto-fire"
    assert "1st time" in err or "Current count: 1" in err
    # drift_count=1 in state
    state = json.loads((repo / ".vg" / ".session-drift.json").read_text())
    assert state["run-aaaa-1111"]["drift_count"] == 1
    assert state["run-aaaa-1111"]["violations_seen"] == ["must_touch_markers"]


def test_marker_drift_second_auto_recovers(tmp_path, capsys, monkeypatch):
    """2nd marker-drift: auto-fire fires, retry passes → APPROVE."""
    run = {"command": "vg:accept", "phase": "7.14.3",
           "run_id": "run-bbbb-2222",
           "started_at": _fresh_started_at()}
    repo = _setup_fake_repo(tmp_path, current_run=run)
    # Pre-seed drift_count=1 (simulating the 1st BLOCK earlier this session)
    drift_state = {
        "run-bbbb-2222": {
            "drift_count": 1,
            "first_drift_at": _fresh_started_at(),
            "last_drift_at": _fresh_started_at(),
            "violations_seen": ["must_touch_markers"],
        }
    }
    (repo / ".vg" / ".session-drift.json").write_text(
        json.dumps(drift_state), encoding="utf-8"
    )

    mod = _load_hook_module(repo)

    # First call: BLOCK marker-only. Second call (retry): PASS.
    call_count = {"n": 0}
    def fake_run():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (2, "", "Missing evidence:\n  [must_touch_markers]\n    - 8_execute_waves\n")
        return (0, "", "")
    monkeypatch.setattr(mod, "run_orchestrator_complete", fake_run)

    auto_fire_calls = []
    monkeypatch.setattr(mod, "_auto_fire_markers",
                        lambda phase: (auto_fire_calls.append(phase) or
                                       (0, "Backfilled 8 marker(s) in 7.14.3", "")))
    telemetry_calls = []
    monkeypatch.setattr(mod, "_emit_telemetry",
                        lambda evt, payload: telemetry_calls.append((evt, payload)))

    rc, out, err = _drive_main(mod, capsys)

    assert rc == 0, f"expected rc=0 (approved via auto-recovery), got {rc}, err={err}"
    assert auto_fire_calls == ["7.14.3"], "auto-fire must fire exactly once"
    assert call_count["n"] == 2, "orchestrator must be retried after auto-fire"
    assert any(evt == "hook.marker_drift_recovered" for evt, _ in telemetry_calls), \
        "telemetry event must be emitted on successful recovery"
    decision = json.loads(out.strip().splitlines()[-1])
    assert decision["decision"] == "approve"
    assert decision["reason"] == "auto-recovered-marker-drift"
    # drift_count bumped to 2 in state
    state = json.loads((repo / ".vg" / ".session-drift.json").read_text())
    assert state["run-bbbb-2222"]["drift_count"] == 2


def test_mixed_violations_never_auto_fires(tmp_path, capsys, monkeypatch):
    """Mixed marker+telemetry → block, never auto-fire, drift_count NOT bumped."""
    run = {"command": "vg:accept", "phase": "7.14.3",
           "run_id": "run-cccc-3333",
           "started_at": _fresh_started_at()}
    repo = _setup_fake_repo(tmp_path, current_run=run)
    # Pre-seed drift_count=1 — even at count=1, mixed violations must NOT
    # trigger auto-fire because telemetry gaps signal real pipeline missing.
    drift_state = {
        "run-cccc-3333": {
            "drift_count": 1,
            "first_drift_at": _fresh_started_at(),
            "last_drift_at": _fresh_started_at(),
            "violations_seen": ["must_touch_markers"],
        }
    }
    (repo / ".vg" / ".session-drift.json").write_text(
        json.dumps(drift_state), encoding="utf-8"
    )

    mod = _load_hook_module(repo)

    mixed_stderr = (
        "Missing evidence:\n"
        "  [must_touch_markers]\n"
        "    - 8_execute_waves\n"
        "  [must_emit_telemetry]\n"
        "    - wave_started\n"
    )
    monkeypatch.setattr(mod, "run_orchestrator_complete",
                        lambda: (2, "", mixed_stderr))
    auto_fire_calls = []
    monkeypatch.setattr(mod, "_auto_fire_markers",
                        lambda p: (auto_fire_calls.append(p) or (0, "", "")))

    rc, out, err = _drive_main(mod, capsys)

    assert rc == 2
    assert auto_fire_calls == [], "mixed violations must never auto-fire"
    # drift_count NOT bumped — non-marker-only path bypasses _bump_drift
    state = json.loads((repo / ".vg" / ".session-drift.json").read_text())
    assert state["run-cccc-3333"]["drift_count"] == 1


def test_auto_fire_failure_blocks(tmp_path, capsys, monkeypatch):
    """drift_count=1 + auto-fire migrate-state rc=2 → BLOCK with FAILED message."""
    run = {"command": "vg:accept", "phase": "7.14.3",
           "run_id": "run-dddd-4444",
           "started_at": _fresh_started_at()}
    repo = _setup_fake_repo(tmp_path, current_run=run)
    drift_state = {
        "run-dddd-4444": {
            "drift_count": 1,
            "first_drift_at": _fresh_started_at(),
            "last_drift_at": _fresh_started_at(),
            "violations_seen": ["must_touch_markers"],
        }
    }
    (repo / ".vg" / ".session-drift.json").write_text(
        json.dumps(drift_state), encoding="utf-8"
    )

    mod = _load_hook_module(repo)
    monkeypatch.setattr(mod, "run_orchestrator_complete",
                        lambda: (2, "", "Missing evidence:\n  [must_touch_markers]\n    - x\n"))
    monkeypatch.setattr(mod, "_auto_fire_markers",
                        lambda p: (2, "", "migrate-state crashed: bug X"))

    rc, out, err = _drive_main(mod, capsys)
    assert rc == 2
    assert "auto-recovery FAILED" in err
    assert "bug X" in err


def test_retry_after_autofire_still_blocks(tmp_path, capsys, monkeypatch):
    """drift_count=1 → auto-fire OK → retry STILL blocks (e.g. cleanup
    happened but markers still missing). No approve, fall through stderr."""
    run = {"command": "vg:accept", "phase": "7.14.3",
           "run_id": "run-eeee-5555",
           "started_at": _fresh_started_at()}
    repo = _setup_fake_repo(tmp_path, current_run=run)
    drift_state = {
        "run-eeee-5555": {
            "drift_count": 1,
            "first_drift_at": _fresh_started_at(),
            "last_drift_at": _fresh_started_at(),
            "violations_seen": ["must_touch_markers"],
        }
    }
    (repo / ".vg" / ".session-drift.json").write_text(
        json.dumps(drift_state), encoding="utf-8"
    )

    mod = _load_hook_module(repo)

    call_count = {"n": 0}
    def fake_run():
        call_count["n"] += 1
        return (2, "", "Missing evidence:\n  [must_touch_markers]\n    - x\n")
    monkeypatch.setattr(mod, "run_orchestrator_complete", fake_run)
    monkeypatch.setattr(mod, "_auto_fire_markers",
                        lambda p: (0, "no drift", ""))

    rc, out, err = _drive_main(mod, capsys)
    assert rc == 2
    assert call_count["n"] == 2  # initial + retry


def test_parse_violation_types_basic(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    mod = _load_hook_module(repo)
    s = (
        "Missing evidence:\n"
        "  [must_touch_markers]\n"
        "    - x\n"
        "  [must_emit_telemetry]\n"
        "    - y\n"
        "  [must_write]\n"
        "    - PLAN.md\n"
    )
    types = mod._parse_violation_types(s)
    assert types == {"must_touch_markers", "must_emit_telemetry", "must_write"}
    assert mod._is_marker_only_drift(s) is False
    # Pure marker
    s2 = "Missing evidence:\n  [must_touch_markers]\n    - x\n"
    assert mod._is_marker_only_drift(s2) is True
    # Empty
    assert mod._is_marker_only_drift("") is False
    assert mod._is_marker_only_drift("random text without tags") is False


def test_drift_state_gc_drops_stale_entries(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    mod = _load_hook_module(repo)
    # Pre-seed: one fresh, one stale (>120min)
    fresh_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_ts = (datetime.utcnow() - timedelta(minutes=200)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    raw = {
        "run-fresh": {"drift_count": 1, "first_drift_at": fresh_ts,
                      "last_drift_at": fresh_ts, "violations_seen": []},
        "run-stale": {"drift_count": 5, "first_drift_at": stale_ts,
                      "last_drift_at": stale_ts, "violations_seen": []},
    }
    (repo / ".vg" / ".session-drift.json").write_text(
        json.dumps(raw), encoding="utf-8"
    )
    state = mod._read_drift_state()
    assert "run-fresh" in state
    assert "run-stale" not in state, "stale entry must be GC'd"
