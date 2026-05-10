"""v2.70.0 T2 — review.md phase-p-variants section split."""
from pathlib import Path


def test_phase_p_variants_subfile_exists():
    p = Path("commands/vg/_shared/review/phase-p-variants.md")
    assert p.exists(), "v2.70.0 T2 must create _shared/review/phase-p-variants.md"


def test_phase_p_variants_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/review/phase-p-variants.md").read_text(encoding="utf-8")
    expected_steps = [
        "phase_profile_branch",
        "phaseP_infra_smoke",
        "phaseP_delta",
        "phaseP_regression",
        "phaseP_schema_verify",
        "phaseP_link_check",
    ]
    for s in expected_steps:
        assert s in body, f"phase-p-variants.md missing step: {s}"


def test_review_md_routes_to_phase_p_variants_subfile():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert "_shared/review/phase-p-variants.md" in body, \
        "review.md must reference _shared/review/phase-p-variants.md after T2 split"


def test_review_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted phase-p step <step name=...> tags are gone from review.md."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="phase_profile_branch">',
        '<step name="phaseP_infra_smoke"',
        '<step name="phaseP_delta"',
        '<step name="phaseP_regression"',
        '<step name="phaseP_schema_verify"',
        '<step name="phaseP_link_check"',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"review.md still contains extracted step tag {tag} (should live in _shared/review/phase-p-variants.md)"


def test_phase_p_variants_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/review/phase-p-variants.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/review/phase-p-variants.md").read_bytes()
    assert canonical == mirror, "_shared/review/phase-p-variants.md mirrors must be byte-identical"


def test_review_md_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror, "commands/vg/review.md mirrors must be byte-identical"
