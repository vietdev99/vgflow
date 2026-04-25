"""
VG Harness v2.6 Phase F — registry-calibrate.py regression tests.

10 cases per PLAN-REVISED.md Phase F work item #5:

  1. No events.jsonl → empty suggestions, no crash
  2. Validator with override_rate > 60% AND not UNQUARANTINABLE
     → BLOCK→WARN downgrade suggested
  3. Validator with override_rate > 60% AND UNQUARANTINABLE
     → NO suggestion (exempted)
  4. Validator with WARN + BLOCK-correlation > 80%
     → WARN→BLOCK upgrade suggested
  5. Validator with WARN + UNQUARANTINABLE + correlation > 80%
     → upgrade suggestion still emitted (UNQUARANTINABLE doesn't
     block upgrades)
  6. Total fires < 10 → no suggestion (insufficient data)
  7. Domain-cluster: 5 security/ validators, 4 BLOCK + 1 WARN outlier
     → cluster alignment suggested
  8. apply --suggestion-id without --reason → BLOCK with
     "reason mandatory" error
  9. apply --suggestion-id with --reason but no TTY → BLOCK with
     TTY-required error
 10. apply --suggestion-id with valid TTY/reason → PASS,
     dispatch-manifest.json updated, audit event emitted

All tests use VG_REPO_ROOT scoped to tmp_path; the script is imported
in-process via importlib so we get full Python coverage. Subprocess
path used only for cases 8-10 (CLI gating).
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


def _events_block_warn_pass_override(
    validator: str,
    *,
    blocks: int = 0,
    warns: int = 0,
    passes: int = 0,
    overrides: int = 0,
    phase: str = "10",
) -> list[dict]:
    """Build synthetic event stream for a single validator."""
    out: list[dict] = []
    for _ in range(blocks):
        out.append({
            "event_type": "validation.failed",
            "outcome": "BLOCK", "phase": phase,
            "payload": {"validator": validator, "evidence_count": 1},
        })
    for _ in range(warns):
        out.append({
            "event_type": "validation.warned",
            "outcome": "WARN", "phase": phase,
            "payload": {"validator": validator, "evidence_count": 1},
        })
    for _ in range(passes):
        out.append({
            "event_type": "validation.passed",
            "outcome": "PASS", "phase": phase,
            "payload": {"validator": validator, "evidence_count": 0},
        })
    for _ in range(overrides):
        out.append({
            "event_type": "override.used",
            "outcome": "INFO", "phase": phase,
            "payload": {"flag": validator, "reason": "test override 50chars" * 4},
        })
    return out


def _write_events(tmp_path: Path, events: list[dict]) -> None:
    p = tmp_path / ".vg" / "events.jsonl"
    p.write_text(
        "\n".join(json.dumps(e) for e in events) + ("\n" if events else ""),
        encoding="utf-8",
    )


# ─────────────────────────────── tests ────────────────────────────────────

def test_01_no_events_empty_suggestions(calib, tmp_path):
    """Case 1: empty events.jsonl → 0 suggestions, no crash."""
    suggestions = calib.compute_suggestions(
        events=[], manifest={"validators": {}}, quarantine={},
        unquarantinable=set(),
    )
    assert suggestions == []
    # render still works on empty
    md = calib.render_markdown(suggestions, n_unquarantinable=0)
    assert "No suggestions" in md


def test_02_block_high_override_not_unq_downgrades(calib, tmp_path):
    """Case 2: BLOCK + override > 60% + not UNQ → downgrade suggested."""
    validators = {
        "verify-friction-foo": {"severity": "BLOCK", "unquarantinable": False},
    }
    # 15 fires, all BLOCK; 12 overrides → rate = 12/15 = 0.80 > 0.60
    events = _events_block_warn_pass_override(
        "verify-friction-foo", blocks=15, overrides=12,
    )
    suggestions = calib.compute_suggestions(
        events=events, manifest={"validators": validators},
        quarantine={}, unquarantinable=set(),
    )
    downgrades = [s for s in suggestions if s["kind"] == "downgrade"]
    assert len(downgrades) == 1
    s = downgrades[0]
    assert s["validator"] == "verify-friction-foo"
    assert s["current_severity"] == "BLOCK"
    assert s["proposed_severity"] == "WARN"
    assert s["unquarantinable"] is False
    assert s["evidence"]["override_rate"] >= 0.6


def test_03_block_high_override_unq_no_suggestion(calib, tmp_path):
    """Case 3: BLOCK + override > 60% + UNQUARANTINABLE → SKIPPED."""
    validators = {
        "verify-jwt-session-policy": {
            "severity": "BLOCK", "unquarantinable": True,
        },
    }
    events = _events_block_warn_pass_override(
        "verify-jwt-session-policy", blocks=20, overrides=18,
    )
    suggestions = calib.compute_suggestions(
        events=events, manifest={"validators": validators},
        quarantine={}, unquarantinable={"verify-jwt-session-policy"},
    )
    assert all(
        s["kind"] != "downgrade" for s in suggestions
    ), "UNQUARANTINABLE downgrade should be suppressed"


def test_04_warn_high_correlation_upgrades(calib, tmp_path):
    """Case 4: WARN with same-phase BLOCK in >80% phases → upgrade."""
    validators = {
        "verify-leading-warn": {"severity": "WARN", "unquarantinable": False},
        # peer that produces BLOCK in same phase
        "verify-downstream-block": {
            "severity": "BLOCK", "unquarantinable": False,
        },
    }
    events: list[dict] = []
    # 11 phases — leading-warn fires WARN in each, downstream-block
    # fires BLOCK in 10/11 (>80%) — leading-warn fires once per phase
    for i in range(11):
        phase = str(100 + i)
        events.append({
            "event_type": "validation.warned", "outcome": "WARN",
            "phase": phase, "payload": {"validator": "verify-leading-warn"},
        })
        if i < 10:
            events.append({
                "event_type": "validation.failed", "outcome": "BLOCK",
                "phase": phase,
                "payload": {"validator": "verify-downstream-block"},
            })
    suggestions = calib.compute_suggestions(
        events=events, manifest={"validators": validators},
        quarantine={}, unquarantinable=set(),
    )
    upgrades = [s for s in suggestions
                if s["kind"] == "upgrade"
                and s["validator"] == "verify-leading-warn"]
    assert len(upgrades) == 1
    assert upgrades[0]["current_severity"] == "WARN"
    assert upgrades[0]["proposed_severity"] == "BLOCK"
    assert upgrades[0]["evidence"]["block_correlation"] >= 0.8


def test_05_warn_unq_high_correlation_still_upgrades(calib, tmp_path):
    """Case 5: UNQUARANTINABLE doesn't block upgrade suggestions."""
    validators = {
        "verify-security-warn-leading": {
            "severity": "WARN", "unquarantinable": True,
        },
        "verify-other-block": {
            "severity": "BLOCK", "unquarantinable": False,
        },
    }
    events: list[dict] = []
    for i in range(11):
        phase = str(200 + i)
        events.append({
            "event_type": "validation.warned", "outcome": "WARN",
            "phase": phase,
            "payload": {"validator": "verify-security-warn-leading"},
        })
        if i < 10:
            events.append({
                "event_type": "validation.failed", "outcome": "BLOCK",
                "phase": phase,
                "payload": {"validator": "verify-other-block"},
            })
    suggestions = calib.compute_suggestions(
        events=events, manifest={"validators": validators},
        quarantine={},
        unquarantinable={"verify-security-warn-leading"},
    )
    upgrades = [s for s in suggestions
                if s["kind"] == "upgrade"
                and s["validator"] == "verify-security-warn-leading"]
    assert len(upgrades) == 1, (
        "UNQUARANTINABLE must NOT block upgrade direction"
    )
    assert upgrades[0]["unquarantinable"] is True


def test_06_under_min_fires_no_suggestion(calib, tmp_path):
    """Case 6: total fires < 10 → no suggestion (insufficient data)."""
    validators = {
        "verify-rare-foo": {"severity": "BLOCK", "unquarantinable": False},
    }
    # 5 BLOCKs, 5 overrides — rate=100% but fires=5 < MIN_FIRES
    events = _events_block_warn_pass_override(
        "verify-rare-foo", blocks=5, overrides=5,
    )
    suggestions = calib.compute_suggestions(
        events=events, manifest={"validators": validators},
        quarantine={}, unquarantinable=set(),
    )
    assert suggestions == [], (
        "Sub-threshold fires must not produce suggestions"
    )


def test_07_domain_cluster_outlier_alignment(calib, tmp_path):
    """Case 7: domain cluster with majority BLOCK + 1 WARN outlier."""
    validators = {
        "verify-security-headers-runtime": {
            "severity": "BLOCK", "unquarantinable": True,
        },
        "verify-security-baseline-project": {
            "severity": "BLOCK", "unquarantinable": True,
        },
        "verify-security-test-plan": {
            "severity": "BLOCK", "unquarantinable": True,
        },
        "verify-security-baseline": {
            "severity": "BLOCK", "unquarantinable": True,
        },
        # outlier
        "verify-security-warn-only": {
            "severity": "WARN", "unquarantinable": False,
        },
    }
    suggestions = calib.compute_suggestions(
        events=[], manifest={"validators": validators},
        quarantine={}, unquarantinable=set(),
    )
    cluster = [s for s in suggestions if s["kind"] == "domain-cluster"]
    assert len(cluster) >= 1
    outlier = next(
        (s for s in cluster
         if s["validator"] == "verify-security-warn-only"),
        None,
    )
    assert outlier is not None, "outlier WARN must be flagged"
    assert outlier["current_severity"] == "WARN"
    assert outlier["proposed_severity"] == "BLOCK"


# ───────────── CLI subprocess tests (cases 8-10) ──────────────────────────

def _run_cli(args: list[str], cwd: Path,
             extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    # Strip any inherited human-operator token so non-TTY tests are
    # deterministic
    env.pop("VG_HUMAN_OPERATOR", None)
    env.pop("VG_ALLOW_FLAGS_LEGACY_RAW", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _seed_repo_for_cli(tmp_path: Path, *, with_suggestion: bool) -> str:
    """Build a tmp repo with manifest + events that produce one
    deterministic suggestion. Returns the suggestion id (or '' if none)."""
    (tmp_path / ".vg").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "scripts" / "validators").mkdir(
        parents=True, exist_ok=True,
    )
    if with_suggestion:
        validators = {
            "verify-friction-foo": {
                "severity": "BLOCK", "unquarantinable": False,
            },
        }
        events = _events_block_warn_pass_override(
            "verify-friction-foo", blocks=15, overrides=12,
        )
    else:
        validators = {}
        events = []
    _write_manifest(tmp_path, validators)
    _write_events(tmp_path, events)

    if with_suggestion:
        # Compute suggestion id by importing module — same logic the
        # subprocess will use, so id matches
        sys.modules.pop("registry_calibrate", None)
        spec = importlib.util.spec_from_file_location(
            "registry_calibrate", str(SCRIPT_PATH)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._suggestion_id("verify-friction-foo", "WARN")
    return ""


def test_08_apply_without_reason_blocks(tmp_path):
    """Case 8: `apply --suggestion-id S-XXX` with no --reason → BLOCK."""
    sid = _seed_repo_for_cli(tmp_path, with_suggestion=True)
    # argparse treats --reason as required → returns rc=2 with usage
    result = _run_cli(["apply", "--suggestion-id", sid], cwd=tmp_path)
    assert result.returncode == 2, (
        f"Expected BLOCK rc=2, got rc={result.returncode}\n"
        f"stderr: {result.stderr[-300:]}"
    )
    combined = (result.stderr + result.stdout).lower()
    assert "reason" in combined, (
        "Stderr should mention --reason requirement"
    )


def test_09_apply_with_short_reason_blocks(tmp_path):
    """Case 9b: `--reason` < 50 chars → BLOCK with mandatory-min msg.

    Real-world subagent attack: AI passes a short cookie-cutter reason.
    Min-50 gate catches it before TTY check.
    """
    sid = _seed_repo_for_cli(tmp_path, with_suggestion=True)
    result = _run_cli(
        ["apply", "--suggestion-id", sid, "--reason", "too short"],
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "min 50 chars" in (result.stderr + result.stdout).lower()


def test_09_apply_with_reason_no_tty_blocks(tmp_path):
    """Case 9: valid reason length but no TTY + no signed token → BLOCK."""
    sid = _seed_repo_for_cli(tmp_path, with_suggestion=True)
    long_reason = (
        "Operator-approved calibration after dashboard review of "
        "2026-04-26 phase-F dogfood — override pattern stable across "
        "phases 100-110 and matches plan-revised.md F threshold guidance"
    )
    # Subprocess inherits no TTY (capture_output=True); strict-mode
    # default = True per allow_flag_gate.DEFAULT_STRICT
    result = _run_cli(
        ["apply", "--suggestion-id", sid, "--reason", long_reason],
        cwd=tmp_path,
    )
    assert result.returncode == 2, (
        f"Expected BLOCK rc=2 (no TTY), got rc={result.returncode}\n"
        f"stderr: {result.stderr[-400:]}"
    )
    body = (result.stderr + result.stdout).lower()
    assert "tty" in body or "human" in body or "operator" in body


def test_10_apply_with_tty_succeeds_and_emits_audit(
    monkeypatch, tmp_path, calib,
):
    """Case 10: bypass TTY by mocking verify_human_operator → PASS.

    Verifies:
      - dispatch-manifest.json severity flipped
      - calibrate.applied audit event emitted (best-effort, db.append_event)
    """
    # Recompute suggestions in-process so we can inject the mock
    validators = {
        "verify-friction-foo": {
            "severity": "BLOCK", "unquarantinable": False,
        },
    }
    events = _events_block_warn_pass_override(
        "verify-friction-foo", blocks=15, overrides=12,
    )
    _write_manifest(tmp_path, validators)
    _write_events(tmp_path, events)

    suggestions = calib.compute_suggestions(
        events=events, manifest={"validators": validators},
        quarantine={}, unquarantinable=set(),
    )
    assert len(suggestions) == 1
    sid = suggestions[0]["id"]

    # Mock verify_human_operator to claim TTY and capture audit emission
    audit_calls: list[dict] = []

    def fake_emit(suggestion, reason, approver):
        audit_calls.append({
            "suggestion_id": suggestion["id"],
            "validator": suggestion["validator"],
            "old": suggestion["current_severity"],
            "new": suggestion["proposed_severity"],
            "reason": reason,
            "approver": approver,
        })

    long_reason = (
        "Operator-approved calibration after dashboard review of "
        "2026-04-26 phase-F dogfood — override pattern verified."
    )

    with patch.object(calib, "_verify_human",
                      return_value=(True, "test-operator", None)):
        with patch.object(calib, "_emit_audit_event",
                          side_effect=fake_emit):
            ns = type("ns", (), {})()
            ns.suggestion_id = sid
            ns.reason = long_reason
            rc = calib.cmd_apply(ns)

    assert rc == 0, "apply with TTY + reason should PASS"
    # Verify manifest mutation
    new_manifest = json.loads(
        (tmp_path / ".claude" / "scripts" / "validators"
         / "dispatch-manifest.json").read_text(encoding="utf-8")
    )
    new_sev = new_manifest["validators"]["verify-friction-foo"]["severity"]
    assert new_sev == "WARN", f"manifest not updated, severity={new_sev}"
    # Verify audit emission
    assert len(audit_calls) == 1
    assert audit_calls[0]["suggestion_id"] == sid
    assert audit_calls[0]["old"] == "BLOCK"
    assert audit_calls[0]["new"] == "WARN"
    assert audit_calls[0]["approver"] == "test-operator"
