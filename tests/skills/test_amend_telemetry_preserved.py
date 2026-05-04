"""amend.md frontmatter MUST retain amend.started + amend.completed events."""

REQUIRED_EVENT_TYPES = {"amend.started", "amend.completed"}


def test_amend_telemetry_events_preserved(skill_loader):
    skill = skill_loader("amend")
    fm = skill["frontmatter"]
    rc = fm.get("runtime_contract", {})
    events = rc.get("must_emit_telemetry", [])
    found = {e["event_type"] for e in events if isinstance(e, dict) and "event_type" in e}
    missing = REQUIRED_EVENT_TYPES - found
    assert not missing, (
        f"frontmatter must_emit_telemetry missing event_types: {missing}\n"
        f"current event_types: {sorted(found)}"
    )
