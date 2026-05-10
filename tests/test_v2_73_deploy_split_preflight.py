"""v2.73.0 T1 — deploy.md preflight section split."""
from pathlib import Path


def test_preflight_subfile_exists():
    p = Path("commands/vg/_shared/deploy/preflight.md")
    assert p.exists(), "v2.73.0 T1 must create _shared/deploy/preflight.md"


def test_preflight_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/deploy/preflight.md").read_text(encoding="utf-8")
    expected_steps = [
        "0_parse_and_validate",
        "0a_env_select_and_confirm",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"preflight.md missing step tag: {s}"


def test_deploy_md_routes_to_preflight_subfile():
    body = Path("commands/vg/deploy.md").read_text(encoding="utf-8")
    assert "_shared/deploy/preflight.md" in body, \
        "deploy.md must reference _shared/deploy/preflight.md after T1 split"


def test_deploy_md_no_longer_contains_extracted_step_bodies():
    """Verify extracted preflight step <step name=...> tags are gone from deploy.md."""
    body = Path("commands/vg/deploy.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="0_parse_and_validate">',
        '<step name="0a_env_select_and_confirm">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"deploy.md still contains extracted step tag {tag} (should live in _shared/deploy/preflight.md)"


def test_preflight_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/deploy/preflight.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/deploy/preflight.md").read_bytes()
    assert canonical == mirror, "_shared/deploy/preflight.md mirrors must be byte-identical"


def test_deploy_md_mirror_byte_identity():
    canonical = Path("commands/vg/deploy.md").read_bytes()
    mirror = Path(".claude/commands/vg/deploy.md").read_bytes()
    assert canonical == mirror, "commands/vg/deploy.md mirrors must be byte-identical"
