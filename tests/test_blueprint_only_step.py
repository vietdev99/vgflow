"""Task 38 — verify `/vg:blueprint <phase> --only=<step>` flag parses + skips
non-named steps. Codex round-2 Amendment D scope.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BP_MD = REPO / "commands/vg/blueprint.md"

VALID_STEP_NAMES = {"fe-contracts", "rcrurdr-invariants", "workflows", "lens-walk", "edge-cases"}


def test_blueprint_argument_hint_declares_only_flag() -> None:
    text = BP_MD.read_text(encoding="utf-8")
    # Frontmatter argument-hint must mention --only=<step>
    m = re.search(r"^argument-hint:\s*(.+)$", text, re.MULTILINE)
    assert m, "blueprint.md frontmatter missing argument-hint"
    hint = m.group(1)
    assert "--only=" in hint, f"argument-hint must declare --only=<step>: {hint}"


def test_blueprint_md_documents_only_step_dispatch() -> None:
    """The slim entry must contain a parse-and-dispatch block for --only."""
    text = BP_MD.read_text(encoding="utf-8")
    assert "--only=" in text
    # All valid step names must be enumerated in the slim entry's only-step list
    only_block_match = re.search(r"<only-step-list>(.+?)</only-step-list>", text, re.DOTALL)
    assert only_block_match, "blueprint.md must wrap valid step list in <only-step-list>...</only-step-list>"
    enumerated = only_block_match.group(1)
    for name in VALID_STEP_NAMES:
        assert name in enumerated, f"missing valid step name '{name}' in <only-step-list>"


def test_blueprint_md_rejects_unknown_only_step_name() -> None:
    """The slim entry must instruct rejection for unknown --only=<name> with explicit error."""
    text = BP_MD.read_text(encoding="utf-8")
    # Must contain a sentence describing rejection of unknown values
    pattern = r"--only.+(?:unknown|invalid|not in).{0,80}error"
    assert re.search(pattern, text, re.IGNORECASE | re.DOTALL), \
        "blueprint.md must specify error behavior for unknown --only=<step> value"
