from pathlib import Path

def test_test_md_spawns_reflector_after_completion():
    """test.md must spawn vg-reflector after phase.test_completed event,
    gated by meta_memory_mode flag."""
    f = Path("commands/vg/test.md").read_text(encoding="utf-8")
    assert "vg-reflector" in f, "test.md must reference vg-reflector spawn"
    assert "phase.test_completed" in f, "test.md must reference phase.test_completed event"
    assert "meta_memory_mode" in f, "test.md spawn must be gated by meta_memory_mode flag"

def test_reflection_trigger_doc_lists_test():
    doc = Path("commands/vg/_shared/reflection-trigger.md").read_text(encoding="utf-8")
    assert ("post-test" in doc.lower()) or ("phase.test_completed" in doc), \
        "reflection-trigger.md must document post-test hook"
    assert ("target_step=test" in doc) or ("target_step: test" in doc), \
        "reflection-trigger.md must say vg-reflector spawned with target_step=test"

def test_mirror_byte_identical_test():
    canonical = Path("commands/vg/test.md").read_bytes()
    mirror = Path(".claude/commands/vg/test.md").read_bytes()
    assert canonical == mirror, "test.md mirror diverged from canonical"

def test_mirror_byte_identical_reflection_trigger_after_22():
    canonical = Path("commands/vg/_shared/reflection-trigger.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/reflection-trigger.md").read_bytes()
    assert canonical == mirror, "reflection-trigger.md mirror diverged from canonical"
