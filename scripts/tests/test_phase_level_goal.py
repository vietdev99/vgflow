"""
R8-C — Phase-level TEST-GOAL (G-PHASE-NN) gate.

Codex closed-loop audit (2026-05-05) found phase-level TEST-GOAL MISSING:
component goals (G-XX) verify per-feature behavior but no goal asserts
the WHOLE phase delivers user-visible value end-to-end. This test
suite pins the 6-layer wiring:

  1. Schema — TEST-GOAL-enriched-template documents G-PHASE-NN class
  2. Generation — blueprint contracts-delegation emits G-PHASE-NN per
     user journey from CONTEXT ## Goals
  3. Validator — verify-phase-goal-coverage.py BLOCKs orphan child
     goal or uncovered CONTEXT goal
  4. Codegen — test codegen delegation + vg-test-codegen SKILL document
     per-phase Playwright spec emission
  5. Review verdict — phase READY requires G-PHASE-NN runtime evidence
  6. UAT quorum — PHASE-G-PHASE-NN critical item; failed → BLOCK

Mirror parity: all modified files MUST be byte-identical between
canonical (commands/, scripts/, agents/) and `.claude/` mirror, except
review/verdict/ which is canonical-only by convention.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _resolve_repo_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in [here, *here.parents]:
        if (ancestor / "commands" / "vg").is_dir() and (
            ancestor / ".claude" / "commands" / "vg"
        ).is_dir():
            return ancestor
    return here.parents[3]


REPO_ROOT = _resolve_repo_root()

TEMPLATE_CANONICAL = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "templates"
    / "TEST-GOAL-enriched-template.md"
)
TEMPLATE_MIRROR = (
    REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "templates"
    / "TEST-GOAL-enriched-template.md"
)

CONTRACTS_DELEGATION_CANONICAL = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "contracts-delegation.md"
)
CONTRACTS_DELEGATION_MIRROR = (
    REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "blueprint"
    / "contracts-delegation.md"
)

VERIFY_BLUEPRINT_CANONICAL = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "verify.md"
)
VERIFY_BLUEPRINT_MIRROR = (
    REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "verify.md"
)

CODEGEN_DELEGATION_CANONICAL = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"
)
CODEGEN_DELEGATION_MIRROR = (
    REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "test" / "codegen"
    / "delegation.md"
)

CODEGEN_SKILL_CANONICAL = REPO_ROOT / "agents" / "vg-test-codegen" / "SKILL.md"
CODEGEN_SKILL_MIRROR = REPO_ROOT / ".claude" / "agents" / "vg-test-codegen" / "SKILL.md"

UAT_BUILDER_CANONICAL = REPO_ROOT / "agents" / "vg-accept-uat-builder" / "SKILL.md"
UAT_BUILDER_MIRROR = REPO_ROOT / ".claude" / "agents" / "vg-accept-uat-builder" / "SKILL.md"

UAT_QUORUM_CANONICAL = REPO_ROOT / "commands" / "vg" / "_shared" / "accept" / "uat" / "quorum.md"
UAT_QUORUM_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "accept" / "uat" / "quorum.md"

REVIEW_VERDICT_CANONICAL = (
    REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "verdict" / "overview.md"
)

VALIDATOR_CANONICAL = (
    REPO_ROOT / "scripts" / "validators" / "verify-phase-goal-coverage.py"
)
VALIDATOR_MIRROR = (
    REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-phase-goal-coverage.py"
)


# ─── LAYER 1: Schema (template) ───────────────────────────────────────────


def test_template_documents_phase_goal_class():
    """Template MUST document goal_class: phase-happy-path schema."""
    body = TEMPLATE_CANONICAL.read_text(encoding="utf-8")
    assert "G-PHASE-NN" in body, (
        "TEST-GOAL-enriched-template.md missing G-PHASE-NN documentation"
    )
    assert "phase-happy-path" in body, (
        "Template missing goal_class: phase-happy-path"
    )
    # Required schema fields
    for field in ("children", "postcondition", "rcrurdr_required"):
        assert field in body, (
            f"Phase-goal schema field {field!r} not documented in template"
        )


def test_template_phase_goal_schema_has_required_fields():
    """Template MUST list children + postcondition as REQUIRED fields."""
    body = TEMPLATE_CANONICAL.read_text(encoding="utf-8")
    # Find phase-goal section — extends to end of file (last section)
    section_match = re.search(
        r"##\s+Phase-level goal class[\s\S]*",
        body,
    )
    assert section_match, "Phase-level goal class section missing"
    section = section_match.group(0)
    assert "REQUIRED" in section, (
        "Phase-goal section must mark fields REQUIRED"
    )
    assert "ordered child goal IDs" in section or "ordered" in section, (
        "Phase-goal section must specify children[] is ordered"
    )


# ─── LAYER 2: Generation (blueprint contracts-delegation) ─────────────────


def test_blueprint_contracts_delegation_documents_phase_goal_generation():
    """contracts-delegation.md MUST document G-PHASE-NN generation step."""
    body = CONTRACTS_DELEGATION_CANONICAL.read_text(encoding="utf-8")
    assert "G-PHASE-NN" in body, (
        "contracts-delegation.md missing G-PHASE-NN generation rule"
    )
    assert "Phase-level goals" in body, (
        "contracts-delegation.md must have a Phase-level goals subsection"
    )
    # Required procedure elements
    assert "user journey" in body.lower(), (
        "Phase-goal generation should reference user journey heuristic"
    )
    assert "context_goal_ref" in body, (
        "Phase-goal generation must produce context_goal_ref linkage"
    )


def test_blueprint_contracts_return_json_includes_phase_goal_count():
    """Return JSON envelope MUST include phase_goal_count + phase_goal_sub_files."""
    body = CONTRACTS_DELEGATION_CANONICAL.read_text(encoding="utf-8")
    assert '"phase_goal_count"' in body, (
        "Return JSON must declare phase_goal_count field"
    )
    assert '"phase_goal_sub_files"' in body, (
        "Return JSON must declare phase_goal_sub_files field"
    )


# ─── LAYER 3: Validator wiring + behavior ─────────────────────────────────


def test_validator_file_exists_and_executable():
    """verify-phase-goal-coverage.py MUST exist and be executable."""
    assert VALIDATOR_CANONICAL.exists(), (
        f"Validator missing at {VALIDATOR_CANONICAL}"
    )
    assert os.access(VALIDATOR_CANONICAL, os.X_OK), (
        f"Validator not executable: {VALIDATOR_CANONICAL}"
    )


def test_validator_smoketest_missing_phase_returns_warn():
    """Validator on non-existent phase MUST return WARN (not error)."""
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR_CANONICAL), "--phase", "99999"],
        capture_output=True, text=True, timeout=10,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["verdict"] == "WARN", out


def _setup_fake_phase(
    tmp_path: Path,
    *,
    phase: str = "test-phase",
    context_md: str = "",
    goal_files: dict[str, str] | None = None,
    crud_md: str = "",
) -> Path:
    """Create a minimal repo with one phase + given TEST-GOALS and CONTEXT."""
    phase_dir = tmp_path / ".vg" / "phases" / phase
    phase_dir.mkdir(parents=True)
    if context_md:
        (phase_dir / "CONTEXT.md").write_text(context_md, encoding="utf-8")
    if crud_md:
        (phase_dir / "CRUD-SURFACES.md").write_text(crud_md, encoding="utf-8")
    if goal_files:
        goals_dir = phase_dir / "TEST-GOALS"
        goals_dir.mkdir(parents=True)
        for name, body in goal_files.items():
            (goals_dir / name).write_text(body, encoding="utf-8")
    return tmp_path


def _run_validator(repo: Path, phase: str, *extra: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR_CANONICAL), "--phase", phase, *extra],
        capture_output=True, text=True, cwd=repo, env=env, timeout=15,
    )
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        data = {"verdict": "ERROR", "raw_stdout": proc.stdout, "raw_stderr": proc.stderr}
    return proc.returncode, data


CONTEXT_SITE_MGMT = """\
# Phase 4.1 — Site Management — CONTEXT

## Goals

### In-scope
- Publisher manages sites end-to-end (CRUD + list)

### Out-of-scope
- Bulk import deferred

## Decisions

### P4.1.D-01: Site CRUD
**Decision:** ...
"""

GOAL_G04 = """\
---
id: G-04
goal_class: mutation
priority: critical
---

# G-04: Create site
"""

GOAL_G05 = """\
---
id: G-05
goal_class: readonly
priority: important
---

# G-05: List sites
"""

GOAL_PHASE_OK = """\
---
id: G-PHASE-01
goal_class: phase-happy-path
priority: critical
children:
  - G-04
  - G-05
postcondition: |
  Publisher creates site, lists sites, sees new site in list
context_goal_ref: |
  "Publisher manages sites end-to-end (CRUD + list)"
---

# Phase happy path — Site management

## Steps
1. (G-04) Create site
2. (G-05) View list

## Postcondition
User can manage sites end-to-end.
"""


def test_validator_passes_with_complete_phase_goal(tmp_path):
    """All bullets covered + all G-XX in children + valid schema = PASS."""
    repo = _setup_fake_phase(
        tmp_path,
        phase="04.1-site-management",
        context_md=CONTEXT_SITE_MGMT,
        goal_files={
            "G-04.md": GOAL_G04,
            "G-05.md": GOAL_G05,
            "G-PHASE-01.md": GOAL_PHASE_OK,
        },
    )
    rc, data = _run_validator(repo, "04.1")
    assert rc == 0, data
    assert data["verdict"] in ("PASS", "WARN"), data


def test_validator_blocks_orphan_component_goal(tmp_path):
    """Component G-XX not listed in any G-PHASE-NN.children[] = BLOCK."""
    # G-PHASE-01 only lists G-04, but G-05 + G-06 are orphans
    GOAL_G06 = "---\nid: G-06\ngoal_class: mutation\n---\n\n# G-06"
    GOAL_PHASE_PARTIAL = """\
---
id: G-PHASE-01
goal_class: phase-happy-path
priority: critical
children:
  - G-04
  - G-05
postcondition: |
  Publisher manages sites
context_goal_ref: |
  "Publisher manages sites end-to-end"
---
"""
    repo = _setup_fake_phase(
        tmp_path,
        phase="04.1-site-management",
        context_md=CONTEXT_SITE_MGMT,
        goal_files={
            "G-04.md": GOAL_G04,
            "G-05.md": GOAL_G05,
            "G-06.md": GOAL_G06,
            "G-PHASE-01.md": GOAL_PHASE_PARTIAL,
        },
    )
    rc, data = _run_validator(repo, "04.1")
    assert rc == 1, data
    assert data["verdict"] == "BLOCK", data
    types = {e.get("type") for e in data["evidence"]}
    assert "component_goal_orphan" in types, data


def test_validator_blocks_uncovered_context_bullet(tmp_path):
    """CONTEXT in-scope bullet without any phase-goal coverage = BLOCK."""
    CONTEXT_TWO_BULLETS = """\
# Phase test

## Goals

### In-scope
- Publisher manages sites end-to-end (CRUD + list)
- Admin reviews approval queue

### Out-of-scope
- None

## Decisions
"""
    # Phase-goal only covers first bullet
    repo = _setup_fake_phase(
        tmp_path,
        phase="04.1-site-management",
        context_md=CONTEXT_TWO_BULLETS,
        goal_files={
            "G-04.md": GOAL_G04,
            "G-05.md": GOAL_G05,
            "G-PHASE-01.md": GOAL_PHASE_OK,
        },
    )
    rc, data = _run_validator(repo, "04.1")
    assert rc == 1, data
    assert data["verdict"] == "BLOCK", data
    types = {e.get("type") for e in data["evidence"]}
    assert "context_goal_uncovered" in types, data


def test_validator_blocks_when_no_phase_goal_emitted(tmp_path):
    """Component G-XX exist but 0 G-PHASE-NN = BLOCK."""
    repo = _setup_fake_phase(
        tmp_path,
        phase="04.1-site-management",
        context_md=CONTEXT_SITE_MGMT,
        goal_files={
            "G-04.md": GOAL_G04,
            "G-05.md": GOAL_G05,
        },
    )
    rc, data = _run_validator(repo, "04.1")
    assert rc == 1, data
    assert data["verdict"] == "BLOCK", data
    types = {e.get("type") for e in data["evidence"]}
    assert "phase_goal_none_emitted" in types, data


def test_validator_blocks_phase_goal_with_invalid_schema(tmp_path):
    """G-PHASE-NN missing goal_class or postcondition = BLOCK."""
    GOAL_PHASE_BROKEN = """\
---
id: G-PHASE-01
goal_class: mutation
priority: critical
children:
  - G-04
  - G-05
---
"""
    repo = _setup_fake_phase(
        tmp_path,
        phase="04.1-site-management",
        context_md=CONTEXT_SITE_MGMT,
        goal_files={
            "G-04.md": GOAL_G04,
            "G-05.md": GOAL_G05,
            "G-PHASE-01.md": GOAL_PHASE_BROKEN,
        },
    )
    rc, data = _run_validator(repo, "04.1")
    assert rc == 1, data
    assert data["verdict"] == "BLOCK", data
    types = {e.get("type") for e in data["evidence"]}
    assert "phase_goal_class_invalid" in types or "phase_goal_postcondition_empty" in types, data


def test_validator_skips_when_phase_has_no_crud_reason(tmp_path):
    """Phase with no_crud_reason in CRUD-SURFACES.md is exempt."""
    CRUD_NONE = """\
# CRUD Surfaces

```json
{
  "version": "1",
  "no_crud_reason": "infra-only phase, no user resources",
  "resources": []
}
```
"""
    repo = _setup_fake_phase(
        tmp_path,
        phase="04.1-site-management",
        context_md=CONTEXT_SITE_MGMT,
        goal_files={"G-04.md": GOAL_G04},
        crud_md=CRUD_NONE,
    )
    rc, data = _run_validator(repo, "04.1")
    # Skipping = WARN only (not BLOCK)
    assert rc == 0, data
    assert data["verdict"] == "WARN", data
    types = {e.get("type") for e in data["evidence"]}
    assert "skipped_no_crud" in types, data


def test_validator_override_demotes_block_to_warn(tmp_path):
    """--allow-phase-goal-incomplete + --override-reason = BLOCK→WARN."""
    repo = _setup_fake_phase(
        tmp_path,
        phase="04.1-site-management",
        context_md=CONTEXT_SITE_MGMT,
        goal_files={"G-04.md": GOAL_G04, "G-05.md": GOAL_G05},
    )
    rc, data = _run_validator(
        repo, "04.1",
        "--allow-phase-goal-incomplete",
        "--override-reason", "scaffolding-only phase, defer phase-goal",
    )
    assert rc == 0, data
    assert data["verdict"] == "WARN", data
    types = {e.get("type") for e in data["evidence"]}
    assert "override_applied" in types, data


# ─── LAYER 3b: Validator wired into blueprint verify ──────────────────────


def test_blueprint_verify_invokes_phase_goal_validator():
    """blueprint/verify.md MUST invoke verify-phase-goal-coverage.py."""
    body = VERIFY_BLUEPRINT_CANONICAL.read_text(encoding="utf-8")
    assert "verify-phase-goal-coverage.py" in body, (
        "blueprint/verify.md does not invoke verify-phase-goal-coverage.py"
    )
    assert "phase-goal-coverage" in body, (
        "blueprint/verify.md missing phase-goal-coverage validator label"
    )
    assert "--allow-phase-goal-incomplete" in body, (
        "blueprint/verify.md missing override flag for phase-goal validator"
    )


# ─── LAYER 4: Codegen — phase E2E spec emission ───────────────────────────


def test_test_codegen_delegation_documents_phase_spec_emission():
    """test/codegen/delegation.md MUST document G-PHASE-NN spec emission."""
    body = CODEGEN_DELEGATION_CANONICAL.read_text(encoding="utf-8")
    assert "G-PHASE-NN" in body, (
        "codegen delegation must document G-PHASE-NN spec emission"
    )
    assert ".phase.spec.ts" in body, (
        "codegen must emit phase specs at <slug>.phase.spec.ts"
    )
    assert "expectLifecycleRoundtrip" in body, (
        "phase spec must call expectLifecycleRoundtrip when rcrurdr_required"
    )
    assert "children" in body.lower(), (
        "phase spec must run children in declared order"
    )


def test_test_codegen_skill_documents_phase_spec_contract():
    """vg-test-codegen SKILL must document phase-spec emission contract."""
    body = CODEGEN_SKILL_CANONICAL.read_text(encoding="utf-8")
    assert "G-PHASE-NN" in body or "phase-level spec" in body.lower(), (
        "vg-test-codegen SKILL must document phase-spec contract"
    )
    assert "phase_spec_files" in body, (
        "Return JSON must include phase_spec_files[] field"
    )
    assert "phase_goal_count" in body, (
        "Return JSON must include phase_goal_count field"
    )


# ─── LAYER 5: Review verdict — phase goal gating ──────────────────────────


def test_review_verdict_documents_phase_goal_runtime_gate():
    """review/verdict/overview.md MUST gate on G-PHASE-NN runtime evidence."""
    body = REVIEW_VERDICT_CANONICAL.read_text(encoding="utf-8")
    assert "G-PHASE-" in body, (
        "review verdict must reference G-PHASE-NN goals"
    )
    assert ".runs/" in body or "runtime evidence" in body.lower(), (
        "review verdict must check phase-goal runtime evidence dir"
    )
    assert "--allow-phase-goal-incomplete" in body, (
        "review verdict must offer --allow-phase-goal-incomplete override"
    )


# ─── LAYER 6: UAT — phase goal item ───────────────────────────────────────


def test_uat_builder_skill_documents_phase_goal_item():
    """vg-accept-uat-builder MUST emit PHASE-G-PHASE-NN items."""
    body = UAT_BUILDER_CANONICAL.read_text(encoding="utf-8")
    assert "PHASE-G-PHASE-" in body, (
        "uat-builder must emit PHASE-G-PHASE-NN items"
    )
    assert "phase happy path" in body.lower() or "phase happy-path" in body.lower(), (
        "uat-builder must use 'phase happy path' phrasing for PHASE items"
    )
    assert "CRITICAL" in body, (
        "PHASE-G-PHASE-NN items must be marked CRITICAL"
    )


def test_uat_quorum_blocks_on_failed_phase_goal():
    """uat/quorum.md MUST BLOCK on failed PHASE-G-PHASE-NN attestation."""
    body = UAT_QUORUM_CANONICAL.read_text(encoding="utf-8")
    assert "PHASE-G-PHASE-" in body, (
        "uat quorum must check PHASE-G-PHASE-NN items"
    )
    assert "--allow-failed-phase-goal-attestation" in body, (
        "uat quorum must offer --allow-failed-phase-goal-attestation override"
    )
    assert "phase_goal_failed" in body or "phase-goal" in body.lower(), (
        "uat quorum must emit telemetry for phase-goal failures"
    )


# ─── Mirror parity (canonical ↔ .claude) ─────────────────────────────────


@pytest.mark.parametrize(
    "canonical,mirror",
    [
        (TEMPLATE_CANONICAL, TEMPLATE_MIRROR),
        (CONTRACTS_DELEGATION_CANONICAL, CONTRACTS_DELEGATION_MIRROR),
        (VERIFY_BLUEPRINT_CANONICAL, VERIFY_BLUEPRINT_MIRROR),
        (CODEGEN_DELEGATION_CANONICAL, CODEGEN_DELEGATION_MIRROR),
        (CODEGEN_SKILL_CANONICAL, CODEGEN_SKILL_MIRROR),
        (UAT_BUILDER_CANONICAL, UAT_BUILDER_MIRROR),
        (UAT_QUORUM_CANONICAL, UAT_QUORUM_MIRROR),
        (VALIDATOR_CANONICAL, VALIDATOR_MIRROR),
    ],
)
def test_mirror_parity(canonical: Path, mirror: Path):
    """Canonical and .claude mirror MUST be byte-identical."""
    if not mirror.exists():
        pytest.fail(f"Mirror missing: {mirror}")
    assert canonical.read_bytes() == mirror.read_bytes(), (
        f"Mirror drift: {canonical.relative_to(REPO_ROOT)} != "
        f"{mirror.relative_to(REPO_ROOT)} — re-run install/sync."
    )
