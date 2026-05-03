"""R4 Accept Pilot — vg-load consumption (Phase F Task 30 absorption).

Large multi-unit artifacts (TEST-GOALS, PLAN) MUST be loaded via
`scripts/vg-load.sh` for partial / per-unit reads. Flat reads of these
artifacts blow the consumer's context budget and trigger AI-skim mode.

KEEP-FLAT allowlist (small / single-doc files — direct read is OK):
  CONTEXT.md, FOUNDATION.md, CRUD-SURFACES.md, RIPPLE-ANALYSIS.md,
  SUMMARY*.md, build-state.log, GOAL-COVERAGE-MATRIX.md.

This test enforces vg-load adoption in NEW R4 surfaces (subagent SKILLs +
delegation refs). Legacy refs containing verbatim bash from the pre-R4
accept.md backup are allowed to keep flat reads — refactoring those is
out of scope for the pilot (would re-write the bash for no behavior change).
"""
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]

# Consumers that MUST adopt vg-load (R4 surfaces)
VG_LOAD_REQUIRED = [
    REPO / "agents/vg-accept-uat-builder/SKILL.md",
    REPO / "commands/vg/_shared/accept/uat/checklist-build/delegation.md",
    REPO / "commands/vg/_shared/accept/uat/checklist-build/overview.md",
]

# Large split artifacts that should NOT be cat'd flat from R4 surfaces
LARGE_FLAT_PATTERNS = [
    # Match Python read_text() / open() of TEST-GOALS.md or PLAN.md flat
    re.compile(r'open\([^)]*TEST-GOALS\.md[^)]*\)'),
    re.compile(r'read_text\([^)]*TEST-GOALS\.md[^)]*\)'),
    re.compile(r'open\([^)]*/PLAN\.md[^)]*\)'),
    re.compile(r'read_text\([^)]*/PLAN\.md[^)]*\)'),
    # Direct bash cat of these
    re.compile(r'cat\s+\S*TEST-GOALS\.md\b'),
    re.compile(r'cat\s+\S*\bPLAN\.md\b'),
]


def test_required_consumers_use_vg_load():
    """Subagent SKILLs + delegation refs MUST mention vg-load."""
    for p in VG_LOAD_REQUIRED:
        assert p.exists(), f"missing required consumer: {p}"
        body = p.read_text()
        assert "vg-load" in body, (
            f"{p} MUST use vg-load (Phase F Task 30) — "
            f"large artifacts (TEST-GOALS, PLAN) cannot be cat'd flat"
        )


def test_uat_builder_skill_uses_vg_load_for_goals_and_design_refs():
    """Subagent SKILL must use vg-load specifically for goals + plan."""
    p = REPO / "agents/vg-accept-uat-builder/SKILL.md"
    body = p.read_text()
    # Section B (goals) must reference vg-load
    assert re.search(r"vg-load.*--artifact\s+goals", body), (
        "uat-builder SKILL must use `vg-load --artifact goals` for Section B"
    )
    # Section D (design refs from plan) must reference vg-load
    assert re.search(r"vg-load.*--artifact\s+plan", body), (
        "uat-builder SKILL must use `vg-load --artifact plan` for Section D design-refs"
    )


def test_r4_surfaces_no_flat_test_goals_or_plan_read():
    """R4 spawn-site refs MUST NOT cat large multi-unit artifacts.

    Excludes the subagent SKILL (it owns the actual heavy work and uses
    vg-load there) — this asserts the slim spawn surfaces stay clean.
    """
    targets = [
        REPO / "commands/vg/_shared/accept/uat/checklist-build/overview.md",
        REPO / "commands/vg/_shared/accept/uat/checklist-build/delegation.md",
        REPO / "commands/vg/_shared/accept/cleanup/overview.md",
        REPO / "commands/vg/_shared/accept/cleanup/delegation.md",
    ]
    for p in targets:
        body = p.read_text()
        for pattern in LARGE_FLAT_PATTERNS:
            m = pattern.search(body)
            assert not m, (
                f"{p} contains flat read of large artifact: "
                f"{m.group(0) if m else '?'}\n"
                f"Use `vg-load --phase ... --artifact ... --list` for partial reads."
            )


def test_keep_flat_artifacts_documented():
    """Delegation refs MUST document KEEP-FLAT allowlist (consumer guidance)."""
    targets = [
        REPO / "commands/vg/_shared/accept/uat/checklist-build/delegation.md",
    ]
    keep_flat_artifacts = [
        "CONTEXT.md",
        "FOUNDATION.md",
        "CRUD-SURFACES.md",
        "RIPPLE-ANALYSIS.md",
        "SUMMARY*.md",
        "build-state.log",
    ]
    for p in targets:
        body = p.read_text()
        # At least 4 of the KEEP-FLAT items should be mentioned in the
        # source list (delegation maps inputs to load mode)
        mentioned = sum(1 for a in keep_flat_artifacts if a in body)
        assert mentioned >= 4, (
            f"{p} should document KEEP-FLAT artifacts in the input source table "
            f"(found {mentioned}/{len(keep_flat_artifacts)} items)"
        )
        # Either KEEP-FLAT phrase or load-mode column should be present
        assert "KEEP-FLAT" in body or "Load mode" in body, (
            f"{p} should mark load mode for each input artifact"
        )
