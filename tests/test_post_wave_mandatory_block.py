"""v2.61.0 L3: Entry MANDATORY post-wave continuation block in build/test/accept/deploy."""
import re
from pathlib import Path

from conftest import read_command_full

REPO_ROOT = Path(__file__).resolve().parents[1]

COMMANDS = ["build", "test", "accept", "deploy"]


def test_each_command_has_mandatory_block():
    for cmd in COMMANDS:
        body = read_command_full(cmd)
        assert "MANDATORY POST-WAVE CONTINUATION" in body, (
            f"commands/vg/{cmd}.md must have MANDATORY POST-WAVE CONTINUATION block (v2.61.0 L3)"
        )


def test_mandatory_block_cites_meta_skill():
    for cmd in COMMANDS:
        body = read_command_full(cmd)
        # MANDATORY block should reference vg-meta-skill or Post-wave continuation Red Flags
        m = re.search(
            r"MANDATORY POST-WAVE CONTINUATION.*?(?=^##|\Z)",
            body, re.DOTALL | re.MULTILINE,
        )
        assert m, f"{cmd}: MANDATORY block not findable as section"
        section = m.group(0)
        assert ("vg-meta-skill" in section or "Post-wave continuation" in section), (
            f"{cmd}: MANDATORY block must cite the primer Red Flag for cross-reference"
        )


def test_mandatory_block_warns_against_ending_turn():
    for cmd in COMMANDS:
        body = read_command_full(cmd)
        m = re.search(
            r"MANDATORY POST-WAVE CONTINUATION.*?(?=^##|\Z)",
            body, re.DOTALL | re.MULTILINE,
        )
        assert m
        assert "Do NOT end the turn" in m.group(0) or "do not end the turn" in m.group(0).lower(), (
            f"{cmd}: MANDATORY block must explicitly warn against ending turn"
        )


def test_mirrors_byte_identical():
    for cmd in COMMANDS:
        canonical = REPO_ROOT / "commands" / "vg" / f"{cmd}.md"
        mirror = REPO_ROOT / ".claude" / "commands" / "vg" / f"{cmd}.md"
        if not mirror.exists():
            continue
        assert canonical.read_bytes() == mirror.read_bytes(), (
            f"{cmd}.md canonical/mirror drift"
        )
