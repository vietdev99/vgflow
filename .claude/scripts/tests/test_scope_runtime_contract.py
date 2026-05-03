import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SLIM = REPO / "commands" / "vg" / "scope.md"


def _load_frontmatter():
    body = SLIM.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", body, re.DOTALL)
    assert m, "scope.md has no YAML frontmatter"
    return yaml.safe_load(m.group(1))


def test_must_write_includes_3_layers_for_context():
    """UX baseline R1: scope MUST write CONTEXT.md (L3 flat) + CONTEXT/index.md (L2) + CONTEXT/D-*.md (L1) + DISCUSSION-LOG.md."""
    fm = _load_frontmatter()
    rc = fm.get("runtime_contract", {})
    paths = []
    for entry in rc.get("must_write", []):
        if isinstance(entry, str):
            paths.append(entry)
        elif isinstance(entry, dict):
            paths.append(entry.get("path", ""))
    flat = " ".join(paths)
    assert "CONTEXT.md" in flat, "missing layer-3 CONTEXT.md"
    assert "CONTEXT/index.md" in flat, "missing layer-2 CONTEXT/index.md"
    assert "CONTEXT/D-" in flat, "missing layer-1 CONTEXT/D-*.md glob"
    assert "DISCUSSION-LOG.md" in flat, "missing DISCUSSION-LOG.md"


def test_must_emit_telemetry_includes_native_tasklist_projected():
    """Audit fix #9: scope.native_tasklist_projected MUST be required (was 0 events in baseline)."""
    fm = _load_frontmatter()
    rc = fm.get("runtime_contract", {})
    events = []
    for entry in rc.get("must_emit_telemetry", []):
        if isinstance(entry, str):
            events.append(entry)
        elif isinstance(entry, dict):
            events.append(entry.get("event_type", ""))
    assert "scope.native_tasklist_projected" in events, f"missing native_tasklist_projected in {events}"


def test_must_touch_markers_includes_3_required():
    fm = _load_frontmatter()
    rc = fm.get("runtime_contract", {})
    markers = []
    for entry in rc.get("must_touch_markers", []):
        if isinstance(entry, str):
            markers.append(entry)
        elif isinstance(entry, dict):
            markers.append(entry.get("name", ""))
    for required in ("0_parse_and_validate", "1_deep_discussion", "2_artifact_generation"):
        assert required in markers, f"missing marker {required}"
