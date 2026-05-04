"""R8-D — UAT RCRURDR lifecycle attestation (closed-loop accept layer).

Codex audit (2026-05-05) found accept layer MISSING on RCRURDR closed-loop:
UAT asks each READY goal only "Verified working in runtime?" — no specific
mutation lifecycle attestation. Quorum gate counts READY-goal responses/
skips, NOT mutation lifecycle integrity.

This test pins the new behavior:
  - SKILL.md (vg-accept-uat-builder) generates `RCRURD-G-NN` items in
    Section B.1 for goals where invariant has `lifecycle: rcrurdr`.
  - Generic-question goals (read-only, lifecycle=rcrurd default) DO NOT
    get an RCRURD-* item — back-compat.
  - interactive.md presents the 7-phase question for `RCRURD-*` items.
  - quorum.md gate BLOCKs verdict on `rcrurdr.items[].verdict == "f"`
    regardless of other section passes.
  - quorum.md ALLOWS proceed when all rcrurd items pass.
  - accept.md frontmatter declares `--allow-failed-rcrurdr-attestation`
    in `forbidden_without_override`.
  - .uat-responses.json schema (interactive.md) documents `rcrurdr` key.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCEPT_MD = REPO_ROOT / "commands" / "vg" / "accept.md"
INTERACTIVE_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "accept" / "uat" / "interactive.md"
)
QUORUM_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "accept" / "uat" / "quorum.md"
)
CHECKLIST_OVERVIEW_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "accept" / "uat" / "checklist-build" / "overview.md"
)
CHECKLIST_DELEGATION_MD = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "accept" / "uat" / "checklist-build" / "delegation.md"
)
BUILDER_SKILL_MD = REPO_ROOT / "agents" / "vg-accept-uat-builder" / "SKILL.md"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "vg-orchestrator"))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — load files once
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def accept_text() -> str:
    return ACCEPT_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def interactive_text() -> str:
    return INTERACTIVE_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def quorum_text() -> str:
    return QUORUM_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def checklist_overview_text() -> str:
    return CHECKLIST_OVERVIEW_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def checklist_delegation_text() -> str:
    return CHECKLIST_DELEGATION_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def builder_skill_text() -> str:
    return BUILDER_SKILL_MD.read_text(encoding="utf-8")


def _extract_step(text: str, name: str) -> str:
    match = re.search(
        rf'<step name="{re.escape(name)}"[^>]*>(.+?)</step>',
        text, re.DOTALL,
    )
    assert match, f'step "{name}" missing'
    return match.group(1)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Checklist generation — RCRURDR goals → RCRURD-* items in B.1
# ─────────────────────────────────────────────────────────────────────────────

def test_checklist_includes_rcrurd_for_lifecycle_rcrurdr_goals(builder_skill_text):
    """SKILL.md must instruct the subagent to emit `RCRURD-<goal_id>` rows
    in Section B.1 for goals with `lifecycle: rcrurdr`."""
    # Section B.1 must reference the R8-D RCRURDR generation block
    assert "RCRURD-" in builder_skill_text or "rcrurdr-attestation" in builder_skill_text, (
        "SKILL.md missing RCRURD- item generation"
    )
    assert "lifecycle: rcrurdr" in builder_skill_text, (
        "SKILL.md must reference `lifecycle: rcrurdr` discriminator"
    )
    # Must reference the Single Source of Truth helper (R7 Task 2)
    assert "rcrurd_invariant" in builder_skill_text, (
        "SKILL.md must reference `scripts/lib/rcrurd_invariant.py`"
    )
    # Must call extract_from_test_goal_md for back-compat (inline yaml-rcrurd fence)
    assert "extract_from_test_goal_md" in builder_skill_text or "RCRURD-INVARIANTS" in builder_skill_text, (
        "SKILL.md must read RCRURD-INVARIANTS/G-NN.yaml or extract from TEST-GOAL md"
    )


def test_checklist_omits_rcrurd_for_non_rcrurdr_goals(builder_skill_text):
    """SKILL.md must filter on `lifecycle == 'rcrurdr'` (NOT every mutation
    goal). Goals with default `rcrurd` lifecycle (single read-after-write)
    do NOT get an RCRURD-* row — they keep the generic Section B question."""
    # Look for the dedicated R8-D RCRURDR generation subsection (h4) and
    # extract its body. The first "R8-D" token in SKILL.md is in the
    # parent section header, so anchor on the explicit subsection.
    rcrurd_block = re.search(
        r"####\s+R8-D[^\n]*\n(.+?)(?=\n#### |\n### |\n## |\Z)",
        builder_skill_text, re.DOTALL,
    )
    assert rcrurd_block is not None, (
        "SKILL.md missing dedicated `#### R8-D ...` RCRURDR subsection"
    )
    block_text = rcrurd_block.group(1)
    # Must explicitly check inv.lifecycle == "rcrurdr"
    assert 'inv.lifecycle == "rcrurdr"' in block_text or "lifecycle == 'rcrurdr'" in block_text, (
        "SKILL.md R8-D block must filter on lifecycle == 'rcrurdr' "
        "(not every mutation goal — default rcrurd keeps generic question)"
    )


def test_checklist_overview_documents_rcrurd_items_in_b1(checklist_overview_text):
    """overview.md JSON return shape must document the RCRURD-* item shape
    so main agent + quorum gate know to special-case them."""
    assert "RCRURD-" in checklist_overview_text, (
        "overview.md output schema doesn't show RCRURD-* item example"
    )
    assert "rcrurdr-attestation" in checklist_overview_text, (
        "overview.md doesn't document `kind: rcrurdr-attestation` field"
    )
    assert "critical" in checklist_overview_text, (
        "overview.md doesn't document `critical: true` field for RCRURD-* items"
    )


def test_checklist_delegation_lists_rcrurd_source(checklist_delegation_text):
    """delegation.md artifact-source table must include RCRURD-INVARIANTS +
    yaml-rcrurd fence sources for Section B.1."""
    # B.1 row must mention RCRURD-INVARIANTS or rcrurdr lifecycle
    assert "RCRURD-INVARIANTS" in checklist_delegation_text or "yaml-rcrurd" in checklist_delegation_text, (
        "delegation.md doesn't list RCRURD-INVARIANTS or yaml-rcrurd source for B.1"
    )
    assert "R8-D" in checklist_delegation_text, (
        "delegation.md doesn't reference R8-D anchor"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Interactive prompt — full 7-phase question for RCRURD-* items
# ─────────────────────────────────────────────────────────────────────────────

def test_uat_question_full_7_phase(interactive_text):
    """interactive.md must present the FULL 7-phase RCRURDR question (NOT
    generic 'working in runtime?') for items with id `RCRURD-*`."""
    # Must mention every phase
    seven_phases = [
        "Read empty",
        "Create",
        "Read shows new entity",  # read_populated
        "Update",
        "Read confirms update",  # read_updated
        "Delete",
        "Read empty after delete",  # read_after_delete
    ]
    for phase in seven_phases:
        assert phase in interactive_text, (
            f"interactive.md missing 7-phase prompt fragment: {phase!r}"
        )

    # Must reference the RCRURD-* id pattern as the trigger
    assert "RCRURD-" in interactive_text, (
        "interactive.md doesn't gate the new question on RCRURD-* id prefix"
    )

    # Must mention this is critical / blocks quorum
    assert re.search(r"critical|BLOCK", interactive_text, re.IGNORECASE), (
        "interactive.md doesn't surface that RCRURD-* failure blocks quorum"
    )


def test_uat_responses_json_includes_rcrurd_section(interactive_text):
    """`.uat-responses.json` schema in interactive.md must include the
    `rcrurdr` section so quorum gate can read it."""
    assert '"rcrurdr"' in interactive_text or "rcrurdr:" in interactive_text, (
        "interactive.md JSON schema doesn't include `rcrurdr` section"
    )
    # Each item must record verdict (p/f/s) so quorum gate can detect failures
    rcrurdr_block = re.search(
        r'"rcrurdr"\s*:\s*\{[^}]*?\}',
        interactive_text, re.DOTALL,
    )
    assert rcrurdr_block is not None, "rcrurdr key not found in JSON example"
    assert "verdict" in rcrurdr_block.group(0), (
        "rcrurdr items don't carry a `verdict` field for quorum to read"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Quorum gate — block on failed RCRURD attestation
# ─────────────────────────────────────────────────────────────────────────────

def test_quorum_blocks_on_failed_rcrurd(quorum_text):
    """quorum.md must read `rcrurdr.items[*].verdict == 'f'` and BLOCK with
    exit 1 (unless --allow-failed-rcrurdr-attestation)."""
    # Must reference the rcrurdr section of .uat-responses.json
    assert '"rcrurdr"' in quorum_text or 'data.get("rcrurdr"' in quorum_text, (
        "quorum.md doesn't read .uat-responses.json `rcrurdr` section"
    )
    # Must filter on verdict == "f"
    assert re.search(r'verdict.*[=]=.*"f"', quorum_text), (
        "quorum.md doesn't filter rcrurdr items on verdict == 'f'"
    )
    # Must BLOCK with exit 1
    assert re.search(
        r'RCRURD_FAILED_COUNT.*-gt\s+0',
        quorum_text, re.DOTALL,
    ) or "RCRURD_FAILED" in quorum_text, (
        "quorum.md doesn't compare failed count > 0"
    )
    assert "accept.uat_rcrurdr_blocked" in quorum_text, (
        "quorum.md missing accept.uat_rcrurdr_blocked telemetry event"
    )


def test_quorum_allows_passed_rcrurd(quorum_text):
    """When all RCRURD items pass (verdict == 'p'), quorum gate must NOT
    block — flow continues to mark-step + emit pass event."""
    # The passing path must still emit accept.uat_quorum_passed
    assert "accept.uat_quorum_passed" in quorum_text, (
        "quorum.md missing accept.uat_quorum_passed telemetry event"
    )
    # The pass event payload should include rcrurdr_failed counter so a
    # passed gate (count=0) can be distinguished from a not-applicable
    # phase (no rcrurdr section). This proves the gate considered the data.
    assert re.search(r'rcrurdr_failed', quorum_text), (
        "accept.uat_quorum_passed payload should include rcrurdr_failed counter"
    )


def test_quorum_override_flag_path(quorum_text):
    """--allow-failed-rcrurdr-attestation override must:
    - require --override-reason
    - run rationalization-guard
    - emit canonical override.used (vg-orchestrator override)
    - log to override-debt
    - force verdict=DEFER (not ACCEPT)
    """
    assert "--allow-failed-rcrurdr-attestation" in quorum_text, (
        "quorum.md missing --allow-failed-rcrurdr-attestation override flag"
    )
    # Must require --override-reason
    assert re.search(
        r"--allow-failed-rcrurdr-attestation requires --override-reason",
        quorum_text,
    ), (
        "quorum.md doesn't enforce --override-reason on RCRURDR override"
    )
    # Must call vg-orchestrator override (canonical override.used)
    assert re.search(
        r'vg-orchestrator\s+override.*--flag\s+"--allow-failed-rcrurdr-attestation"',
        quorum_text, re.DOTALL,
    ), (
        "quorum.md doesn't fire canonical `vg-orchestrator override --flag`"
    )
    # Must log to override-debt
    assert "log_override_debt" in quorum_text, "quorum.md missing log_override_debt call"
    # Must force DEFER (not ACCEPT)
    assert "uat_rcrurdr_override" in quorum_text, (
        "quorum.md doesn't tag forced_by=uat_rcrurdr_override on DEFER"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Frontmatter — override flag declared
# ─────────────────────────────────────────────────────────────────────────────

def test_override_flag_in_frontmatter(accept_text):
    """accept.md frontmatter `forbidden_without_override` must declare
    `--allow-failed-rcrurdr-attestation` so contract enforcement fires."""
    # Parse frontmatter region (between first two --- markers)
    fm_match = re.match(r"^---\n(.+?)\n---\n", accept_text, re.DOTALL)
    assert fm_match, "accept.md missing frontmatter"
    frontmatter = fm_match.group(1)

    # forbidden_without_override list must include the new flag.
    # Match the list block: each item is `    - "<flag>"` on its own line.
    # Use lookahead for newline-or-end so the final list item (which may
    # not have a trailing newline if frontmatter ends with `---`) is still
    # captured.
    forbidden_block = re.search(
        r"forbidden_without_override:\s*\n((?:\s+-\s+\"[^\"]+\"(?:\n|$))+)",
        frontmatter,
    )
    assert forbidden_block is not None, (
        "accept.md frontmatter missing forbidden_without_override list"
    )
    block = forbidden_block.group(1)
    assert "--allow-failed-rcrurdr-attestation" in block, (
        "accept.md `forbidden_without_override` doesn't list "
        "--allow-failed-rcrurdr-attestation"
    )

    # argument-hint should also surface the flag for users
    assert "--allow-failed-rcrurdr-attestation" in frontmatter, (
        "accept.md argument-hint doesn't mention "
        "--allow-failed-rcrurdr-attestation"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Mirror parity — .claude/ and source must stay in sync
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("relpath", [
    "commands/vg/accept.md",
    "commands/vg/_shared/accept/uat/interactive.md",
    "commands/vg/_shared/accept/uat/quorum.md",
    "commands/vg/_shared/accept/uat/checklist-build/overview.md",
    "commands/vg/_shared/accept/uat/checklist-build/delegation.md",
    "agents/vg-accept-uat-builder/SKILL.md",
])
def test_mirror_parity_with_dotclaude(relpath):
    """Source under `commands/` (or `agents/`) must match the `.claude/`
    mirror byte-for-byte so the runtime sees the same instructions."""
    src = REPO_ROOT / relpath
    mirror = REPO_ROOT / ".claude" / relpath
    assert src.exists(), f"source missing: {src}"
    assert mirror.exists(), f"mirror missing: {mirror}"
    assert src.read_bytes() == mirror.read_bytes(), (
        f"R8-D mirror drift: {relpath} differs between source and .claude/"
    )
