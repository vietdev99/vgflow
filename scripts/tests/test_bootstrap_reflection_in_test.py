"""
BOOT-1 (2026-04-23) — verify bootstrap_reflection step exists in test.md
and is declared in runtime_contract. Previously reflection only ran at
review close, so test phase learnings evaporated (mutation bugs,
regression failures, codegen gaps never captured).

Also verifies "Self-Healing" naming is corrected to the more accurate
"Human-Curated Learning" since promotion is gated by /vg:learn user
approval, not autonomous.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if candidate.name == ".claude" and (candidate / "commands" / "vg").exists():
            return candidate.parent
        if (candidate / "sync.sh").exists() and (candidate / ".claude" / "commands" / "vg").exists():
            return candidate
        if (candidate / "commands" / "vg").exists() and (candidate / "scripts").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
TEST_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "test.md"


@pytest.fixture(scope="module")
def test_md_text() -> str:
    return TEST_MD.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────
# runtime_contract frontmatter

def test_bootstrap_reflection_in_must_touch_markers(test_md_text):
    """Contract must list bootstrap_reflection as tracked marker."""
    # Extract frontmatter between --- lines
    m = re.search(r"^---\n(.+?)\n---", test_md_text, re.DOTALL)
    assert m, "test.md missing frontmatter block"
    frontmatter = m.group(1)
    assert "bootstrap_reflection" in frontmatter, (
        "bootstrap_reflection not declared in runtime_contract — "
        "orchestrator won't check marker at step close"
    )


def test_bootstrap_reflection_severity_warn(test_md_text):
    """Severity must be warn — reflector crash shouldn't fail test."""
    m = re.search(r"^---\n(.+?)\n---", test_md_text, re.DOTALL)
    assert m
    frontmatter = m.group(1)
    # Look for the bootstrap_reflection block with its severity
    bs_block = re.search(
        r'-\s+name:\s+"bootstrap_reflection"\s*\n\s+severity:\s+"(\w+)"',
        frontmatter,
    )
    assert bs_block, "bootstrap_reflection marker missing severity field"
    assert bs_block.group(1) == "warn", (
        f"severity must be 'warn' (non-blocking). Got: {bs_block.group(1)}"
    )


# ─────────────────────────────────────────────────────────────────────────
# step body

def test_bootstrap_reflection_step_exists(test_md_text):
    """Step definition must exist in body, not only contract."""
    assert '<step name="bootstrap_reflection">' in test_md_text, (
        "bootstrap_reflection step tag missing from test.md body"
    )


def test_step_invokes_vg_reflector_skill(test_md_text):
    """Step must spawn reflector agent with skill vg-reflector."""
    assert "Use skill: vg-reflector" in test_md_text, (
        "bootstrap_reflection step does not invoke vg-reflector skill"
    )


def test_step_has_skip_condition_for_bootstrap_opt_out(test_md_text):
    """Step must skip when .vg/bootstrap/ absent — don't force it."""
    assert "BOOTSTRAP_DIR=\".vg/bootstrap\"" in test_md_text or \
           ".vg/bootstrap" in test_md_text, (
        "step doesn't check .vg/bootstrap opt-in state"
    )


def test_step_emits_telemetry(test_md_text):
    """bootstrap.reflection_ran event must be emitted for efficacy tracking."""
    assert "bootstrap.reflection_ran" in test_md_text, (
        "telemetry event bootstrap.reflection_ran missing — "
        "efficacy ACCEPTED.md hit counting will miss test phase"
    )


def test_step_has_marker_touch(test_md_text):
    """Final action must touch step marker — universal rule 10."""
    # Scoped to the reflection step block
    step_block = re.search(
        r'<step name="bootstrap_reflection">(.*?)</step>',
        test_md_text, re.DOTALL,
    )
    assert step_block
    body = step_block.group(1)
    assert ".step-markers/bootstrap_reflection.done" in body, (
        "step missing terminal `touch .step-markers/bootstrap_reflection.done` "
        "— violates rule 10 (universal marker enforcement)"
    )


# ─────────────────────────────────────────────────────────────────────────
# naming correction

def test_human_curated_learning_not_self_healing(test_md_text):
    """
    'Self-Healing' is misleading — system requires human /vg:learn gate.
    Naming MUST reflect reality: Human-Curated Learning.
    """
    step_block = re.search(
        r'<step name="bootstrap_reflection">(.*?)</step>',
        test_md_text, re.DOTALL,
    )
    assert step_block
    body = step_block.group(1)
    # Must mention the corrected term
    assert "Human-Curated Learning" in body, (
        "step header missing 'Human-Curated Learning' naming correction"
    )


def test_vg_reflector_skill_exists_on_disk():
    """The skill invoked must actually exist."""
    skill = REPO_ROOT / ".claude" / "skills" / "vg-reflector" / "SKILL.md"
    assert skill.exists(), f"vg-reflector skill missing at {skill}"
