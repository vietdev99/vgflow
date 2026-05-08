"""Tests for /vg:deploy STEP 0 pre-spawn meta-memory bootstrap inject (Stage 4 task 2/4).

Before vg-deploy-executor spawn, deploy.md must load deploy-specific procedural
rules and pass them via BOOTSTRAP_RULES_BLOCK env var to the executor capsule.

Gated by `meta_memory_mode != "disabled"`. Mirror byte-identity is required.
"""
from pathlib import Path


CANONICAL = Path("commands/vg/deploy.md")
MIRROR = Path(".claude/commands/vg/deploy.md")


def test_deploy_md_invokes_bootstrap_loader():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "bootstrap-loader" in f
    assert "meta_memory_mode" in f


def test_deploy_loads_target_step_deploy():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "--target-step deploy" in f


def test_deploy_includes_procedural_flag():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "--include-procedural" in f


def test_deploy_exports_bootstrap_rules_block_env():
    """Pre-spawn inject must export BOOTSTRAP_RULES_BLOCK so executor capsule sees rules."""
    f = CANONICAL.read_text(encoding="utf-8")
    assert "BOOTSTRAP_RULES_BLOCK" in f
    # Must be exported (env var to subprocess)
    assert "export BOOTSTRAP_RULES_BLOCK" in f


def test_deploy_inject_block_consumes_loader_json():
    f = CANONICAL.read_text(encoding="utf-8")
    # JSON parsing reference required
    assert ("import json" in f) or ("jq" in f)


def test_deploy_max_bytes_cap_present():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "--max-bytes" in f


def test_deploy_inject_before_executor_spawn():
    """Inject MUST appear before the vg-deploy-executor Agent invocation comment."""
    f = CANONICAL.read_text(encoding="utf-8")
    inject_pos = f.find("BOOTSTRAP_RULES_BLOCK")
    spawn_pos = f.find('subagent_type="vg-deploy-executor"')
    if spawn_pos == -1:
        # Fallback: any first reference to vg-deploy-executor in spawn context
        spawn_pos = f.find("vg-deploy-executor spawning")
    assert inject_pos != -1, "BOOTSTRAP_RULES_BLOCK not found"
    assert spawn_pos != -1, "vg-deploy-executor spawn site not found"
    assert inject_pos < spawn_pos, (
        f"Inject (pos {inject_pos}) must precede executor spawn (pos {spawn_pos})"
    )


def test_mirror_byte_identical_deploy():
    canonical = CANONICAL.read_bytes()
    mirror = MIRROR.read_bytes()
    assert canonical == mirror, (
        f"Mirror drift: canonical={len(canonical)} bytes vs mirror={len(mirror)} bytes"
    )
