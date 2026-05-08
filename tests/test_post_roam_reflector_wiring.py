from pathlib import Path

def test_roam_md_spawns_reflector_after_completion():
    """roam.md must spawn vg-reflector after phase.roam_completed event,
    gated by meta_memory_mode flag."""
    f = Path("commands/vg/roam.md").read_text(encoding="utf-8")
    assert "vg-reflector" in f, "roam.md must reference vg-reflector spawn"
    assert "phase.roam_completed" in f, "roam.md must reference phase.roam_completed event"
    assert "meta_memory_mode" in f, "roam.md spawn must be gated by meta_memory_mode flag"

def test_reflection_trigger_doc_lists_roam():
    doc = Path("commands/vg/_shared/reflection-trigger.md").read_text(encoding="utf-8")
    assert ("post-roam" in doc.lower()) or ("phase.roam_completed" in doc), \
        "reflection-trigger.md must document post-roam hook"
    assert ("target_step=roam" in doc) or ("target_step: roam" in doc), \
        "reflection-trigger.md must say vg-reflector spawned with target_step=roam"

def test_mirror_byte_identical_roam():
    canonical = Path("commands/vg/roam.md").read_bytes()
    mirror = Path(".claude/commands/vg/roam.md").read_bytes()
    assert canonical == mirror, "roam.md mirror diverged from canonical"

def test_mirror_byte_identical_reflection_trigger_after_24():
    canonical = Path("commands/vg/_shared/reflection-trigger.md").read_bytes()
    mirror = Path(".claude/commands/vg/_shared/reflection-trigger.md").read_bytes()
    assert canonical == mirror, "reflection-trigger.md mirror diverged from canonical"
