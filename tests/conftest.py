"""v2.75.2 — shared test helpers for slim/_shared command structure.

After v2.71+ refactors split `commands/vg/<cmd>.md` into slim parent +
`commands/vg/_shared/<cmd>/*.md` sub-files, tests that scan parent only miss
extracted content. This conftest exposes `read_command_full(cmd)` which returns
parent text concatenated with all `_shared/<cmd>/*.md` sub-files (sorted), so
content checks remain valid post-split without per-test fixup.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDS_DIR = REPO_ROOT / "commands" / "vg"
SHARED_DIR = COMMANDS_DIR / "_shared"


def read_command_full(cmd: str) -> str:
    """Return slim parent + all _shared/<cmd>/*.md sub-files concatenated.

    Use for content scans (regex, substring) that need to find text regardless
    of whether it lives in slim parent or extracted sub-file. Do NOT use for
    structural checks where location matters (e.g., frontmatter parse).
    """
    parent = (COMMANDS_DIR / f"{cmd}.md").read_text(encoding="utf-8")
    shared = SHARED_DIR / cmd
    if not shared.is_dir():
        return parent
    chunks = [parent]
    for sub in sorted(shared.rglob("*.md")):
        chunks.append(sub.read_text(encoding="utf-8"))
    return "\n\n".join(chunks)
