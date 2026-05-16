"""tests/test_batch65b_validator_stage_sets.py — B65b (codex BLOCKER #3).

Codex audit found verify-deep-test-specs.py:106-109 hard-requires
`stages == REQUIRED_STAGES` (RCRURDR 7 stages). This blocks valid
feature_chain output (11 stages per FEATURE_CHAIN_STAGES) and
read-only output (9 stages per READONLY_STAGES).

Fix: per-goal-class stage sets mirror generate-lifecycle-specs.py
dispatch precedence:
  1. goal_class (feature_chain, post_create_cascade, readonly)
  2. goal_type (create-only, update-only, delete-only, read-only)
  3. fallback REQUIRED_STAGES (full RCRURDR)

Coverage:
  1. _expected_stages_for_spec returns FEATURE_CHAIN_STAGES for
     goal_class=feature_chain
  2. _expected_stages_for_spec returns FEATURE_CHAIN_STAGES for
     post_create_cascade alias
  3. _expected_stages_for_spec returns READONLY_STAGES for
     goal_class=readonly
  4. _expected_stages_for_spec returns READONLY_STAGES for
     goal_type=read-only
  5. _expected_stages_for_spec returns CREATE_ONLY for
     goal_type=create-only
  6. _expected_stages_for_spec returns REQUIRED_STAGES (RCRURDR) default
  7. goal_class wins over goal_type (B62-pre precedence)
  8. FEATURE_CHAIN_STAGES content == generate-lifecycle-specs
  9. READONLY_STAGES content == generate-lifecycle-specs
  10. Validator passes feature_chain spec with full 11 stages
  11. Validator fails feature_chain spec missing visibility_check
  12. Error message cites dispatch_key (goal_class=... / goal_type=...)
  13. Mirror parity
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-deep-test-specs.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-deep-test-specs.py"
LIFECYCLE = REPO / "scripts" / "generate-lifecycle-specs.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_feature_chain_class_returns_feature_chain_stages():
    mod = _load(VAL, "val_b65b_1")
    stages, key = mod._expected_stages_for_spec({"goal_class": "feature_chain"})
    assert stages == mod.FEATURE_CHAIN_STAGES
    assert "visibility_check" in stages
    assert "feature_chain" in key


def test_post_create_cascade_alias_returns_feature_chain():
    mod = _load(VAL, "val_b65b_2")
    stages, key = mod._expected_stages_for_spec({"goal_class": "post_create_cascade"})
    assert stages == mod.FEATURE_CHAIN_STAGES


def test_readonly_class_returns_readonly_stages():
    mod = _load(VAL, "val_b65b_3")
    stages, key = mod._expected_stages_for_spec({"goal_class": "readonly"})
    assert stages == mod.READONLY_STAGES


def test_readonly_goal_type_returns_readonly_stages():
    mod = _load(VAL, "val_b65b_4")
    stages, key = mod._expected_stages_for_spec({"goal_type": "read-only"})
    assert stages == mod.READONLY_STAGES
    assert "read-only" in key


def test_create_only_returns_create_only_stages():
    mod = _load(VAL, "val_b65b_5")
    stages, key = mod._expected_stages_for_spec({"goal_type": "create-only"})
    assert stages == mod.CREATE_ONLY_STAGES


def test_default_returns_required_stages():
    mod = _load(VAL, "val_b65b_6")
    stages, key = mod._expected_stages_for_spec({})
    assert stages == mod.REQUIRED_STAGES
    assert "default" in key.lower() or "RCRURDR" in key


def test_goal_class_wins_over_goal_type():
    """B62-pre dispatch precedence: goal_class trumps goal_type."""
    mod = _load(VAL, "val_b65b_7")
    spec = {"goal_class": "feature_chain", "goal_type": "create-only"}
    stages, key = mod._expected_stages_for_spec(spec)
    assert stages == mod.FEATURE_CHAIN_STAGES
    assert "goal_class" in key


def test_feature_chain_stages_match_generator():
    """B65b parity: validator FEATURE_CHAIN_STAGES must mirror
    generate-lifecycle-specs.py FEATURE_CHAIN_STAGES exactly."""
    val_mod = _load(VAL, "val_b65b_8")
    gen_mod = _load(LIFECYCLE, "lc_b65b_8")
    assert val_mod.FEATURE_CHAIN_STAGES == gen_mod.FEATURE_CHAIN_STAGES


def test_readonly_stages_match_generator():
    val_mod = _load(VAL, "val_b65b_9")
    gen_mod = _load(LIFECYCLE, "lc_b65b_9")
    assert val_mod.READONLY_STAGES == gen_mod.READONLY_STAGES


def test_validator_passes_feature_chain_full_stages():
    """Smoke: feature_chain spec with all 11 stages → no
    lifecycle_stage_missing error."""
    mod = _load(VAL, "val_b65b_10")
    spec = {
        "goal_class": "feature_chain",
        "actors": [{"id": "user"}],
        "fixture_dag": [{"id": "f1"}],
        "cleanup": [{"target": "f1"}],
        "artifact_capture": [],
        "steps": [{"stage": s} for s in mod.FEATURE_CHAIN_STAGES],
        "execution_plan": {
            "profile": "web-fullstack",
            "runner": "playwright",
            "entrypoints": ["x"],
            "assertions": ["y"],
            "artifacts": ["z"],
        },
    }
    # Build mock Output to capture errors
    import argparse
    args = argparse.Namespace(severity="warn", phase="7")
    out = mod.Output(validator="verify-deep-test-specs")
    mod.validate_goal_contract(out, args, Path("/tmp"), "G-01", spec)
    stage_errors = [e for e in out.evidence if e.type == "lifecycle_stage_missing"]
    assert not stage_errors, f"feature_chain full stages should not error: {stage_errors}"


def test_validator_fails_feature_chain_missing_visibility_check():
    """feature_chain missing visibility_check → stage error fires."""
    mod = _load(VAL, "val_b65b_11")
    incomplete = [s for s in mod.FEATURE_CHAIN_STAGES if s != "visibility_check"]
    spec = {
        "goal_class": "feature_chain",
        "actors": [{"id": "user"}],
        "fixture_dag": [{"id": "f1"}],
        "cleanup": [{"target": "f1"}],
        "artifact_capture": [],
        "steps": [{"stage": s} for s in incomplete],
        "execution_plan": {
            "profile": "web-fullstack", "runner": "playwright",
            "entrypoints": ["x"], "assertions": ["y"], "artifacts": ["z"],
        },
    }
    import argparse
    args = argparse.Namespace(severity="warn", phase="7")
    out = mod.Output(validator="verify-deep-test-specs")
    mod.validate_goal_contract(out, args, Path("/tmp"), "G-01", spec)
    stage_errors = [e for e in out.evidence if e.type == "lifecycle_stage_missing"]
    assert stage_errors, "missing visibility_check must fire error"
    assert "visibility_check" in stage_errors[0].message


def test_error_message_cites_dispatch_key():
    """Error message must include 'goal_class=feature_chain' or similar so
    operator knows which stage set was expected."""
    mod = _load(VAL, "val_b65b_12")
    spec = {
        "goal_class": "feature_chain",
        "actors": [{"id": "user"}],
        "fixture_dag": [{"id": "f1"}],
        "cleanup": [{"target": "f1"}],
        "artifact_capture": [],
        "steps": [{"stage": "create"}],  # only 1 stage, wrong
        "execution_plan": {
            "profile": "web-fullstack", "runner": "playwright",
            "entrypoints": ["x"], "assertions": ["y"], "artifacts": ["z"],
        },
    }
    import argparse
    args = argparse.Namespace(severity="warn", phase="7")
    out = mod.Output(validator="verify-deep-test-specs")
    mod.validate_goal_contract(out, args, Path("/tmp"), "G-01", spec)
    stage_errors = [e for e in out.evidence if e.type == "lifecycle_stage_missing"]
    assert stage_errors
    assert "goal_class=feature_chain" in stage_errors[0].message


def test_mirror_in_sync():
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")
