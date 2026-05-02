"""R3.5 Roam Pilot — discovery ref absorbs Phase F Task 30 (vg-load --index)."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DISCOVERY = REPO / "commands/vg/_shared/roam/discovery.md"


def test_discovery_ref_uses_vg_load():
    text = DISCOVERY.read_text()
    assert "vg-load" in text, "discovery.md must reference vg-load"
    assert "--index" in text, "discovery.md must use vg-load --index for surface enumeration"


def test_discovery_ref_does_not_flat_read_plan_md():
    text = DISCOVERY.read_text()
    # Allow narrative/cautionary mentions (e.g. "DO NOT cat PLAN.md") but
    # forbid actual instructions to flat-read.
    # Strategy: check for `cat ${PHASE_DIR}/PLAN.md` or `cat ... PLAN.md` in
    # active code blocks. Cautionary lines containing "DO NOT" are fine.
    for line in text.splitlines():
        stripped = line.strip()
        # Skip comment / cautionary lines
        if "DO NOT" in stripped or stripped.startswith("#") or stripped.startswith(">"):
            continue
        # Active flat-read patterns
        assert not re.search(r'^\s*cat\s+\S*PLAN\.md', line), (
            f"discovery.md must not contain `cat ... PLAN.md` outside cautionary lines: {line!r}"
        )
        # Read tool invocation (Markdown documenting `Read PLAN.md` is OK as
        # a description but shouldn't appear inside code blocks as an
        # instruction). Heuristic: backtick-wrapped Read call.
        assert not re.search(r'`Read\s+\S*PLAN\.md`', line), (
            f"discovery.md must not instruct `Read PLAN.md` flat: {line!r}"
        )


def test_discovery_ref_keeps_context_runtime_map_flat():
    """CONTEXT.md and RUNTIME-MAP.md remain KEEP-FLAT per spec — verify the ref says so."""
    text = DISCOVERY.read_text()
    assert "CONTEXT.md" in text and "RUNTIME-MAP.md" in text, (
        "discovery.md must reference both small-doc artifacts that stay flat"
    )
    assert "KEEP-FLAT" in text, (
        "discovery.md must declare CONTEXT.md / RUNTIME-MAP.md as KEEP-FLAT"
    )
