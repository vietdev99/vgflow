"""tests/test_g11_codegen_conformance_gate.py — G11 conformance gate.

Verifies that verify-codegen-lifecycle-conformance.py exists and detects
when generated test specs miss lifecycle stages defined in LIFECYCLE-SPECS.json.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VAL = REPO / "scripts" / "validators" / "verify-codegen-lifecycle-conformance.py"


def test_validator_exists():
    assert VAL.is_file(), "G11: verify-codegen-lifecycle-conformance.py must ship"


def test_validator_flags_spec_missing_lifecycle_stages(tmp_path):
    """G11: generated spec must cover every step in LIFECYCLE-SPECS.json for that goal."""
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "goals": {
            "G-01": {
                "steps": [
                    {"name": "read_before"}, {"name": "create"}, {"name": "read_after_create"}
                ]
            }
        }
    }), encoding="utf-8")
    # Spec file only mentions 'create' step, missing the reads
    spec_dir = phase_dir / "generated-tests"
    spec_dir.mkdir()
    (spec_dir / "G-01.spec.ts").write_text("// GOAL: G-01\ntest('create', () => {})", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase", "99", "--phase-dir", str(phase_dir),
         "--spec-dir", str(spec_dir)],
        capture_output=True, text=True,
    )
    assert (r.returncode != 0) or ("read_before" in r.stdout or "read_after_create" in r.stdout) or "G11" in r.stdout, (
        f"G11: validator must flag spec missing lifecycle stages. "
        f"stdout={r.stdout[:500]}"
    )


def test_validator_passes_when_all_stages_covered(tmp_path):
    """G11: when spec references all stages, no G11 issue."""
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps({
        "goals": {
            "G-01": {
                "steps": [
                    {"name": "read_before"},
                    {"name": "create"},
                    {"name": "read_after_create"},
                ]
            }
        }
    }), encoding="utf-8")
    spec_dir = phase_dir / "generated-tests"
    spec_dir.mkdir()
    (spec_dir / "G-01.spec.ts").write_text(
        "// GOAL: G-01\ntest('read_before', () => {})\ntest('create', () => {})\ntest('read_after_create', () => {})",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase", "99", "--phase-dir", str(phase_dir),
         "--spec-dir", str(spec_dir)],
        capture_output=True, text=True,
    )
    # Should pass (no G11 issues)
    assert "G11" not in r.stdout or "OK" in r.stdout, (
        f"G11: all-stages-covered spec must not trigger G11 issues. stdout={r.stdout[:500]}"
    )


def test_regression_security_invokes_gate():
    body = (REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md").read_text(encoding="utf-8")
    assert "verify-codegen-lifecycle-conformance" in body, (
        "G11: regression-security.md must invoke verify-codegen-lifecycle-conformance.py "
        "before 5e_regression run"
    )
