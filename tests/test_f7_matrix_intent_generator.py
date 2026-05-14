"""tests/test_f7_matrix_intent_generator.py — F7 matrix intent generator."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "scripts" / "generate-matrix-intent.py"
MI_MD = REPO / "commands" / "vg" / "_shared" / "review" / "matrix-intent.md"


def test_generator_exists():
    assert GEN.is_file(), "F7: scripts/generate-matrix-intent.py must ship"


def test_generator_produces_matrix_intent_json(tmp_path):
    phase_dir = tmp_path / ".vg" / "phases" / "07"
    phase_dir.mkdir(parents=True)
    # Minimal GOAL-COVERAGE-MATRIX.json
    (phase_dir / "GOAL-COVERAGE-MATRIX.json").write_text(json.dumps({
        "goals": [
            {"goal_id": "G-01", "selectors_resolved": True, "endpoint_observed": True, "assertion_evidence_persisted": True},
            {"goal_id": "G-02", "selectors_resolved": True, "endpoint_observed": True, "assertion_evidence_persisted": False},
            {"goal_id": "G-03", "selectors_resolved": False, "endpoint_observed": False},
            {"goal_id": "G-04", "selectors_resolved": True, "endpoint_observed": True},
        ]
    }), encoding="utf-8")
    out = phase_dir / "MATRIX-INTENT.json"
    r = subprocess.run(
        [sys.executable, str(GEN), "--phase-dir", str(phase_dir), "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"generator failed: {r.stderr}"
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "goals" in data
    verdicts = {g["goal_id"]: g["verdict"] for g in data["goals"]}
    assert verdicts["G-01"] == "READY_BEHAVIORAL"
    assert verdicts["G-02"] == "READY_STRUCTURAL"
    assert verdicts["G-03"] == "BLOCKED"
    # G-04: missing assertion_evidence_persisted → READY_STRUCTURAL
    assert verdicts["G-04"] == "READY_STRUCTURAL"


def test_matrix_intent_step_invokes_generator():
    body = MI_MD.read_text(encoding="utf-8")
    assert "generate-matrix-intent" in body, (
        "F7: matrix-intent.md MUST invoke generate-matrix-intent.py before "
        "mark-step (currently only mark-step — no artifact written)"
    )
