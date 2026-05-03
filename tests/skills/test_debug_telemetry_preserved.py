"""debug.md frontmatter MUST retain all 5 telemetry events."""

REQUIRED_EVENT_TYPES = {
    "debug.parsed",
    "debug.classified",
    "debug.fix_attempted",
    "debug.user_confirmed",
    "debug.completed",
}


def test_debug_telemetry_events_preserved(skill_loader):
    skill = skill_loader("debug")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    events = rc.get("must_emit_telemetry", [])
    found = {e["event_type"] for e in events if isinstance(e, dict) and "event_type" in e}
    missing = REQUIRED_EVENT_TYPES - found
    assert not missing, (
        f"frontmatter must_emit_telemetry missing event_types: {missing}\n"
        f"current event_types: {sorted(found)}"
    )
