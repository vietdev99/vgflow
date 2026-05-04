"""
VG Harness v2.7 Phase Q — calibration decay-policy enforcement tests.

4 cases per Phase Q plan (decay-only sub-deliverable):

  1. Suggestion age 3 phases (< threshold 5) → no decay action,
     suggestion stays active.
  2. Suggestion age 6 phases (> threshold) WITHOUT confirming evidence
     → marked RETIRED in state file + decay event emitted.
  3. Suggestion age 6 phases WITH confirming evidence (validator still
     firing pattern matches) → stays active, no decay.
  4. `apply-decay` without TTY → BLOCK with "TTY or HMAC required"
     message.

All tests use VG_REPO_ROOT scoped to tmp_path. The script is imported
in-process via importlib for direct compute coverage; subprocess path
exercises full CLI gating end-to-end.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "registry-calibrate.py"
)


# ─────────────────────────────── fixtures ─────────────────────────────────

@pytest.fixture
def calib(monkeypatch, tmp_path):
    """Import registry-calibrate.py with VG_REPO_ROOT scoped to tmp_path."""
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    (tmp_path / ".vg").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vg" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / ".claude" / "scripts" / "validators").mkdir(
        parents=True, exist_ok=True
    )
    (tmp_path / ".claude" / "scripts" / "validators" /
     "dispatch-manifest.json").write_text(
        json.dumps({"version": "1.0", "validators": {}}, indent=2),
        encoding="utf-8",
    )
    sys.modules.pop("registry_calibrate", None)
    spec = importlib.util.spec_from_file_location(
        "registry_calibrate", str(SCRIPT_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["registry_calibrate"] = mod
    return mod


def _write_manifest(tmp_path: Path, validators: dict) -> None:
    p = tmp_path / ".claude" / "scripts" / "validators" / "dispatch-manifest.json"
    p.write_text(
        json.dumps({"version": "1.0", "validators": validators}, indent=2),
        encoding="utf-8",
    )


def _write_events(tmp_path: Path, events: list[dict]) -> None:
    p = tmp_path / ".vg" / "events.jsonl"
    p.write_text(
        "\n".join(json.dumps(e) for e in events) + ("\n" if events else ""),
        encoding="utf-8",
    )


def _write_state(tmp_path: Path, state: dict) -> None:
    p = tmp_path / ".vg" / "calibration-suggestions-state.json"
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _events_with_phases(phases: list[str]) -> list[dict]:
    """Build a synthetic events stream so _current_phase_counter sees N
    distinct phases. Each phase gets one PASS validation event so the
    count is deterministic."""
    return [
        {
            "event_type": "validation.passed", "outcome": "PASS",
            "phase": p, "payload": {"validator": "dummy-counter-validator"},
        }
        for p in phases
    ]


def _block_overrides_events(
    validator: str, *, blocks: int, overrides: int, phase: str = "10",
) -> list[dict]:
    out: list[dict] = []
    for _ in range(blocks):
        out.append({
            "event_type": "validation.failed",
            "outcome": "BLOCK", "phase": phase,
            "payload": {"validator": validator},
        })
    for _ in range(overrides):
        out.append({
            "event_type": "override.used",
            "outcome": "INFO", "phase": phase,
            "payload": {"flag": validator, "reason": "x" * 50},
        })
    return out


# ─────────────────────────────── tests ────────────────────────────────────

def test_01_age_below_threshold_no_decay(calib, tmp_path):
    """Case 1: suggestion age 3 phases < threshold 5 → no decay.

    State records first_seen_phase=2, current phase counter=5
    (5-2=3 phases of age). Threshold=5. Should stay active even if
    no confirming evidence (we omit it from manifest entirely).
    """
    # Seed 5 distinct phases of events so phase_counter == 5
    _write_events(tmp_path, _events_with_phases(["1", "2", "3", "4", "5"]))
    # Empty manifest → fresh suggestions = []
    _write_manifest(tmp_path, {})
    # Pre-stamp state: suggestion S-AAA first seen at phase_counter=2
    _write_state(tmp_path, {
        "S-AAA": {
            "first_seen_phase": 2,
            "first_seen_ts": "2026-04-20T00:00:00+00:00",
            "validator": "verify-foo",
            "kind": "downgrade",
            "proposed_severity": "WARN",
        },
    })

    candidates = calib._compute_decay_candidates(decay_after_phases=5)
    assert candidates == [], (
        f"Age 3 < threshold 5, expected no decay candidates, "
        f"got {candidates}"
    )


def test_02_age_above_threshold_no_evidence_decays(
    monkeypatch, calib, tmp_path,
):
    """Case 2: age 6 phases > threshold 5 + no confirming evidence
    → RETIRED in state + calibration.suggestion_decayed event emitted."""
    # 8 distinct phases → phase_counter = 8
    _write_events(tmp_path, _events_with_phases(
        ["10", "11", "12", "13", "14", "15", "16", "17"]
    ))
    # Empty manifest → fresh recompute returns 0 suggestions
    # (= no confirming evidence for tracked S-BBB)
    _write_manifest(tmp_path, {})
    _write_state(tmp_path, {
        "S-BBB": {
            "first_seen_phase": 2,  # age = 8 - 2 = 6
            "first_seen_ts": "2026-04-20T00:00:00+00:00",
            "validator": "verify-stale-bar",
            "kind": "downgrade",
            "proposed_severity": "WARN",
        },
    })

    candidates = calib._compute_decay_candidates(decay_after_phases=5)
    assert len(candidates) == 1, (
        f"Expected 1 decay candidate, got {len(candidates)}: {candidates}"
    )
    c = candidates[0]
    assert c["suggestion_id"] == "S-BBB"
    assert c["age_phases"] == 6
    assert "decay" in c["retire_reason"]
    assert "5 phases" in c["retire_reason"]

    # Mock TTY + capture decay event emission
    captured_events: list[dict] = []

    def fake_emit(*, candidate, operator_token):
        captured_events.append({
            "suggestion_id": candidate["suggestion_id"],
            "age_phases": candidate["age_phases"],
            "retire_reason": candidate["retire_reason"],
            "operator_token": operator_token,
        })

    long_reason = (
        "Operator-approved decay action after dashboard review of "
        "stale calibration suggestions — verified telemetry no longer "
        "matches threshold profile across phases."
    )

    # Touch suggestions MD so the annotate path doesn't no-op
    (tmp_path / ".vg" / "CALIBRATION-SUGGESTIONS.md").write_text(
        "# CALIBRATION-SUGGESTIONS\n\n_seed_\n", encoding="utf-8",
    )

    with patch.object(calib, "_verify_human",
                      return_value=(True, "test-op", None)):
        with patch.object(calib, "_emit_decay_event", side_effect=fake_emit):
            ns = type("ns", (), {})()
            ns.reason = long_reason
            ns.decay_after_phases = 5
            ns.dry_run = False
            rc = calib.cmd_apply_decay(ns)

    assert rc == 0, "apply-decay with TTY + reason should PASS"
    assert len(captured_events) == 1
    assert captured_events[0]["suggestion_id"] == "S-BBB"
    assert captured_events[0]["age_phases"] == 6

    # Verify state file marked RETIRED (forensic trail, not deletion)
    state = json.loads(
        (tmp_path / ".vg" / "calibration-suggestions-state.json")
        .read_text(encoding="utf-8")
    )
    assert "S-BBB" in state, "RETIRED entry must remain — forensic trail"
    assert "retired_at" in state["S-BBB"]
    assert state["S-BBB"]["retire_reason"].startswith("decay")
    assert state["S-BBB"]["retired_age_phases"] == 6

    # Verify suggestions MD annotated with retired block
    md = (tmp_path / ".vg" / "CALIBRATION-SUGGESTIONS.md").read_text(
        encoding="utf-8"
    )
    assert "Retired (decay)" in md
    assert "S-BBB" in md


def test_03_age_above_threshold_with_evidence_no_decay(
    calib, tmp_path,
):
    """Case 3: age 6 phases > threshold but validator's firing pattern
    still crosses threshold in fresh recompute → no decay (confirming
    evidence keeps suggestion active)."""
    # 8 distinct phases → phase_counter = 8
    base_events = _events_with_phases(
        ["10", "11", "12", "13", "14", "15", "16", "17"]
    )
    # Add real telemetry for verify-friction-foo so fresh suggest emits it
    # 15 fires, 12 overrides → rate=12/15=0.80 > 0.60
    foo_events = _block_overrides_events(
        "verify-friction-foo", blocks=15, overrides=12, phase="20",
    )
    _write_events(tmp_path, base_events + foo_events)
    _write_manifest(tmp_path, {
        "verify-friction-foo": {
            "severity": "BLOCK", "unquarantinable": False,
        },
    })

    # Compute the canonical suggestion id this validator produces
    sid = calib._suggestion_id("verify-friction-foo", "WARN")

    # Pre-stamp state: same id first seen 6+ phases ago
    # phase_counter = 8 (from foo_events phase '20' is also distinct →
    # 9 phases total). Pre-stamp first_seen_phase so age >= 5.
    fresh = calib.compute_suggestions()
    fresh_ids = {s["id"] for s in fresh}
    assert sid in fresh_ids, (
        "Sanity: verify-friction-foo must trigger downgrade in fresh "
        "recompute for this case to test confirming-evidence path."
    )

    current_pc = calib._current_phase_counter()
    _write_state(tmp_path, {
        sid: {
            "first_seen_phase": current_pc - 6,  # age = 6
            "first_seen_ts": "2026-04-20T00:00:00+00:00",
            "validator": "verify-friction-foo",
            "kind": "downgrade",
            "proposed_severity": "WARN",
        },
    })

    candidates = calib._compute_decay_candidates(decay_after_phases=5)
    assert candidates == [], (
        f"Suggestion still has confirming evidence, must NOT decay. "
        f"Got: {candidates}"
    )


def test_04_apply_decay_without_tty_blocks(tmp_path):
    """Case 4: subprocess apply-decay without TTY → BLOCK with TTY/HMAC
    message (gate parity with Phase F apply path)."""
    # Seed minimum repo structure
    (tmp_path / ".vg").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "scripts" / "validators").mkdir(
        parents=True, exist_ok=True,
    )
    _write_manifest(tmp_path, {})
    _write_events(tmp_path, [])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(tmp_path)
    env.pop("VG_HUMAN_OPERATOR", None)
    env.pop("VG_ALLOW_FLAGS_LEGACY_RAW", None)

    long_reason = (
        "Operator-approved decay action after stale calibration "
        "review — verified no confirming evidence across phases."
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "apply-decay",
         "--reason", long_reason],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace", cwd=str(tmp_path),
    )
    assert result.returncode == 2, (
        f"Expected BLOCK rc=2 (no TTY), got rc={result.returncode}\n"
        f"stderr: {result.stderr[-400:]}"
    )
    body = (result.stderr + result.stdout).lower()
    # TTY/HMAC error message — accept any of the canonical error tokens
    assert (
        "tty" in body or "hmac" in body or "human" in body
        or "operator" in body
    ), (
        f"Stderr should mention TTY/HMAC/human-operator gate, got:\n"
        f"{result.stderr[-400:]}"
    )
