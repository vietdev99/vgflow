"""tests/test_batch35_edge_negative_manifest.py — Batch 35.

Codex audit F3+F4+F11 (docs/plans/2026-05-15-codex-review-testspec-test-flow-audit.md):

F3 CRITICAL: edge_cases[] not first-class in LIFECYCLE-SPECS.json / manifest.
F4 CRITICAL: negative paths prompt-only (codegen says "never invent
  assertions beyond TEST-GOALS").
F11 HIGH: manifest schema only required at-least-one-spec; no per-goal
  happy+edge+negative+failure coverage requirement.

Batch 35 fix: introduce verify-manifest-spec-kinds.py validator that
asserts spec_kind tagging on each manifest entry + counts per goal.
Bash gate in regression-security.md invokes validator before test runs.
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-manifest-spec-kinds.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-manifest-spec-kinds.py"
REG_SEC = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"
REG_SEC_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_validator_exists_and_executable():
    """verify-manifest-spec-kinds.py must exist + be invocable."""
    assert VAL.exists(), "Batch 35 F11: validator must exist"
    assert VAL_MIRROR.exists(), "Mirror missing"
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")
    body = VAL.read_text(encoding="utf-8")
    assert "spec_kind" in body
    assert "VALID_KINDS" in body


def test_validator_rejects_untagged_specs(tmp_path):
    """Manifest with entries missing spec_kind must FAIL."""
    import subprocess
    phase_dir = tmp_path / "phases" / "test"
    phase_dir.mkdir(parents=True)
    manifest = {
        "playwright_specs": [
            {"path": "a.spec.ts", "goal_id": "G-01"},  # no spec_kind
            {"path": "b.spec.ts", "goal_id": "G-02"},
        ]
    }
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "test", "--phase-dir", str(phase_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, "must FAIL on untagged specs"
    assert "missing spec_kind" in r.stderr or "missing spec_kind" in r.stdout


def test_validator_accepts_tagged_specs(tmp_path):
    """Manifest with proper spec_kind tagging must PASS."""
    import subprocess
    phase_dir = tmp_path / "phases" / "test"
    phase_dir.mkdir(parents=True)
    manifest = {
        "playwright_specs": [
            {"path": "a.spec.ts", "goal_id": "G-01", "spec_kind": "happy"},
            {"path": "b.spec.ts", "goal_id": "G-01", "spec_kind": "negative"},
        ]
    }
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "test", "--phase-dir", str(phase_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"expected PASS, got rc={r.returncode}\n{r.stderr}"


def test_validator_rejects_no_happy_for_goal(tmp_path):
    """Goal with edge but no happy → FAIL."""
    import subprocess
    phase_dir = tmp_path / "phases" / "test"
    phase_dir.mkdir(parents=True)
    manifest = {
        "playwright_specs": [
            {"path": "a.spec.ts", "goal_id": "G-01", "spec_kind": "edge"},
        ]
    }
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "test", "--phase-dir", str(phase_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, "must FAIL when goal has no happy spec"


def test_bash_gate_wired_in_regression_security():
    """regression-security.md must invoke verify-manifest-spec-kinds.py
    before running tests."""
    body = REG_SEC.read_text(encoding="utf-8")
    assert "verify-manifest-spec-kinds.py" in body, (
        "Batch 35 F11: regression-security.md must invoke validator "
        "before running tests"
    )
    assert "KIND_RC" in body, "must capture validator rc"
    assert "--allow-manifest-happy-only" in body, (
        "must support legacy escape hatch"
    )


def test_mirrors_in_sync():
    assert REG_SEC.read_text(encoding="utf-8") == REG_SEC_MIRROR.read_text(encoding="utf-8")
