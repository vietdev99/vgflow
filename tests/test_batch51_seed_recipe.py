"""tests/test_batch51_seed_recipe.py — Batch 51.

L4 seed contract per variant_id. Generator derives SEED-RECIPE.md from
LIFECYCLE-SPECS edge_cases[] + negative_specs[]. Validator enforces 1:1
mapping. test-spec.md wires generator + validator.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "scripts" / "generate-seed-recipes.py"
GEN_MIRROR = REPO / ".claude" / "scripts" / "generate-seed-recipes.py"
VAL = REPO / "scripts" / "validators" / "verify-seed-recipe-coverage.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-seed-recipe-coverage.py"
TEST_SPEC = REPO / "commands" / "vg" / "test-spec.md"
TEST_SPEC_MIRROR = REPO / ".claude" / "commands" / "vg" / "test-spec.md"


def test_scripts_exist_mirrored():
    for src, mir in [(GEN, GEN_MIRROR), (VAL, VAL_MIRROR)]:
        assert src.is_file() and mir.is_file()
        assert src.read_text(encoding="utf-8") == mir.read_text(encoding="utf-8")


def test_generator_emits_recipes_from_lifecycle(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    lifecycle = {
        "goals": {
            "G-01": {
                "title": "Create site",
                "edge_cases": [
                    {"kind": "boundary", "label": "max"},
                    {"kind": "unicode_special", "label": "emoji"},
                ],
                "negative_specs": [
                    {"kind": "unauthorized_401", "expected_status": 401},
                    {"kind": "validation_422", "expected_status": 422},
                ],
            },
        }
    }
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps(lifecycle), encoding="utf-8")
    r = subprocess.run(
        ["python", str(GEN), "--phase", "7", "--phase-dir", str(phase_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    recipe = phase_dir / "SEED-RECIPE.md"
    assert recipe.is_file()
    body = recipe.read_text(encoding="utf-8")
    # Edge variant_ids
    assert "variant_id: G-01-b1" in body  # boundary
    assert "variant_id: G-01-u2" in body  # unicode_special
    # Negative variant_ids (n prefix)
    assert "variant_id: G-01-n1" in body
    assert "variant_id: G-01-n2" in body
    # Boundary recipe has expected template
    assert "boundary value" in body
    assert "requires_state" in body
    assert "seed_action" in body
    assert "cleanup" in body
    assert "idempotent" in body
    # 401 recipe uses clearCookies pattern
    assert "clearCookies" in body or "unauthenticated" in body


def test_validator_passes_when_all_recipes_present(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({
            "goals": {
                "G-01": {
                    "edge_cases": [{"kind": "boundary"}],
                    "negative_specs": [{"kind": "unauthorized_401"}],
                }
            }
        }),
        encoding="utf-8",
    )
    subprocess.run(["python", str(GEN), "--phase", "7", "--phase-dir", str(phase_dir)],
                   capture_output=True, text=True)
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir),
         "--strict", "--allow-placeholders"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"expected PASS: {r.stderr}"


def test_validator_fails_when_recipe_missing(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": {"G-01": {"edge_cases": [{"kind": "boundary"}]}}}),
        encoding="utf-8",
    )
    (phase_dir / "SEED-RECIPE.md").write_text("# Empty\n", encoding="utf-8")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "G-01-b1" in r.stderr


def test_validator_allow_uncovered_skip(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": {"G-01": {"edge_cases": [{"kind": "boundary"}]}}}),
        encoding="utf-8",
    )
    (phase_dir / "SEED-RECIPE.md").write_text("# Empty\n", encoding="utf-8")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(phase_dir),
         "--strict", "--allow-uncovered", "G-01-b1"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0


def test_test_spec_wires_seed_chain():
    body = TEST_SPEC.read_text(encoding="utf-8")
    assert "generate-seed-recipes.py" in body, "must invoke generator"
    assert "verify-seed-recipe-coverage.py" in body, "must invoke validator"
    assert "--allow-seed-shortfall" in body, "must support escape hatch"


def test_mirror_in_sync():
    assert TEST_SPEC.read_text(encoding="utf-8") == TEST_SPEC_MIRROR.read_text(encoding="utf-8")
