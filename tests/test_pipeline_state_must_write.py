"""P0-2: PIPELINE-STATE.json must be in build's must_write contract.

Without this, orchestrator's run-complete doesn't enforce that build
actually wrote the file. After session compact, file can vanish silently
and downstream /vg:deploy /vg:review /vg:test /vg:accept fail with
cryptic 'missing prior outputs' errors.

Audit references: agent + codex confirmed P0-2 (cross-cutting #1).
"""
import re
from pathlib import Path

CANONICAL = Path("commands/vg/build.md")
MIRROR = Path(".claude/commands/vg/build.md")


def _extract_must_write(body: str) -> str:
    """Pull the must_write block from runtime_contract."""
    # runtime_contract is YAML at top of file (frontmatter or labeled block)
    m = re.search(r"must_write:(.*?)(?=^\s{2}must_touch_markers:|^\s{2}must_emit_telemetry:|^---|\Z)",
                  body, flags=re.DOTALL | re.MULTILINE)
    assert m, f"must_write block not found in {body[:500]}"
    return m.group(1)


def test_pipeline_state_in_build_must_write():
    body = CANONICAL.read_text(encoding="utf-8")
    block = _extract_must_write(body)
    assert "PIPELINE-STATE.json" in block, (
        "PIPELINE-STATE.json must be declared in build's must_write contract. "
        "Without it, downstream gates lose visibility on cross-command state."
    )


def test_pipeline_state_has_content_section_check():
    body = CANONICAL.read_text(encoding="utf-8")
    block = _extract_must_write(body)
    # Find the PIPELINE-STATE entry and its content_required_sections
    m = re.search(
        r"path:\s*[\"']?\$\{PHASE_DIR\}/PIPELINE-STATE\.json[\"']?\s*\n"
        r".*?content_required_sections:\s*\[([^\]]+)\]",
        block, flags=re.DOTALL,
    )
    assert m, "PIPELINE-STATE.json entry must have content_required_sections"
    sections = m.group(1)
    assert "steps.build.status" in sections, (
        "must require steps.build.status field present in JSON"
    )
    assert "built-complete" in sections, (
        "must require status value 'built-complete' (aligned with Task 1 P0-1 fix)"
    )


def test_pipeline_state_has_min_bytes():
    body = CANONICAL.read_text(encoding="utf-8")
    block = _extract_must_write(body)
    m = re.search(
        r"path:\s*[\"']?\$\{PHASE_DIR\}/PIPELINE-STATE\.json[\"']?\s*\n"
        r".*?content_min_bytes:\s*(\d+)",
        block, flags=re.DOTALL,
    )
    assert m, "PIPELINE-STATE.json must declare content_min_bytes"
    assert int(m.group(1)) >= 50, "min_bytes too low — empty {} would pass"


def test_build_md_mirror_byte_identical():
    if not MIRROR.exists():
        return
    assert CANONICAL.read_bytes() == MIRROR.read_bytes(), (
        "build.md canonical/mirror must be byte-identical"
    )
