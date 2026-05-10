"""v2.71.0 T3 — first-time-rounds split."""
from pathlib import Path
import re


def test_first_time_subfile_exists():
    p = Path("commands/vg/_shared/project/first-time-rounds.md")
    assert p.exists()


def test_first_time_subfile_contains_step_and_rounds():
    body = Path("commands/vg/_shared/project/first-time-rounds.md").read_text(encoding="utf-8")
    assert '<step name="4_mode_first_time">' in body
    for n in range(1, 10):
        assert f"Round {n}" in body, f"Missing Round {n}"


def test_project_md_routes_to_first_time_subfile():
    body = Path("commands/vg/project.md").read_text(encoding="utf-8")
    assert "_shared/project/first-time-rounds.md" in body


def test_first_time_subfile_mirror_byte_identity():
    canonical = Path("commands/vg/_shared/project/first-time-rounds.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/project/first-time-rounds.md").read_bytes()
    assert canonical == mirror


def test_project_md_mirror_byte_identity():
    canonical = Path("commands/vg/project.md").read_bytes()
    mirror = Path(".claude/commands/vg/project.md").read_bytes()
    assert canonical == mirror


def test_extracted_step_no_longer_in_project_md_body():
    body = Path("commands/vg/project.md").read_text(encoding="utf-8")
    # Step XML body should be gone (slim routing reference only)
    # Just check the step body markers are absent
    matches = re.findall(r'<step name="4_mode_first_time">.*?</step>', body, re.DOTALL)
    # Either no match (fully removed) or 1 thin slim wrapper (allowed)
    for m in matches:
        assert len(m) < 500, "step body should be replaced by slim routing reference"
