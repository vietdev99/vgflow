from pathlib import Path

def test_accept_md_spawns_reflector_after_completion():
    """accept.md must spawn vg-reflector after phase.accept_uat_completed event,
    gated by meta_memory_mode flag."""
    f = Path("commands/vg/accept.md").read_text(encoding="utf-8")
    assert "vg-reflector" in f, "accept.md must reference vg-reflector spawn"
    assert "phase.accept_uat_completed" in f, "accept.md must reference phase.accept_uat_completed event"
    assert "meta_memory_mode" in f, "accept.md spawn must be gated by meta_memory_mode flag"

def test_reflection_trigger_doc_lists_accept():
    doc = Path("commands/vg/_shared/reflection-trigger.md").read_text(encoding="utf-8")
    assert ("post-accept" in doc.lower()) or ("phase.accept_uat_completed" in doc), \
        "reflection-trigger.md must document post-accept hook"
    assert ("target_step=accept" in doc) or ("target_step: accept" in doc), \
        "reflection-trigger.md must say vg-reflector spawned with target_step=accept"

def test_mirror_byte_identical_accept():
    canonical = Path("commands/vg/accept.md").read_bytes()
    mirror = Path(".claude/commands/vg/accept.md").read_bytes()
    assert canonical == mirror, "accept.md mirror diverged from canonical"

def test_mirror_byte_identical_reflection_trigger_after_23():
    canonical = Path("commands/vg/_shared/reflection-trigger.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/reflection-trigger.md").read_bytes()
    assert canonical == mirror, "reflection-trigger.md mirror diverged from canonical"
