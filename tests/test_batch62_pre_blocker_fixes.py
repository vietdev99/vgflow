"""tests/test_batch62_pre_blocker_fixes.py — B62-pre (audit BLOCKERs ID-1, ID-2).

Codex audit (dev-phases/feature-chain-design/CODEX-AUDIT.md) identified 2
BLOCKERs that would make B62 silent no-op:

ID-1: `goal_class` not the dispatch key — `_stages_for_goal` reads
      `goal_type` only. Plan adds feature_chain to goal_class enum but
      pipeline ignores it.

ID-2: `enables[]` vs `Dependencies[]` symmetry undefined — FLOW-SPEC
      walker would loop / double-count chains.

Fix:
  - generate-lifecycle-specs.py: add GOAL_CLASS_STAGES + FEATURE_CHAIN_STAGES,
    dispatch precedence goal_class > goal_type > HTTP-verb inference.
  - verify-enables-deps-symmetry.py: new validator enforces A.enables=[B]
    implies B.Dependencies contains A.
  - contracts-overview.md FLOW-SPEC walker: documented truth-source rule
    (Dependencies[] canonical; enables[] validated by symmetry validator,
    NOT walked here to avoid double-traversal).

Coverage:
  1. goal_class=feature_chain returns FEATURE_CHAIN_STAGES (contains
     visibility_check)
  2. goal_type=create-only still works (back-compat)
  3. goal_class wins over goal_type (precedence)
  4. unknown goal_class falls through to goal_type
  5. neither set → HTTP-verb inference still works
  6. Symmetry validator PASS when A.enables=[B] + B.Deps=[A]
  7. Symmetry validator FAIL strict on asymmetry
  8. Symmetry validator handles no TEST-GOALS.md gracefully
  9. Symmetry validator handles enables targeting missing goal
  10. FEATURE_CHAIN_STAGES contains all required stages
  11. contracts-overview FLOW-SPEC walker has truth-source doc
  12. Mirror parity for new validator
"""
from __future__ import annotations
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO / "scripts" / "generate-lifecycle-specs.py"
LIFECYCLE_MIRROR = REPO / ".claude" / "scripts" / "generate-lifecycle-specs.py"
VAL = REPO / "scripts" / "validators" / "verify-enables-deps-symmetry.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-enables-deps-symmetry.py"
CONTRACTS = REPO / "commands" / "vg" / "_shared" / "blueprint" / "contracts-overview.md"
CONTRACTS_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "contracts-overview.md"


def _load_lifecycle_module():
    spec = importlib.util.spec_from_file_location("gls", LIFECYCLE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gls"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_goal_class_feature_chain_returns_chain_stages():
    mod = _load_lifecycle_module()
    stages = mod._stages_for_goal({"goal_class": "feature_chain"})
    assert "visibility_check" in stages, (
        "B62-pre ID-1: goal_class=feature_chain must dispatch to FEATURE_CHAIN_STAGES"
    )
    assert "cascade_check" in stages
    assert "archive_visibility_check" in stages


def test_goal_class_post_create_cascade_alias():
    mod = _load_lifecycle_module()
    stages = mod._stages_for_goal({"goal_class": "post_create_cascade"})
    assert "visibility_check" in stages  # alias maps to FEATURE_CHAIN_STAGES


def test_goal_type_backcompat():
    """Existing goal_type dispatch unchanged."""
    mod = _load_lifecycle_module()
    stages = mod._stages_for_goal({"goal_type": "create-only"})
    assert stages == ("read_before", "create", "read_after_create")


def test_goal_class_wins_over_goal_type():
    """Precedence rule: goal_class > goal_type."""
    mod = _load_lifecycle_module()
    stages = mod._stages_for_goal({
        "goal_class": "feature_chain",
        "goal_type": "create-only",
    })
    # FEATURE_CHAIN_STAGES has 11 stages; create-only has 3
    assert len(stages) > 5
    assert "visibility_check" in stages


def test_unknown_goal_class_falls_through_to_goal_type():
    mod = _load_lifecycle_module()
    stages = mod._stages_for_goal({
        "goal_class": "some_unknown_class",
        "goal_type": "read-only",
    })
    # Falls through to goal_type → READONLY_STAGES (8 stages)
    assert "render_initial" in stages


def test_no_dispatch_keys_falls_to_verb_inference():
    """Neither goal_class nor goal_type → HTTP-verb inference."""
    mod = _load_lifecycle_module()
    stages = mod._stages_for_goal({
        "mutation_evidence": "POST /api/sites returns 201",
    })
    # POST detected → create-only
    assert stages == ("read_before", "create", "read_after_create")


def test_symmetry_validator_passes_on_consistent(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "TEST-GOALS.md").write_text(
        "## G-01 - Create\n"
        "- **Dependencies:** []\n"
        "- enables: [G-02]\n\n"
        "## G-02 - View\n"
        "- **Dependencies:** [G-01]\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(pd), "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


def test_symmetry_validator_fails_on_asymmetric(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "TEST-GOALS.md").write_text(
        "## G-01 - Create\n"
        "- enables: [G-02]\n\n"
        "## G-02 - View\n"
        "- **Dependencies:** []\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(pd), "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode != 0
    assert "ASYMMETRY" in (r.stderr + r.stdout)


def test_symmetry_validator_handles_missing_goals_file(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(pd), "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0  # skip gracefully


def test_symmetry_validator_flags_enables_to_unknown_goal(tmp_path):
    pd = tmp_path / "phases" / "7"
    pd.mkdir(parents=True)
    (pd / "TEST-GOALS.md").write_text(
        "## G-01 - Create\n"
        "- enables: [G-99]\n",  # G-99 doesn't exist
        encoding="utf-8",
    )
    r = subprocess.run(
        ["python", str(VAL), "--phase", "7", "--phase-dir", str(pd), "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode != 0
    assert "G-99" in (r.stderr + r.stdout)


def test_feature_chain_stages_completeness():
    """FEATURE_CHAIN_STAGES contains all required stage names."""
    mod = _load_lifecycle_module()
    expected = {
        "read_before", "create", "read_after_create",
        "visibility_check", "interaction_chain",
        "update", "read_after_update",
        "cascade_check",
        "delete", "read_after_delete",
        "archive_visibility_check",
    }
    actual = set(mod.FEATURE_CHAIN_STAGES)
    assert expected.issubset(actual), f"missing: {expected - actual}"


def test_contracts_overview_documents_truth_source():
    body = CONTRACTS.read_text(encoding="utf-8")
    assert "B62-pre" in body
    assert "Truth source = Dependencies" in body or "Dependencies[] (backward edge, canonical)" in body
    # walker reads Dependencies[] ONLY note present
    assert "enables[]" in body


def test_mirrors_in_sync():
    assert LIFECYCLE.read_text(encoding="utf-8") == LIFECYCLE_MIRROR.read_text(encoding="utf-8")
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")
    assert CONTRACTS.read_text(encoding="utf-8") == CONTRACTS_MIRROR.read_text(encoding="utf-8")
