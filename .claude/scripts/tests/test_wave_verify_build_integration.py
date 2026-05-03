"""
Phase A integration — verify build.md step 8 has post-wave verify hook.

Validates that the wave-verify-isolated integration point exists in
build.md step 8 sub-step 4b, invokes the validator with correct args,
and has rollback logic via git reset --soft.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "build.md"


@pytest.fixture(scope="module")
def step8_body() -> str:
    text = BUILD_MD.read_text(encoding="utf-8")
    m = re.search(
        r'<step name="8_execute_waves">(.*?)</step>',
        text, re.DOTALL,
    )
    assert m, "step 8_execute_waves not found"
    return m.group(1)


def test_step_4b_post_wave_verify_exists(step8_body):
    """Step 4b section must be present after step 4 record wave result."""
    assert "Step 4b" in step8_body or "4b" in step8_body, (
        "build.md step 8 missing Step 4b post-wave verify section"
    )
    assert "post-wave independent verify" in step8_body.lower() or \
           "Post-wave independent verify" in step8_body


def test_invokes_wave_verify_validator(step8_body):
    """Step 4b must invoke wave-verify-isolated.py script."""
    assert "wave-verify-isolated.py" in step8_body, (
        "Step 4b does not invoke wave-verify-isolated.py"
    )
    # Must pass --phase and --wave-tag
    assert "--wave-tag" in step8_body
    assert "--phase" in step8_body


def test_uses_wave_tag_pattern(step8_body):
    """WAVE_TAG must follow vg-build-{phase}-wave-{N}-start pattern."""
    assert "vg-build-${PHASE_NUMBER}-wave-${N}-start" in step8_body


def test_outside_commit_mutex(step8_body):
    """Step 4b narration mentions mutex released + post-mutex placement."""
    assert "post-mutex" in step8_body.lower() or \
           "mutex released" in step8_body.lower() or \
           "outside commit-queue" in step8_body.lower()


def test_rollback_via_git_reset_soft(step8_body):
    """Divergence → git reset --soft {tag} rollback mechanism."""
    assert "git reset --soft" in step8_body
    # Must use WAVE_TAG variable for soft reset, not hard-coded
    m = re.search(r'git reset --soft\s+"?\$\{?WAVE_TAG\}?"?', step8_body)
    assert m, "git reset --soft must use WAVE_TAG variable"


def test_override_flag_present(step8_body):
    """--allow-verify-divergence override flag logged to debt register."""
    assert "--allow-verify-divergence" in step8_body
    assert "log_override_debt" in step8_body


def test_sets_failed_gate_on_divergence(step8_body):
    """Divergence sets FAILED_GATE to surface in step proceed check."""
    assert "FAILED_GATE=\"wave-verify-divergence\"" in step8_body or \
           "FAILED_GATE='wave-verify-divergence'" in step8_body


def test_runs_only_if_wave_succeeded(step8_body):
    """Guard: only run if prior FAILED_GATE empty (wave passed)."""
    # Extract the 4b bash block
    m = re.search(
        r"Step 4b.*?```bash(.*?)```", step8_body, re.DOTALL,
    )
    assert m, "Step 4b bash block not found"
    block = m.group(1)
    # Must check FAILED_GATE empty before running verify
    assert re.search(r'\[\s*-z\s*"?\$FAILED_GATE"?\s*\]', block) or \
           "FAILED_GATE" in block.split("wave-verify")[0]


def test_config_flag_honors_disable(step8_body):
    """Config CONFIG_INDEPENDENT_VERIFY_ENABLED honored (opt-out)."""
    assert "CONFIG_INDEPENDENT_VERIFY_ENABLED" in step8_body or \
           "independent_verify" in step8_body.lower()
