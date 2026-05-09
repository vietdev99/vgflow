"""v2.61.0 L1: Post-wave continuation Red Flags in vg-meta-skill.md."""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
META = REPO_ROOT / "scripts" / "hooks" / "vg-meta-skill.md"


def test_post_wave_red_flags_section_exists():
    body = META.read_text(encoding="utf-8")
    assert "## Red Flags — Post-wave continuation" in body, (
        "v2.61.0 L1: vg-meta-skill.md must have post-wave Red Flags section"
    )


def test_post_wave_section_covers_4_commands():
    body = META.read_text(encoding="utf-8")
    section_match = re.search(
        r"## Red Flags — Post-wave continuation.*?(?=^## )",
        body, re.DOTALL | re.MULTILINE,
    )
    assert section_match, "Post-wave section not found"
    section = section_match.group(0)
    # Must reference all 4 commands with wave-spawn pattern
    for cmd in ["/vg:build", "/vg:test", "/vg:accept", "/vg:deploy"]:
        assert cmd in section, f"Post-wave Red Flags must mention {cmd}"


def test_post_wave_section_has_min_rationalizations():
    body = META.read_text(encoding="utf-8")
    section_match = re.search(
        r"## Red Flags — Post-wave continuation.*?(?=^## )",
        body, re.DOTALL | re.MULTILINE,
    )
    assert section_match
    section = section_match.group(0)
    # Count "NO —" rows (each is a rationalization counter)
    rows = [ln for ln in section.split("\n") if "NO —" in ln or "NO -" in ln]
    assert len(rows) >= 5, f"Need at least 5 rationalizations, found {len(rows)}"


def test_post_wave_section_cites_is_final_wave():
    body = META.read_text(encoding="utf-8")
    section_match = re.search(
        r"## Red Flags — Post-wave continuation.*?(?=^## )",
        body, re.DOTALL | re.MULTILINE,
    )
    assert section_match
    section = section_match.group(0)
    assert "is-final-wave" in section or "IS_FINAL_WAVE" in section, (
        "Post-wave Red Flags must cite the IS_FINAL_WAVE check pattern"
    )


def test_meta_skill_mirror_byte_identical():
    canonical = REPO_ROOT / "scripts" / "hooks" / "vg-meta-skill.md"
    mirror = REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-meta-skill.md"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_meta_skill_under_size_budget():
    body = META.read_text(encoding="utf-8")
    assert len(body) < 20000, (
        f"vg-meta-skill.md exceeded 20KB budget: {len(body)} chars"
    )
