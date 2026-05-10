"""v2.71.0 T4 — update-modes split."""
from pathlib import Path
import re


def test_update_modes_subfile_exists():
    p = Path("commands/vg/_shared/project/update-modes.md")
    assert p.exists()


def test_update_modes_subfile_contains_extracted_steps():
    body = Path("commands/vg/_shared/project/update-modes.md").read_text(encoding="utf-8")
    assert '<step name="5_mode_update">' in body
    assert '<step name="6_mode_milestone">' in body
    assert '<step name="7_mode_rewrite">' in body


def test_project_md_routes_to_update_modes_subfile():
    body = Path("commands/vg/project.md").read_text(encoding="utf-8")
    assert "_shared/project/update-modes.md" in body


def test_update_modes_subfile_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/project/update-modes.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/project/update-modes.md").read_bytes()
    assert canonical == mirror


def test_project_md_mirror_byte_identity():
    canonical = Path("commands/vg/project.md").read_bytes()
    mirror = Path(".claude/commands/vg/project.md").read_bytes()
    assert canonical == mirror


def test_extracted_steps_no_longer_in_project_md_body():
    body = Path("commands/vg/project.md").read_text(encoding="utf-8")
    # Step XML bodies should be gone (slim routing reference only)
    for step_name in ("5_mode_update", "6_mode_milestone", "7_mode_rewrite"):
        pattern = rf'<step name="{step_name}">.*?</step>'
        matches = re.findall(pattern, body, re.DOTALL)
        for m in matches:
            assert len(m) < 500, (
                f"step {step_name} body should be replaced by slim routing reference"
            )
