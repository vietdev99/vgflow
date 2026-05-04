import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENTRY = REPO / "commands/vg/build.md"


def test_must_write_includes_per_task_split():
    """UX baseline Req 1 — build runtime_contract must enforce BUILD-LOG split."""
    text = ENTRY.read_text()
    fm_m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert fm_m, "build.md missing frontmatter"
    fm = fm_m.group(1)
    # Layer 1 — per-task glob
    assert "BUILD-LOG/task-*.md" in fm, "must_write missing BUILD-LOG/task-*.md (Layer 1)"
    assert "glob_min_count" in fm, "must_write missing glob_min_count assertion"
    # Layer 2 — index
    assert "BUILD-LOG/index.md" in fm, "must_write missing BUILD-LOG/index.md (Layer 2)"
    # Layer 3 — flat concat
    assert "BUILD-LOG.md" in fm, "must_write missing BUILD-LOG.md (Layer 3 concat)"
