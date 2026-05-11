from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_lifecycle_validator_registered_and_mirrored() -> None:
    canonical = REPO_ROOT / "scripts" / "validators" / "verify-lifecycle-spec-depth.py"
    mirror = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-lifecycle-spec-depth.py"
    generator = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"
    generator_mirror = REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py"
    registry = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_text(encoding="utf-8")

    assert canonical.exists()
    assert mirror.exists()
    assert generator.exists()
    assert generator_mirror.exists()
    assert canonical.read_bytes() == mirror.read_bytes()
    assert generator.read_bytes() == generator_mirror.read_bytes()
    assert "id: lifecycle-spec-depth" in registry
    assert "verify-lifecycle-spec-depth.py" in registry
    assert "phases_active: [test]" in registry


def test_vg_test_preflight_blocks_missing_lifecycle_specs() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "preflight.md").read_text(encoding="utf-8")
    mirror = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "test" / "preflight.md").read_text(encoding="utf-8")

    assert body == mirror
    assert "generate-lifecycle-specs.py" in body
    assert "--regen-lifecycle-specs" in body
    assert "verify-lifecycle-spec-depth.py" in body
    assert "lifecycle-spec-depth-test.json" in body
    assert "Mutation/multi-actor goals need LIFECYCLE-SPECS.json" in body


def test_post_build_test_spec_generates_and_verifies_lifecycle_specs() -> None:
    command = (REPO_ROOT / "commands" / "vg" / "test-spec.md").read_text(encoding="utf-8")
    mirror = (REPO_ROOT / ".claude" / "commands" / "vg" / "test-spec.md").read_text(encoding="utf-8")

    assert command == mirror
    assert "${PHASE_DIR}/LIFECYCLE-SPECS.json" in command
    assert "${PHASE_DIR}/DEEP-TEST-SPECS.md" in command
    assert "${PHASE_DIR}/TEST-FIXTURE-DAG.json" in command
    assert "${PHASE_DIR}/TEST-EXECUTION-PLAN.json" in command
    assert "${PHASE_DIR}/TEST-SPEC-LOCALIZER/PROMPT.md" in command
    assert "generate-deep-test-specs.py" in command
    assert "verify-deep-test-specs.py" in command
    assert "read_after_delete" in command


def test_codegen_consumes_lifecycle_specs() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md").read_text(encoding="utf-8")
    mirror = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md").read_text(encoding="utf-8")

    assert body == mirror
    assert "@${PHASE_DIR}/LIFECYCLE-SPECS.json" in body
    assert "generate-lifecycle-specs.py" in body
    assert "formula.stages" in body
    assert "Create fixtures in `fixture_dag` order" in body
    assert "Register `cleanup[]`" in body

def test_review_goal_comparison_consumes_lifecycle_specs() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "fix-loop-and-goals.md").read_text(encoding="utf-8")
    mirror = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "review" / "fix-loop-and-goals.md").read_text(encoding="utf-8")
    matrix_merger = (REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "matrix-merger.sh").read_text(encoding="utf-8")
    matrix_merger_mirror = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "lib" / "matrix-merger.sh").read_text(encoding="utf-8")

    assert body == mirror
    assert matrix_merger == matrix_merger_mirror
    assert "Post-build lifecycle contract" in body
    assert "${PHASE_DIR}/LIFECYCLE-SPECS.json" in body
    assert "${PHASE_DIR}/TEST-FIXTURE-DAG.json" in body
    assert "${PHASE_DIR}/TEST-EXECUTION-PLAN.json" in body
    assert "Runner-native phases" in body
    assert "LIFECYCLE-SPECS.json/TEST-FIXTURE-DAG.json/TEST-EXECUTION-PLAN.json" in matrix_merger
    assert "LIFECYCLE_CONTRACTS" in matrix_merger
    assert "--source-inputs" in body
    assert "${PHASE_DIR}/DEEP-TEST-SPECS.md" in body

def test_curated_codex_skills_reference_lifecycle_generator() -> None:
    vg_test = (REPO_ROOT / "codex-skills" / "vg-test" / "SKILL.md").read_text(encoding="utf-8")
    vg_test_spec = (REPO_ROOT / "codex-skills" / "vg-test-spec" / "SKILL.md").read_text(encoding="utf-8")

    assert "generate-lifecycle-specs.py --phase ${PHASE_NUMBER}" in vg_test
    assert "verify-lifecycle-spec-depth.py" in vg_test
    assert "formula.stages" in vg_test
    assert "generate-deep-test-specs.py" in vg_test_spec
    assert "verify-deep-test-specs.py" in vg_test_spec
    assert "TEST-FIXTURE-DAG.json" in vg_test_spec
    assert "TEST-EXECUTION-PLAN.json" in vg_test_spec
