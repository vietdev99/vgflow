"""Tier 1 #107: Verify CLAUDE.md documents --exclude-dynamic-system-prompt-sections."""
from pathlib import Path

CLAUDE_MD = Path(__file__).resolve().parents[2] / "CLAUDE.md"


def test_claude_md_recommends_exclude_dynamic_flag():
    body = CLAUDE_MD.read_text()
    assert "--exclude-dynamic" in body, (
        "CLAUDE.md must recommend --exclude-dynamic-system-prompt-sections "
        "for cache reuse (Tier 1 #107)"
    )


def test_claude_md_explains_why():
    body = CLAUDE_MD.read_text().lower()
    assert "cache" in body or "token" in body, (
        "CLAUDE.md must explain WHY (cache reuse / token saving)"
    )
