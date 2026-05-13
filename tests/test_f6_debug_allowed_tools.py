"""tests/test_f6_debug_allowed_tools.py — F6 debug SlashCommand allowed."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
DEBUG = REPO / "commands" / "vg" / "debug.md"


def test_debug_allowed_tools_includes_slashcommand():
    body = DEBUG.read_text(encoding="utf-8")
    # Find allowed-tools line in frontmatter
    fm_end = body.find("\n---\n", 4)
    fm = body[:fm_end] if fm_end > 0 else body[:2000]
    assert "SlashCommand" in fm, (
        "F6: debug.md frontmatter allowed-tools must include SlashCommand "
        "so the spec-gap auto-route to /vg:amend can actually execute"
    )
