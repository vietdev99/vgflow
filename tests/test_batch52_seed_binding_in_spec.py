"""tests/test_batch52_seed_binding_in_spec.py — Batch 52.

Codegen subagent reads SEED-RECIPE.md, wraps test.each(variant) with
beforeEach(runSeedRecipe)/afterEach(cleanup). Validator enforces binding.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-spec-seed-binding.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-spec-seed-binding.py"
DEL = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"
DEL_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"
TEST_SPEC = REPO / "commands" / "vg" / "test-spec.md"
TEST_SPEC_MIRROR = REPO / ".claude" / "commands" / "vg" / "test-spec.md"


def test_validator_exists_mirrored():
    assert VAL.is_file() and VAL_MIRROR.is_file()
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")


def test_delegation_declares_seed_inputs_and_contract():
    body = DEL.read_text(encoding="utf-8")
    assert "@${PHASE_DIR}/SEED-RECIPE.md" in body, (
        "Batch 52: delegation.md inputs must list SEED-RECIPE.md"
    )
    assert "seed_contract" in body or "Batch 52" in body, (
        "Batch 52: delegation.md must declare seed_contract section"
    )
    assert "runSeedRecipe" in body, "must mandate runSeedRecipe call"
    assert "cleanup" in body and "afterEach" in body, "must mandate afterEach cleanup"


def test_validator_passes_when_specs_have_binding(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": {"G-01": {
            "edge_cases": [{"kind": "boundary"}],
            "negative_specs": [{"kind": "unauthorized_401"}],
        }}}),
        encoding="utf-8",
    )
    spec_dir = tmp_path / "tests"
    spec_dir.mkdir()
    spec_file = spec_dir / "G-01.spec.ts"
    spec_file.write_text("""
test.each(variants)('G-01-b1 — boundary', async ({ page }, variant) => {
  // vg-edge-case: G-01-b1
  // seed recipe: SEED-RECIPE.md#G-01-b1
  await runSeedRecipe(variant.id);
  try {
    // body
  } finally {
    await cleanup(variant.id);
  }
});

test.each(variants)('G-01-n1 — unauthorized', async ({ page }, variant) => {
  // vg-edge-case: G-01-n1
  await runSeedRecipe('G-01-n1');
  try {
    // body
  } finally {
    await cleanup('G-01-n1');
  }
});
""", encoding="utf-8")
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [{"path": str(spec_file), "goal_id": "G-01"}]}),
        encoding="utf-8",
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert r.returncode == 0, f"expected PASS: stdout={r.stdout}\nstderr={r.stderr}"


def test_validator_fails_when_binding_missing(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": {"G-01": {"edge_cases": [{"kind": "boundary"}]}}}),
        encoding="utf-8",
    )
    spec_dir = tmp_path / "tests"
    spec_dir.mkdir()
    # Variant id in spec but NO runSeedRecipe / cleanup
    (spec_dir / "G-01.spec.ts").write_text(
        "test('G-01-b1 — boundary', async ({ page }) => { /* no seed */ });\n",
        encoding="utf-8",
    )
    (phase_dir / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [{"path": str(spec_dir / "G-01.spec.ts"), "goal_id": "G-01"}]}),
        encoding="utf-8",
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert r.returncode != 0


def test_test_spec_invokes_seed_binding_validator():
    body = TEST_SPEC.read_text(encoding="utf-8")
    assert "verify-spec-seed-binding.py" in body
    assert "--allow-seed-binding-shortfall" in body


def test_mirrors_in_sync():
    assert DEL.read_text(encoding="utf-8") == DEL_MIRROR.read_text(encoding="utf-8")
    assert TEST_SPEC.read_text(encoding="utf-8") == TEST_SPEC_MIRROR.read_text(encoding="utf-8")
