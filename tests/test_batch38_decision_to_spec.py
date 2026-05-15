"""tests/test_batch38_decision_to_spec.py — Batch 38.

CONTEXT D-XX → spec body traceability validator.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-decision-to-spec-coverage.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-decision-to-spec-coverage.py"
TEST_SPEC = REPO / "commands" / "vg" / "test-spec.md"
TEST_SPEC_MIRROR = REPO / ".claude" / "commands" / "vg" / "test-spec.md"


def test_validator_exists():
    assert VAL.exists()
    assert VAL_MIRROR.exists()
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")


def test_validator_blocks_uncovered_decision(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "CONTEXT.md").write_text(
        "# CONTEXT\n\n- D-01: use postgres\n- D-02: env-driven config\n- D-03: 2FA required\n",
        encoding="utf-8",
    )
    # Spec only mentions D-01
    spec_file = tmp_path / "tests" / "test.spec.ts"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("// D-01: postgres test\ntest('foo', () => {});\n", encoding="utf-8")
    # Manifest pointing to that spec
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [str(spec_file)]}),
        encoding="utf-8",
    )

    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, "must FAIL strict mode with uncovered D-02 + D-03"
    assert "D-02" in r.stderr or "D-02" in r.stdout
    assert "D-03" in r.stderr or "D-03" in r.stdout


def test_validator_passes_when_all_covered(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "CONTEXT.md").write_text(
        "# CONTEXT\n\n- D-01: x\n- D-02: y\n", encoding="utf-8")
    spec_file = tmp_path / "tests" / "test.spec.ts"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text(
        "// Covers D-01 and D-02\ntest('foo', () => {});\n", encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [str(spec_file)]}), encoding="utf-8")

    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"expected PASS, got {r.returncode}: {r.stderr}"


def test_validator_allow_uncovered_list(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "CONTEXT.md").write_text("- D-01\n- D-02\n", encoding="utf-8")
    spec_file = tmp_path / "tests" / "test.spec.ts"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("// D-01\n", encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [str(spec_file)]}), encoding="utf-8")

    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir),
         "--strict", "--allow-uncovered", "D-02"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"allow-list should let D-02 pass: {r.stderr}"


def test_bash_gate_wired_in_test_spec():
    body = TEST_SPEC.read_text(encoding="utf-8")
    assert "verify-decision-to-spec-coverage.py" in body, (
        "Batch 38: test-spec.md must invoke decision coverage validator"
    )
    assert "--allow-decision-shortfall" in body, "must support escape hatch"


def test_mirror_in_sync():
    assert TEST_SPEC.read_text(encoding="utf-8") == TEST_SPEC_MIRROR.read_text(encoding="utf-8")
