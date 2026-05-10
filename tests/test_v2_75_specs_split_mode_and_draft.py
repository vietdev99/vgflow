"""v2.75.0 T2 — specs.md mode-and-draft section split."""
from pathlib import Path


def test_mode_and_draft_subfile_exists():
    p = Path("commands/vg/_shared/specs/mode-and-draft.md")
    assert p.exists(), "v2.75.0 T2 must create _shared/specs/mode-and-draft.md"


def test_mode_and_draft_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/specs/mode-and-draft.md").read_text(encoding="utf-8")
    expected_steps = [
        "choose_mode",
        "guided_questions",
        "generate_draft",
    ]
    for s in expected_steps:
        assert f'<step name="{s}">' in body, f"mode-and-draft.md missing step tag: {s}"


def test_specs_md_routes_to_mode_and_draft_subfile():
    body = Path("commands/vg/specs.md").read_text(encoding="utf-8")
    assert "_shared/specs/mode-and-draft.md" in body, \
        "specs.md must reference _shared/specs/mode-and-draft.md after T2 split"


def test_specs_md_no_longer_contains_extracted_step_bodies():
    body = Path("commands/vg/specs.md").read_text(encoding="utf-8")
    extracted_step_tags = [
        '<step name="choose_mode">',
        '<step name="guided_questions">',
        '<step name="generate_draft">',
    ]
    for tag in extracted_step_tags:
        assert tag not in body, \
            f"specs.md still contains extracted step tag {tag} (should live in _shared/specs/mode-and-draft.md)"


def test_mode_and_draft_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/specs/mode-and-draft.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/specs/mode-and-draft.md").read_bytes()
    assert canonical == mirror, "_shared/specs/mode-and-draft.md mirrors must be byte-identical"


def test_specs_md_mirror_byte_identity():
    canonical = Path("commands/vg/specs.md").read_bytes()
    mirror = Path(".claude/commands/vg/specs.md").read_bytes()
    assert canonical == mirror, "commands/vg/specs.md mirrors must be byte-identical"
