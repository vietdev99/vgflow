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


def test_blueprint_generates_and_verifies_lifecycle_specs() -> None:
    blueprint = (REPO_ROOT / "commands" / "vg" / "blueprint.md").read_text(encoding="utf-8")
    overview = (REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "contracts-overview.md").read_text(encoding="utf-8")
    delegation = (REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "contracts-delegation.md").read_text(encoding="utf-8")

    assert "${PHASE_DIR}/LIFECYCLE-SPECS.json" in blueprint
    assert "generate-lifecycle-specs.py" in overview
    assert "verify-lifecycle-spec-depth.py" in overview
    assert "LIFECYCLE-SPECS.json" in delegation
    assert "Common formula" in delegation
    assert "fixture_dag" in delegation
    assert "artifact_capture" in delegation
    assert "read_after_delete" in delegation


def test_codegen_consumes_lifecycle_specs() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md").read_text(encoding="utf-8")
    mirror = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md").read_text(encoding="utf-8")

    assert body == mirror
    assert "@${PHASE_DIR}/LIFECYCLE-SPECS.json" in body
    assert "generate-lifecycle-specs.py" in body
    assert "formula.stages" in body
    assert "Create fixtures in `fixture_dag` order" in body
    assert "Register `cleanup[]`" in body

def test_curated_codex_skills_reference_lifecycle_generator() -> None:
    vg_test = (REPO_ROOT / "codex-skills" / "vg-test" / "SKILL.md").read_text(encoding="utf-8")
    vg_blueprint = (REPO_ROOT / "codex-skills" / "vg-blueprint" / "SKILL.md").read_text(encoding="utf-8")

    assert "generate-lifecycle-specs.py --phase ${PHASE_NUMBER}" in vg_test
    assert "verify-lifecycle-spec-depth.py" in vg_test
    assert "formula.stages" in vg_test
    assert "generate-lifecycle-specs.py --phase ${PHASE_NUMBER}" in vg_blueprint
    assert "verify-lifecycle-spec-depth.py" in vg_blueprint
    assert "fixture_dag" in vg_blueprint
    assert "artifact_capture[]" in vg_blueprint
