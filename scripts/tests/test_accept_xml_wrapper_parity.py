"""R6 Task 4 — every accept must_touch_marker has <step name="..."> XML wrapper.

Cross-pilot test parity: review.md has full XML wrappers (R3 pilot enforced via
test_review_slim_size.py::test_review_md_step_blocks_in_refs_match_backup).
Accept should match this convention.
"""
from __future__ import annotations
import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCEPT_MD = REPO_ROOT / "commands" / "vg" / "accept.md"
ACCEPT_REFS_DIR = REPO_ROOT / "commands" / "vg" / "_shared" / "accept"


def _extract_must_touch_markers() -> list[str]:
    """Parse accept.md frontmatter for must_touch_markers list."""
    text = ACCEPT_MD.read_text(encoding="utf-8")
    m = re.search(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if not m:
        return []
    fm = m.group(1)
    block = re.search(
        r'must_touch_markers:\n(.*?)(?=\n  [a-z_]+:|\nmust_emit_telemetry:|\Z)',
        fm,
        re.DOTALL,
    )
    if not block:
        return []
    markers = []
    for line in block.group(1).splitlines():
        m2 = re.search(r'-\s*(?:name:\s*)?"([^"]+)"', line)
        if m2:
            markers.append(m2.group(1))
    return markers


def _all_step_blocks_in_refs() -> set[str]:
    """Collect all <step name="..."> XML wrappers across accept refs."""
    found: set[str] = set()
    for path in ACCEPT_REFS_DIR.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        found |= {m.group(1) for m in re.finditer(r'<step\s+name="([^"]+)"', text)}
    return found


@pytest.mark.parametrize("marker", _extract_must_touch_markers())
def test_accept_marker_has_xml_wrapper(marker: str) -> None:
    """Every accept must_touch_marker must have <step name="..."> wrapper in some ref."""
    found = _all_step_blocks_in_refs()
    assert marker in found, (
        f"Accept marker '{marker}' declared in must_touch_markers but no "
        f"<step name=\"{marker}\"> wrapper found in commands/vg/_shared/accept/. "
        f"Cross-pilot test parity (review.md has full XML) requires accept refs "
        f"to wrap each marker body in XML. Available wrappers: {sorted(found)}"
    )
