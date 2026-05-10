"""v2.70.0 T5 — review.md lens-and-findings section split."""
from pathlib import Path


def test_lens_findings_subfile_exists():
    p = Path("commands/vg/_shared/review/lens-and-findings.md")
    assert p.exists(), "v2.70.0 T5 must create _shared/review/lens-and-findings.md"


def test_lens_findings_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/review/lens-and-findings.md").read_text(encoding="utf-8")
    expected_steps = [
        "phase2_5_recursive_lens_probe",
        "phase2b_collect_merge",
        "phase2c_enrich_test_goals",
        "phase2c_pre_dispatch_gates",
        "phase2d_crud_roundtrip_dispatch",
        "phase2e_findings_merge",
        "phase2e_post_challenge",
        "phase2f_route_auto_fix",
    ]
    for s in expected_steps:
        assert s in body, f"lens-and-findings.md missing step: {s}"


def test_review_md_routes_to_lens_findings_subfile():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert "_shared/review/lens-and-findings.md" in body, \
        "review.md must reference _shared/review/lens-and-findings.md after T5 split"


def test_review_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted lens-and-findings step <step name=...> tags are gone from review.md."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="phase2_5_recursive_lens_probe"',
        '<step name="phase2b_collect_merge"',
        '<step name="phase2c_enrich_test_goals"',
        '<step name="phase2c_pre_dispatch_gates"',
        '<step name="phase2d_crud_roundtrip_dispatch"',
        '<step name="phase2e_findings_merge"',
        '<step name="phase2e_post_challenge"',
        '<step name="phase2f_route_auto_fix"',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"review.md still contains extracted step tag {tag} (should live in _shared/review/lens-and-findings.md)"


def test_lens_findings_subfile_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/review/lens-and-findings.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/review/lens-and-findings.md").read_bytes()
    assert canonical == mirror, "_shared/review/lens-and-findings.md mirrors must be byte-identical"


def test_review_md_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror, "commands/vg/review.md mirrors must be byte-identical"
