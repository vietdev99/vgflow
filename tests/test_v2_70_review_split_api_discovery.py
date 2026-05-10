"""v2.70.0 T4 — review.md api-and-discovery section split."""
from pathlib import Path


def test_api_discovery_subfile_exists():
    p = Path("commands/vg/_shared/review/api-and-discovery.md")
    assert p.exists(), "v2.70.0 T4 must create _shared/review/api-and-discovery.md"


def test_api_discovery_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/review/api-and-discovery.md").read_text(encoding="utf-8")
    expected_steps = [
        "phase2a_api_contract_probe",
        "phase2_browser_discovery",
    ]
    for s in expected_steps:
        assert s in body, f"api-and-discovery.md missing step: {s}"


def test_review_md_routes_to_api_discovery_subfile():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert "_shared/review/api-and-discovery.md" in body, \
        "review.md must reference _shared/review/api-and-discovery.md after T4 split"


def test_review_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted api-and-discovery step <step name=...> tags are gone from review.md."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="phase2a_api_contract_probe"',
        '<step name="phase2_browser_discovery"',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"review.md still contains extracted step tag {tag} (should live in _shared/review/api-and-discovery.md)"


def test_api_discovery_subfile_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/review/api-and-discovery.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/review/api-and-discovery.md").read_bytes()
    assert canonical == mirror, "_shared/review/api-and-discovery.md mirrors must be byte-identical"


def test_review_md_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror, "commands/vg/review.md mirrors must be byte-identical"
