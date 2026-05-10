from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_lifecycle_validator_registered_and_mirrored() -> None:
    canonical = REPO_ROOT / "scripts" / "validators" / "verify-lifecycle-spec-depth.py"
    mirror = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-lifecycle-spec-depth.py"
    registry = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_text(encoding="utf-8")

    assert canonical.exists()
    assert mirror.exists()
    assert canonical.read_bytes() == mirror.read_bytes()
    assert "id: lifecycle-spec-depth" in registry
    assert "verify-lifecycle-spec-depth.py" in registry
    assert "phases_active: [test]" in registry


def test_vg_test_preflight_blocks_missing_lifecycle_specs() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "preflight.md").read_text(encoding="utf-8")
    mirror = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "test" / "preflight.md").read_text(encoding="utf-8")

    assert body == mirror
    assert "verify-lifecycle-spec-depth.py" in body
    assert "lifecycle-spec-depth-test.json" in body
    assert "Mutation/multi-actor goals need LIFECYCLE-SPECS.json" in body


def test_blueprint_generates_and_verifies_lifecycle_specs() -> None:
    blueprint = (REPO_ROOT / "commands" / "vg" / "blueprint.md").read_text(encoding="utf-8")
    overview = (REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "contracts-overview.md").read_text(encoding="utf-8")
    delegation = (REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "contracts-delegation.md").read_text(encoding="utf-8")

    assert "${PHASE_DIR}/LIFECYCLE-SPECS.json" in blueprint
    assert "verify-lifecycle-spec-depth.py" in overview
    assert "LIFECYCLE-SPECS.json" in delegation
    assert "fixture_dag" in delegation
    assert "artifact_capture" in delegation
    assert "read_after_delete" in delegation


def test_codegen_consumes_lifecycle_specs() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md").read_text(encoding="utf-8")
    mirror = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md").read_text(encoding="utf-8")

    assert body == mirror
    assert "@${PHASE_DIR}/LIFECYCLE-SPECS.json" in body
    assert "Create fixtures in `fixture_dag` order" in body
    assert "Register `cleanup[]`" in body
