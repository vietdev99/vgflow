"""v2.65.0 A3 smoke — codex-inline parallel scanner option."""
import re
from pathlib import Path
import pytest


@pytest.fixture
def review_md_text():
    return Path("commands/vg/review.md").read_text(encoding="utf-8")


def test_codex_inline_supports_parallel_codex_spawn(review_md_text):
    """review.md must document codex-spawn parallel branch for codex runtime."""
    assert "codex-spawn.sh --tier scanner" in review_md_text
    # Must reference parallel_workers config knob
    assert "parallel_workers" in review_md_text


def test_mcp_browser_stays_inline_for_codex(review_md_text):
    """MCP/browser actions must NOT be moved to codex-spawn (codex-spawn lacks MCP)."""
    # Look for an explanatory clause
    assert re.search(
        r"MCP.{0,200}main Codex orchestrator|main Codex orchestrator.{0,200}MCP",
        review_md_text, re.DOTALL | re.IGNORECASE
    ), "review.md must explicitly state MCP/browser stays inline for codex-inline"


def test_mirror_byte_identity():
    canonical = Path("commands/vg/review.md").read_bytes()
    mirror = Path(".claude/commands/vg/review.md").read_bytes()
    assert canonical == mirror, "review.md mirrors must be byte-identical"


def test_codex_spawn_haiku_warning_preserved(review_md_text):
    """Must still warn that Haiku model is Claude-only (not for codex-spawn)."""
    # Either "do not ask to spawn Haiku on Codex" OR "Haiku is Claude-only"
    assert re.search(r"Haiku.{0,80}(Claude-only|on Codex)", review_md_text, re.IGNORECASE), \
        "Must preserve warning that Haiku model isn't for codex runtime"
