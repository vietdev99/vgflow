"""v2.70.0 T1 — review.md preflight section split."""
from pathlib import Path


def test_preflight_subfile_exists():
    p = Path("commands/vg/_shared/review/preflight.md")
    assert p.exists(), "v2.70.0 T1 must create _shared/review/preflight.md"


def test_preflight_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/review/preflight.md").read_text(encoding="utf-8")
    expected_steps = [
        "00_gate_integrity_precheck",
        "00_session_lifecycle",
        "0_parse_and_validate",
        "0a_env_mode_gate",
        "0b_goal_coverage_gate",
        "0c_telemetry_suggestions",
        "create_task_tracker",
    ]
    for s in expected_steps:
        assert s in body, f"preflight.md missing step: {s}"


def test_review_md_routes_to_preflight_subfile():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert "_shared/review/preflight.md" in body, \
        "review.md must reference _shared/review/preflight.md after T1 split"


def test_review_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted preflight step <step name=...> tags are gone from review.md."""
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="00_gate_integrity_precheck">',
        '<step name="00_session_lifecycle">',
        '<step name="0_parse_and_validate">',
        '<step name="0a_env_mode_gate">',
        '<step name="0b_goal_coverage_gate">',
        '<step name="0c_telemetry_suggestions">',
        '<step name="create_task_tracker">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"review.md still contains extracted step tag {tag} (should live in _shared/review/preflight.md)"


def test_preflight_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/review/preflight.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/review/preflight.md").read_bytes()
    assert canonical == mirror, "_shared/review/preflight.md mirrors must be byte-identical"


def test_review_md_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror, "commands/vg/review.md mirrors must be byte-identical"
