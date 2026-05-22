"""B97 v4.69.0 — issue #200 + #201 + #202 goal_class trio.

Three tightly coupled fixes to align generator + validator semantics
around `goal_class` enum.

## #200 — generate-deep-test-specs.py infers goal_class when blank

PrintwayV3 Phase 8.2 R3: 206 goals emitted into LIFECYCLE-SPECS.json.
85 had stage-shape ≠ full RCRURDR but `goal_class` blank because
TEST-GOALS.md authors omitted the field. Downstream validator defaulted
to strictest contract → 85 `lifecycle_stage_missing` evidences → BLOCK.

Fix: `_infer_goal_class(stages)` reverse-maps emitted stage set to
canonical enum value. `_goal_spec` consults declared goal_class first,
infers when blank, emits `effective_goal_class` + tags
`_b97_goal_class_inferred` for audit. `generator_note` appends
"B97-inferred goal_class: <value>" when inference fired.

## #201 — verify-lifecycle-spec-depth.py respects explicit goal_class

Pre-B97: `_needs_lifecycle` returned True for ANY goal whose
mutation_evidence non-empty OR SIDE_EFFECT_WORD_RE matched (catches
"approve|reject|update|delete|create..."). Then `missing =
[s for s in REQUIRED_STAGES if ...]` always used FULL RCRURDR check
→ 3-stage create-only goal flagged as missing update/delete.

Fix: new `REQUIRED_STAGES_BY_CLASS` map + `_required_stages_for(goal)`
helper. When goal_class declares non-mutation subset, validator
enforces ONLY that subset. Evidence type renamed `class_stages_missing`
(was `rcrurdr_stages_missing`) when class-specific check fires.

## #202 — verify-decision-to-spec-coverage.py accepts spec_file field

Writer (generate-deep-test-specs.py + vg-test-codegen subagent + light
manifest writers) writes `playwright_specs[].spec_file`. Reader pre-B97
only checked `entry.get("path")` → returned None → fallback glob fired
→ `⛔ Batch 38: no spec files found`. Fix: accept `spec_file` (canonical)
OR `path` OR `file` field.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO_ROOT / "scripts" / "generate-lifecycle-specs.py"
DEPTH_VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-lifecycle-spec-depth.py"
COVERAGE_VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-decision-to-spec-coverage.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("lc", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def depth():
    spec = importlib.util.spec_from_file_location("depth", DEPTH_VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# #200: generator infers goal_class
# ---------------------------------------------------------------------------

def test_b97_infer_readonly_from_stages(lc) -> None:
    inferred = lc._infer_goal_class(lc.GOAL_TYPE_STAGES["read-only"])
    assert inferred == "readonly"


def test_b97_infer_create_only(lc) -> None:
    inferred = lc._infer_goal_class(lc.GOAL_TYPE_STAGES["create-only"])
    assert inferred == "create-only"


def test_b97_infer_update_only(lc) -> None:
    inferred = lc._infer_goal_class(lc.GOAL_TYPE_STAGES["update-only"])
    assert inferred == "update-only"


def test_b97_infer_delete_only(lc) -> None:
    inferred = lc._infer_goal_class(lc.GOAL_TYPE_STAGES["delete-only"])
    assert inferred == "delete-only"


def test_b97_infer_mutation_rcrurdr(lc) -> None:
    inferred = lc._infer_goal_class(lc.REQUIRED_STAGES)
    assert inferred == "mutation"


def test_b97_infer_feature_chain(lc) -> None:
    inferred = lc._infer_goal_class(lc.FEATURE_CHAIN_STAGES)
    assert inferred == "feature_chain"


def test_b97_infer_unknown_stages_returns_empty(lc) -> None:
    weird = ("read_before", "delete", "create")  # not a known shape
    assert lc._infer_goal_class(weird) == ""


def test_b97_goal_spec_emits_inferred_class_when_blank(lc) -> None:
    """Goal without goal_class but read-only title → emit goal_class='readonly'."""
    goal = {
        "id": "G-001",
        "title": "List approved topups",
        "body": "## Goal\n\nList topups\n",
        "goal_type": "",
        "goal_class": "",  # blank — should infer
    }
    spec = lc._goal_spec(goal)
    assert spec["goal_class"] == "readonly"
    assert "B97-inferred" in spec["generator_note"]


def test_b97_goal_spec_preserves_declared_class(lc) -> None:
    """Declared goal_class wins — no inference override."""
    goal = {
        "id": "G-001",
        "title": "List approved topups",
        "body": "## Goal\n\nList topups\n",
        "goal_type": "",
        "goal_class": "mutation",  # declared explicitly — should NOT change
    }
    spec = lc._goal_spec(goal)
    assert spec["goal_class"] == "mutation"
    assert "B97-inferred" not in spec["generator_note"]


def test_b97_summary_counts_inferred(lc, tmp_path: Path) -> None:
    pdir = tmp_path / "08.2-test"
    pdir.mkdir()
    (pdir / "TEST-GOALS.md").write_text(
        "## Goal G-001: List approved topups\n\n(infer readonly)\n\n"
        "## Goal G-002: Display dashboard\n\n(infer readonly)\n\n"
        "## Goal G-003: Create topup\n\n"
        "goal_type: mutation\n"
        "mutation_evidence: POST /api/v1/admin/topups\n"
        "persistence_check: GET returns row\n",
        encoding="utf-8",
    )
    payload = lc.generate(pdir, include_readonly=True)
    assert payload["summary"]["goal_class_inferred_count"] >= 2


# ---------------------------------------------------------------------------
# #201: validator respects explicit goal_class
# ---------------------------------------------------------------------------

def test_b97_required_stages_for_class_lookup(depth) -> None:
    assert depth._required_stages_for({"goal_class": "create-only"}) == \
        ("read_before", "create", "read_after_create")
    assert depth._required_stages_for({"goal_class": "readonly"}) == \
        ("read_before",)
    assert depth._required_stages_for({"goal_class": "delete-only"}) == \
        ("read_before", "delete", "read_after_delete")


def test_b97_required_stages_falls_back_to_full_rcrurdr(depth) -> None:
    """Goals without explicit class → full RCRURDR."""
    assert depth._required_stages_for({"goal_class": ""}) == depth.REQUIRED_STAGES
    assert depth._required_stages_for({"goal_class": "mutation"}) == depth.REQUIRED_STAGES


def test_b97_required_stages_unknown_class_falls_back(depth) -> None:
    """Unknown class → full RCRURDR (don't silently accept arbitrary)."""
    assert depth._required_stages_for({"goal_class": "garbage-class"}) == depth.REQUIRED_STAGES


def test_b97_needs_lifecycle_keeps_validating_class_subset(depth) -> None:
    """Explicit create-only still goes through validator (per-class subset)."""
    assert depth._needs_lifecycle({"goal_class": "create-only"}) is True
    assert depth._needs_lifecycle({"goal_class": "readonly"}) is True


# ---------------------------------------------------------------------------
# #202: spec_file field accepted alongside path
# ---------------------------------------------------------------------------

def test_b97_coverage_validator_accepts_spec_file_field(tmp_path: Path) -> None:
    """playwright_specs[].spec_file should be honored (currently the
    canonical writer field, per generate-deep-test-specs.py + vg-test-codegen)."""
    phase = tmp_path / "08.2-test"
    phase.mkdir()
    spec_file = phase / "test.spec.ts"
    spec_file.write_text("// test", encoding="utf-8")
    (phase / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({
            "playwright_specs": [
                {"spec_file": str(spec_file), "goal_id": "G-001", "lens": "happy-path"},
            ],
        }),
        encoding="utf-8",
    )
    # Use the validator's _spec_files() to verify resolution
    spec = importlib.util.spec_from_file_location("cov", COVERAGE_VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    found = mod._spec_files(phase)
    assert len(found) == 1
    assert found[0].name == "test.spec.ts"


def test_b97_coverage_validator_accepts_path_field_still(tmp_path: Path) -> None:
    """Backward compat: `path` field must still work."""
    phase = tmp_path / "08.2-test"
    phase.mkdir()
    spec_file = phase / "test.spec.ts"
    spec_file.write_text("// test", encoding="utf-8")
    (phase / "CODEGEN-MANIFEST.json").write_text(
        json.dumps({"playwright_specs": [{"path": str(spec_file), "goal_id": "G-001"}]}),
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location("cov", COVERAGE_VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    found = mod._spec_files(phase)
    assert len(found) == 1


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b97_lifecycle_mirror_parity() -> None:
    a = LIFECYCLE.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "generate-lifecycle-specs.py").read_bytes()
    assert a == b


def test_b97_depth_validator_mirror_parity() -> None:
    a = DEPTH_VALIDATOR.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-lifecycle-spec-depth.py").read_bytes()
    assert a == b


def test_b97_coverage_validator_mirror_parity() -> None:
    a = COVERAGE_VALIDATOR.read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-decision-to-spec-coverage.py").read_bytes()
    assert a == b
