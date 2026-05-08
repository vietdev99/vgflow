"""Tests for /vg:accept preflight meta-memory bootstrap inject (Stage 4 task 3/4).

Mirror of build preflight inject (Task 4.1) but filtered for accept-step rules
and using phase_type as the precondition. Renders rules to
${PHASE_DIR}/.accept-context.md so accept-flow consumers see the rules
before UAT/audit gates fire.

Gated by `meta_memory_mode != "disabled"`. Mirror byte-identity is required.
"""
from pathlib import Path


CANONICAL = Path("commands/vg/_shared/accept/preflight.md")
MIRROR = Path(".claude/commands/vg/_shared/accept/preflight.md")


def test_accept_preflight_md_invokes_bootstrap_loader():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "bootstrap-loader" in f
    assert "meta_memory_mode" in f
    assert ".accept-context.md" in f


def test_accept_preflight_loads_target_step_accept():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "--target-step accept" in f


def test_accept_preflight_includes_procedural_flag():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "--include-procedural" in f


def test_accept_preflight_consumes_loader_json_output():
    f = CANONICAL.read_text(encoding="utf-8")
    assert ("import json" in f) or ("jq" in f) or ("python3 -c" in f)


def test_accept_preflight_max_bytes_cap_present():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "--max-bytes" in f


def test_accept_preflight_uses_phase_type_precondition():
    """Spec: filter-preconditions {phase_type: $PHASE_TYPE}."""
    f = CANONICAL.read_text(encoding="utf-8")
    assert "phase_type" in f


def test_accept_preflight_default_off():
    f = CANONICAL.read_text(encoding="utf-8")
    assert ('"disabled"' in f) or ("'disabled'" in f) or ("=disabled" in f)


def test_mirror_byte_identical_accept_preflight():
    canonical = CANONICAL.read_bytes()
    mirror = MIRROR.read_bytes()
    assert canonical == mirror, (
        f"Mirror drift: canonical={len(canonical)} bytes vs mirror={len(mirror)} bytes"
    )
