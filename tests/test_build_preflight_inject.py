"""Tests for /vg:build STEP 0.5b meta-memory bootstrap inject (Stage 4 task 1/4).

The build preflight skill must call bootstrap-loader.py with deploy+build
target steps, parse JSON output, render to markdown, and append to
${PHASE_DIR}/.build-context.md so orchestrator/planner sees deploy gating
patterns BEFORE planner divides waves.

Gated by `meta_memory_mode != "disabled"` in vg.config.md.

Mirror byte-identity is a hard requirement — both copies of preflight.md
must be byte-identical.
"""
from pathlib import Path


CANONICAL = Path("commands/vg/_shared/build/preflight.md")
MIRROR = Path(".claude/commands/vg/_shared/build/preflight.md")


def test_build_preflight_md_invokes_bootstrap_loader():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "bootstrap-loader" in f
    assert "meta_memory_mode" in f
    assert ".build-context.md" in f


def test_build_preflight_loads_target_step_build_and_deploy():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "--target-step build" in f
    assert "--target-step deploy" in f


def test_build_preflight_includes_procedural_flag():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "--include-procedural" in f


def test_build_preflight_consumes_loader_json_output():
    """Inject block must parse JSON output (jq or python) — loader emits JSON."""
    f = CANONICAL.read_text(encoding="utf-8")
    # One of: jq, python -c, json parsing reference
    assert ("jq" in f) or ("import json" in f) or ("python3 -c" in f)


def test_build_preflight_max_bytes_cap_present():
    """Stage 4 contract: max-bytes budget must be honored to prevent context bloat."""
    f = CANONICAL.read_text(encoding="utf-8")
    assert "--max-bytes" in f


def test_build_preflight_default_off():
    """meta_memory_mode=disabled MUST skip inject — no behavior change in current pipeline."""
    f = CANONICAL.read_text(encoding="utf-8")
    # Must reference disabled fallback OR an explicit guard branch
    assert ('"disabled"' in f) or ("'disabled'" in f) or ("=disabled" in f)


def test_mirror_byte_identical_build_preflight():
    canonical = CANONICAL.read_bytes()
    mirror = MIRROR.read_bytes()
    assert canonical == mirror, (
        f"Mirror drift: canonical={len(canonical)} bytes vs mirror={len(mirror)} bytes"
    )
