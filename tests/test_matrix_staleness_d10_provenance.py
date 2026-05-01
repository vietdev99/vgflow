"""Tests for verify-matrix-staleness.py D10 trustworthy-provenance gate.

Wave-3.2.3 (RFC v9 D10): bidirectional sync (SUSPECTED → READY) must only
trigger when the submit step bears `evidence.source: scanner` (with
`scanner_run_id`) or `evidence.source: diagnostic_l2` (with
`layer2_proposal_id`). Hand-written `executor`/`manual` evidence keeps
SUSPECTED — closes the trust hole where executor agents could fabricate
submit + 2xx evidence to flip the matrix back.

Exercises the `trustworthy_submit_evidence()` helper directly + verifies
end-to-end behavior via subprocess invocation against a fixture phase.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATORS_DIR = REPO_ROOT / "scripts" / "validators"
sys.path.insert(0, str(VALIDATORS_DIR))

# Module imported as a hyphen-named file — load via importlib
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "verify_matrix_staleness",
    VALIDATORS_DIR / "verify-matrix-staleness.py",
)
matrix_staleness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(matrix_staleness)


# ─── Unit tests for trustworthy_submit_evidence() ─────────────────────────────


def _seq_with_step(step: dict) -> dict:
    return {"steps": [step]}


def test_scanner_with_run_id_is_trustworthy():
    seq = _seq_with_step({
        "do": "click",
        "target": "Submit topup",
        "evidence": {
            "source": "scanner",
            "scanner_run_id": "haiku-2026-05-02-abc123",
            "artifact_hash": "sha256:deadbeef",
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "1.0",
        },
    })
    ok, reason = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is True
    assert reason is None


def test_scanner_without_run_id_is_not_trustworthy():
    seq = _seq_with_step({
        "do": "click",
        "target": "Submit topup",
        "evidence": {"source": "scanner"},  # missing scanner_run_id
    })
    ok, reason = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is False
    # Falls through to "submit step lacks structured evidence" because the
    # only submit step's evidence is rejected (no scanner_run_id) and no
    # weak_source was captured (since 'scanner' is in trustworthy set).
    # Either reason is acceptable — what matters is ok=False.


def test_diagnostic_l2_with_proposal_id_is_trustworthy():
    seq = _seq_with_step({
        "do": "submit",
        "target": "Confirm withdraw",
        "evidence": {
            "source": "diagnostic_l2",
            "layer2_proposal_id": "l2-proposal-7e9f",
            "artifact_hash": "sha256:cafebabe",
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "1.0",
        },
    })
    ok, reason = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is True
    assert reason is None


def test_diagnostic_l2_without_proposal_id_is_not_trustworthy():
    seq = _seq_with_step({
        "do": "submit",
        "target": "Confirm withdraw",
        "evidence": {"source": "diagnostic_l2"},  # missing layer2_proposal_id
    })
    ok, _ = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is False


def test_executor_evidence_is_rejected():
    seq = _seq_with_step({
        "do": "click",
        "target": "Approve transaction",
        "evidence": {
            "source": "executor",  # hand-written by executor agent — DENY
            "artifact_hash": "sha256:fake",
            "captured_at": "2026-05-02T10:00:00Z",
            "schema_version": "1.0",
        },
    })
    ok, reason = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is False
    assert "executor" in reason


def test_manual_evidence_is_rejected():
    seq = _seq_with_step({
        "do": "click",
        "target": "Submit",
        "evidence": {"source": "manual"},
    })
    ok, reason = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is False
    assert "manual" in reason


def test_orchestrator_evidence_is_rejected():
    seq = _seq_with_step({
        "do": "click",
        "target": "Confirm",
        "evidence": {"source": "orchestrator"},
    })
    ok, reason = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is False
    assert "orchestrator" in reason


def test_missing_evidence_object_is_rejected():
    seq = _seq_with_step({
        "do": "click",
        "target": "Submit topup",
        # NO evidence key — pre-v9 / legacy
    })
    ok, reason = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is False
    # Either "no submit step" if SUBMIT_TARGET_RE didn't catch, or the
    # "lacks structured evidence" path; both are acceptable refusals.
    assert reason is not None


def test_cancel_step_does_not_count_as_submit():
    seq = _seq_with_step({
        "do": "click",
        "target": "Cancel",
        "evidence": {
            "source": "scanner",
            "scanner_run_id": "x",
        },
    })
    ok, reason = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is False
    # The submit-target regex should reject "Cancel" (cancel verb wins),
    # so we never see this as a submit step.
    assert reason == "no submit step"


def test_multiple_steps_one_trustworthy_passes():
    seq = {
        "steps": [
            {  # Earlier weak step (executor)
                "do": "click",
                "target": "Submit topup",
                "evidence": {"source": "executor"},
            },
            {  # Later trustworthy step (scanner)
                "do": "click",
                "target": "Submit topup",
                "evidence": {
                    "source": "scanner",
                    "scanner_run_id": "haiku-r2",
                },
            },
        ],
    }
    ok, _ = matrix_staleness.trustworthy_submit_evidence(seq)
    assert ok is True  # any trustworthy submit step is enough


def test_non_dict_seq_is_safe():
    ok, reason = matrix_staleness.trustworthy_submit_evidence({"steps": "not-a-list"})
    assert ok is False
    assert reason == "steps not list"


# ─── End-to-end test: invoke validator binary against synthetic phase ──────


@pytest.fixture
def synthetic_phase(tmp_path: Path):
    """Build a minimal phase tree with TEST-GOALS, RUNTIME-MAP, MATRIX."""
    phases_dir = tmp_path / ".vg" / "phases"
    phase_dir = phases_dir / "99.9-d10-test"
    phase_dir.mkdir(parents=True)

    (phase_dir / "TEST-GOALS.md").write_text(
        "## Goal G-01: Submit topup\n"
        "**Surface:** ui\n"
        "**Mutation evidence:** POST /api/topup returns 200 with id\n",
        encoding="utf-8",
    )

    (phase_dir / "GOAL-COVERAGE-MATRIX.md").write_text(
        "| Goal | Type | Evidence | Status |\n"
        "|------|------|----------|--------|\n"
        "| G-01 | mutation | trace-x | SUSPECTED |\n",
        encoding="utf-8",
    )

    yield tmp_path, phase_dir


def _run_validator(repo_root: Path, phase: str, *flags: str) -> tuple[int, dict]:
    """Invoke validator with VG_REPO_ROOT pointed at synthetic tree."""
    cmd = [
        sys.executable,
        str(VALIDATORS_DIR / "verify-matrix-staleness.py"),
        "--phase", phase,
        *flags,
    ]
    proc = subprocess.run(
        cmd,
        env={"VG_REPO_ROOT": str(repo_root), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        out = {"verdict": "PARSE_ERROR", "stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, out


def _write_runtime_map(phase_dir: Path, evidence_block: dict | None) -> None:
    step = {
        "do": "click",
        "target": "Submit topup",
        "network": [{"method": "POST", "endpoint": "/api/topup", "status": 200}],
    }
    if evidence_block is not None:
        step["evidence"] = evidence_block
    (phase_dir / "RUNTIME-MAP.json").write_text(
        json.dumps({
            "goal_sequences": {
                "G-01": {"steps": [step], "result": "passed"},
            },
        }, indent=2),
        encoding="utf-8",
    )


def test_e2e_scanner_evidence_promotes_suspected_to_ready(synthetic_phase):
    repo, phase_dir = synthetic_phase
    _write_runtime_map(phase_dir, {
        "source": "scanner",
        "scanner_run_id": "haiku-r-1",
        "artifact_hash": "sha256:abc",
        "captured_at": "2026-05-02T10:00:00Z",
        "schema_version": "1.0",
    })
    rc, out = _run_validator(repo, "99.9", "--apply-status-update")
    assert rc == 0, f"Expected PASS, got rc={rc}, output={out}"
    assert out["verdict"] in ("PASS", "WARN")
    matrix_text = (phase_dir / "GOAL-COVERAGE-MATRIX.md").read_text()
    assert "READY" in matrix_text
    # Suspected_resolved evidence emitted
    types = [e["type"] for e in out.get("evidence", [])]
    assert "suspected_resolved" in types


def test_e2e_executor_evidence_keeps_suspected(synthetic_phase):
    repo, phase_dir = synthetic_phase
    _write_runtime_map(phase_dir, {"source": "executor"})  # untrustworthy
    rc, out = _run_validator(repo, "99.9", "--apply-status-update")
    matrix_text = (phase_dir / "GOAL-COVERAGE-MATRIX.md").read_text()
    # Should still be SUSPECTED — promotion blocked
    assert "SUSPECTED" in matrix_text
    types = [e["type"] for e in out.get("evidence", [])]
    # Surface the kept-with-weak-provenance signal
    assert "suspected_kept_weak_provenance" in types
    # Validator itself still passes (kept-weak is non-escalating signal)
    assert rc == 0


def test_e2e_no_evidence_keeps_suspected_silently(synthetic_phase):
    """Pre-v9 legacy: missing evidence object — keep SUSPECTED, no error."""
    repo, phase_dir = synthetic_phase
    _write_runtime_map(phase_dir, None)
    rc, out = _run_validator(repo, "99.9", "--apply-status-update")
    matrix_text = (phase_dir / "GOAL-COVERAGE-MATRIX.md").read_text()
    assert "SUSPECTED" in matrix_text
    assert rc == 0
