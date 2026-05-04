"""R6 Task 13 — trust-review replay enforcement gate.

Asserts that vg-test-goal-verifier SKILL.md documents the gate that forces
full replay on goals whose code/spec fingerprint changed since the last
verified run. Trust-review v1.14.0+ default skips replay for unchanged
goals (cost optimization), but static review can't catch regressions in
changed code → mismatched goals MUST replay.

Doc-level test: SKILL.md is the single source of truth for the verifier
subagent's procedure; if the documented gate is missing, the AI-driven
verifier won't enforce it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = REPO_ROOT / "agents" / "vg-test-goal-verifier" / "SKILL.md"
MIRROR_MD = REPO_ROOT / ".claude" / "agents" / "vg-test-goal-verifier" / "SKILL.md"


def _read_skill() -> str:
    assert SKILL_MD.exists(), f"missing canonical SKILL.md: {SKILL_MD}"
    return SKILL_MD.read_text(encoding="utf-8")


def test_skill_has_replay_enforcement_gate() -> None:
    """Gate must be documented with fingerprint + replay + changed semantics."""
    body = _read_skill()
    lower = body.lower()
    assert "fingerprint" in lower, "SKILL.md missing 'fingerprint' concept"
    assert "replay" in lower, "SKILL.md missing 'replay' concept"
    # Some marker that ties the gate to changed goals (mismatch / changed / delta).
    assert any(tok in lower for tok in ("mismatch", "changed", "delta")), (
        "SKILL.md missing the 'changed-goal' framing for the replay gate"
    )
    # Gate header must explicitly call out R6 Task 13 anchor.
    assert "r6 task 13" in lower, "SKILL.md missing R6 Task 13 anchor for the gate"


def test_skill_documents_goal_fingerprint_schema() -> None:
    """Return JSON schema must declare goal_fingerprint + baseline + match."""
    body = _read_skill()
    assert "goal_fingerprint" in body, "missing goal_fingerprint in return schema"
    assert "fingerprint_baseline" in body, "missing fingerprint_baseline in return schema"
    assert "fingerprint_match" in body, "missing fingerprint_match in return schema"


def test_skill_documents_telemetry_event() -> None:
    """Gate trigger must emit dedicated telemetry event."""
    body = _read_skill()
    assert "test.trust_review_mismatch_replay_required" in body, (
        "SKILL.md missing telemetry event 'test.trust_review_mismatch_replay_required'"
    )


def test_skill_documents_override_flag() -> None:
    """Operator override must be explicitly documented (escape hatch)."""
    body = _read_skill()
    assert "--allow-trust-review-on-changed-goals" in body, (
        "SKILL.md missing override flag '--allow-trust-review-on-changed-goals'"
    )
    assert "--override-reason" in body, (
        "SKILL.md missing required '--override-reason' companion to override flag"
    )


def test_skill_documents_baseline_path() -> None:
    """Baseline storage path must be deterministic and documented."""
    body = _read_skill()
    assert ".replay-baseline" in body, "SKILL.md missing .replay-baseline directory"
    assert "G-NN.json" in body, "SKILL.md missing per-goal baseline filename pattern"
    assert "${PHASE_DIR}/.replay-baseline/G-NN.json" in body, (
        "SKILL.md missing fully-qualified baseline path"
    )


def test_mirror_parity_if_present() -> None:
    """If the .claude/agents mirror exists, it MUST match the canonical SKILL."""
    if not MIRROR_MD.exists():
        return  # Mirror optional in some installs.
    canonical = SKILL_MD.read_text(encoding="utf-8")
    mirror = MIRROR_MD.read_text(encoding="utf-8")
    assert canonical == mirror, (
        "Mirror .claude/agents/vg-test-goal-verifier/SKILL.md drifted from "
        "canonical agents/vg-test-goal-verifier/SKILL.md — re-sync required"
    )
