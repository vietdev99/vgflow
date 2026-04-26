"""
Tests for the pre-commit RULES-CARDS drift hook (Phase R, v2.7).

Companion to:
- .husky/pre-commit
- .claude/scripts/validators/verify-rule-cards-fresh-hook.py

Cases (per PLAN-v2.7 R5):
  1. SKILL.md modified, RULES-CARDS regenerated (cards newer) → PASS
  2. SKILL.md modified, RULES-CARDS stale (cards older)        → BLOCK
  3. RULES-CARDS-MANUAL.md modified only (no SKILL.md)         → PASS
     (drift gate must not fire on operator-curated manual cards)
  4. Hook output schema canonical:
     • exit code is exactly 1 on BLOCK (never 2 — that's reserved)
     • stderr contains the remediation command path
     • stderr cites the no-verify ban (executor-rule cross-reference)

Tests target the validator script directly via subprocess. We don't
execute the husky shim here — the shim is a thin wrapper whose
contract is "pipe staged SKILL.md paths to the validator", which is
covered by the integration test in test_pre_commit_rule_cards_drift.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = (
    REPO_ROOT / ".claude" / "scripts" / "validators"
    / "verify-rule-cards-fresh-hook.py"
)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _make_skill(tmp_path: Path, name: str = "vg-test-skill") -> tuple[Path, Path]:
    """Create a skill dir with SKILL.md + RULES-CARDS.md. Returns (skill_md, cards_md)."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    cards_md = skill_dir / "RULES-CARDS.md"
    skill_md.write_text("# fake skill body\n", encoding="utf-8")
    cards_md.write_text("# fake auto cards\n", encoding="utf-8")
    return skill_md, cards_md


# ─── Case 1 — SKILL.md modified, RULES-CARDS regenerated (PASS) ──────

def test_cards_fresher_than_skill_passes(tmp_path):
    skill_md, cards_md = _make_skill(tmp_path)
    # Cards regenerated AFTER skill edit — typical post-extractor state.
    now = time.time()
    os.utime(skill_md, (now - 10, now - 10))
    os.utime(cards_md, (now, now))

    r = _run([str(skill_md)])
    assert r.returncode == 0, (
        f"Fresh cards must PASS\nstdout={r.stdout}\nstderr={r.stderr}"
    )


# ─── Case 2 — SKILL.md modified, RULES-CARDS stale (BLOCK) ───────────

def test_cards_stale_blocks(tmp_path):
    skill_md, cards_md = _make_skill(tmp_path)
    # Skill edited AFTER cards — drift state.
    now = time.time()
    os.utime(cards_md, (now - 10, now - 10))
    os.utime(skill_md, (now, now))

    r = _run([str(skill_md)])
    assert r.returncode == 1, (
        f"Stale cards must BLOCK with rc=1\nstdout={r.stdout}\nstderr={r.stderr}"
    )
    # Stderr must name the offending skill so operator can find it.
    assert "vg-test-skill" in r.stderr, "BLOCK must name the drifted skill"
    # Stderr must include the remediation command verbatim.
    assert "extract-rule-cards.py" in r.stderr, (
        "BLOCK must reference the extractor as remediation"
    )


# ─── Case 3 — Manual cards modified, no SKILL.md staged (PASS) ───────

def test_manual_only_modification_passes(tmp_path):
    """Drift gate must not fire when only RULES-CARDS-MANUAL.md is staged.

    The husky hook filters staged files by SKILL.md name BEFORE invoking
    the validator. If no SKILL.md paths are forwarded, the validator
    short-circuits to PASS. We verify that contract here by passing zero
    arguments — the same condition the hook produces when the staged
    diff lists only RULES-CARDS-MANUAL.md.
    """
    skill_md, cards_md = _make_skill(tmp_path)
    manual_md = skill_md.parent / "RULES-CARDS-MANUAL.md"
    manual_md.write_text("# operator-curated\n", encoding="utf-8")

    # Simulate the hook filter: only manual was staged → validator gets
    # zero SKILL.md paths.
    r = _run([])
    assert r.returncode == 0, (
        f"No SKILL.md staged must PASS\nstdout={r.stdout}\nstderr={r.stderr}"
    )

    # Belt-and-braces: even if the validator IS asked about a fresh
    # SKILL.md (manual cards being edited typically coincides with NO
    # skill change at all), it should still PASS because cards mtime
    # is fresh.
    now = time.time()
    os.utime(skill_md, (now - 10, now - 10))
    os.utime(cards_md, (now, now))
    r2 = _run([str(skill_md)])
    assert r2.returncode == 0


# ─── Case 4 — Output schema canonical (rc=1, remediation, no-verify ban) ──

def test_block_output_schema(tmp_path):
    skill_md, cards_md = _make_skill(tmp_path)
    now = time.time()
    os.utime(cards_md, (now - 10, now - 10))
    os.utime(skill_md, (now, now))

    r = _run([str(skill_md)])

    # Exit code: exactly 1, never 2 (rc=2 is reserved for VG validator
    # config errors per the regression harness convention).
    assert r.returncode == 1, f"BLOCK must use rc=1, got rc={r.returncode}"

    # Remediation: stderr must include the canonical extractor command
    # so operators see it without consulting docs.
    assert "extract-rule-cards.py" in r.stderr

    # Cross-reference to executor rules — keeps the no-verify policy
    # visible at the moment a developer is most tempted to bypass it.
    assert "no-verify" in r.stderr.lower(), (
        "BLOCK must cite the no-verify ban (defense in depth)"
    )

    # Visual marker — operators scan for this glyph.
    assert "⛔" in r.stderr or "BLOCKED" in r.stderr.upper()


# ─── Additional safety — non-existent SKILL.md (deletion) is allowed ──

def test_deleted_skill_passes(tmp_path):
    """If a SKILL.md is staged for deletion, allow the commit."""
    nonexistent = tmp_path / "deleted-skill" / "SKILL.md"
    r = _run([str(nonexistent)])
    assert r.returncode == 0, (
        f"Deletion must PASS\nstdout={r.stdout}\nstderr={r.stderr}"
    )


# ─── Additional safety — first-time skill without RULES-CARDS allowed ──

def test_skill_without_cards_passes(tmp_path):
    """A new skill with no RULES-CARDS.md yet must not block — operator
    will run the extractor in a follow-up commit. The gate's purpose is
    preventing DRIFT, not enforcing card-presence."""
    skill_dir = tmp_path / "new-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("# brand new\n", encoding="utf-8")

    r = _run([str(skill_md)])
    assert r.returncode == 0
