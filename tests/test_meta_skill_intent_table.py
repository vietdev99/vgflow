"""Task 3 v2.60.0: Intent → Command map in vg-meta-skill.md."""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
META = REPO_ROOT / "scripts" / "hooks" / "vg-meta-skill.md"


def test_intent_section_exists():
    body = META.read_text(encoding="utf-8")
    assert "## Intent → Command map" in body, (
        "vg-meta-skill.md must have Intent → Command map section for v2.60.0"
    )


def test_intent_table_has_minimum_entries():
    body = META.read_text(encoding="utf-8")
    section_match = re.search(
        r"## Intent → Command map.*?(?=^## )",
        body, re.DOTALL | re.MULTILINE,
    )
    assert section_match, "Intent map section not found"
    section = section_match.group(0)
    # Count table rows (lines with `/vg:` AND a pipe)
    rows = [ln for ln in section.split("\n")
            if "/vg:" in ln and ln.count("|") >= 2]
    assert len(rows) >= 12, (
        f"Intent map must have at least 12 entries, found {len(rows)}"
    )


def test_intent_map_covers_core_commands():
    body = META.read_text(encoding="utf-8")
    section_match = re.search(
        r"## Intent → Command map.*?(?=^## )",
        body, re.DOTALL | re.MULTILINE,
    )
    assert section_match
    section = section_match.group(0)
    core = ["/vg:build", "/vg:blueprint", "/vg:specs", "/vg:scope",
            "/vg:review", "/vg:test", "/vg:accept", "/vg:deploy",
            "/vg:debug", "/vg:amend", "/vg:learn"]
    missing = [c for c in core if c not in section]
    assert not missing, f"Intent map missing core commands: {missing}"


def test_intent_map_covers_vietnamese_phrases():
    """Project user is Vietnamese — table must include vi triggers."""
    body = META.read_text(encoding="utf-8")
    vi_phrases = ["lập plan", "viết code", "rà", "kiểm thử", "đẩy lên", "tiến độ"]
    found = [p for p in vi_phrases if p in body]
    assert len(found) >= 3, (
        f"Intent map must include Vietnamese triggers; found only {found}"
    )


def test_intent_red_flags_section():
    body = META.read_text(encoding="utf-8")
    assert "## Red Flags — Intent recognition" in body, (
        "Must have dedicated Red Flags table for intent skipping"
    )


def test_intent_red_flags_has_examples():
    body = META.read_text(encoding="utf-8")
    section_match = re.search(
        r"## Red Flags — Intent recognition.*?(?=^## |\Z)",
        body, re.DOTALL | re.MULTILINE,
    )
    assert section_match
    section = section_match.group(0)
    # At least 4 rationalization examples
    rows = [ln for ln in section.split("\n") if "NO —" in ln or "NO -" in ln]
    assert len(rows) >= 4, f"Need at least 4 Red Flag rows, found {len(rows)}"


def test_meta_skill_mirror_byte_identical():
    canonical = REPO_ROOT / "scripts" / "hooks" / "vg-meta-skill.md"
    mirror = REPO_ROOT / ".claude" / "scripts" / "hooks" / "vg-meta-skill.md"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_meta_skill_under_size_budget():
    """Primer is injected on every SessionStart — keep it tight."""
    body = META.read_text(encoding="utf-8")
    assert len(body) < 20000, (
        f"vg-meta-skill.md exceeded 20KB budget: {len(body)} chars"
    )
