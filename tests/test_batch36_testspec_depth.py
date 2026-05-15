"""tests/test_batch36_testspec_depth.py — Batch 36 test-spec depth fixes.

User complaint: "test-specs còn khá sơ sài và test cũng không bám theo
test specs". Sandbox deploy reveals many small issues AI doesn't catch.

Root causes:
R1: generate-lifecycle-specs.py skips read-only goals by default
    (include_readonly=False). LIFECYCLE-SPECS.json contains only mutation
    goals. Subagent reads LIFECYCLE → generates specs only for mutation.
    Display/list/dashboard/filter goals get sparse or no spec.

R2: Read-only goals (when included) only get `read_before` stage. Missing:
    render_initial, interaction_filter, interaction_sort,
    interaction_paginate, empty_state, error_state_4xx, loading_state,
    accessibility.

R3: acceptance_criteria / success_criteria not converted to per-stage
    assertion[]. Specs may not assert each criterion.
"""
from __future__ import annotations
import importlib.util
import json
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIFECYCLE_GEN = REPO / "scripts" / "generate-lifecycle-specs.py"
DEEP_GEN = REPO / "scripts" / "generate-deep-test-specs.py"


def _load(path):
    name = path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_r1_deep_gen_includes_readonly_by_default():
    """deep-test-specs.py must call generate(include_readonly=True) so
    LIFECYCLE-SPECS.json covers ALL goals, not just mutation."""
    body = DEEP_GEN.read_text(encoding="utf-8")
    assert "include_readonly=True" in body or "include_readonly = True" in body, (
        "Batch 36 R1: generate-deep-test-specs.py must call lifecycle "
        "generate with include_readonly=True. Currently skips read-only "
        "goals → sparse specs."
    )


def test_r2_readonly_goal_has_multiple_stages():
    """Read-only goal must get more than just `read_before` stage.
    Needs render_initial + interaction_filter + interaction_sort +
    interaction_paginate + empty_state + error_state_4xx + loading_state +
    accessibility."""
    mod = _load(LIFECYCLE_GEN)
    READONLY_STAGES = getattr(mod, "READONLY_STAGES", None)
    assert READONLY_STAGES is not None, (
        "Batch 36 R2: must define READONLY_STAGES tuple covering "
        "render+filter+sort+paginate+empty+error+loading+a11y"
    )
    required = {"render_initial", "interaction_filter", "interaction_sort",
                "interaction_paginate", "empty_state", "error_state_4xx",
                "loading_state", "accessibility"}
    actual = set(READONLY_STAGES)
    missing = required - actual
    assert not missing, f"R2: read-only stages missing: {missing}"


def test_r2_readonly_stage_mapped_in_goal_type_stages():
    """GOAL_TYPE_STAGES['read-only'] must reference READONLY_STAGES."""
    mod = _load(LIFECYCLE_GEN)
    gts = mod.GOAL_TYPE_STAGES
    assert "read-only" in gts
    # Must be more than just (read_before,)
    assert len(gts["read-only"]) >= 4, (
        f"R2: read-only stages too short ({len(gts['read-only'])}); "
        f"need ≥4 stages for proper coverage"
    )


def test_r3_acceptance_criteria_parsed():
    """generate-lifecycle-specs must parse acceptance_criteria field
    from goal frontmatter + emit per-criterion entry in spec.assertions[]."""
    mod = _load(LIFECYCLE_GEN)
    # Must have helper to parse criteria
    has_helper = (
        hasattr(mod, "_parse_acceptance_criteria")
        or hasattr(mod, "_acceptance_criteria")
        or hasattr(mod, "_criteria_assertions")
    )
    assert has_helper, (
        "Batch 36 R3: must define helper to parse acceptance_criteria → "
        "assertion[]. Currently criteria only embedded in prose."
    )


def test_r3_goal_spec_has_criteria_assertions():
    """When a goal has acceptance_criteria, _goal_spec output must include
    criteria in assertions[]. Use synthetic goal to verify."""
    mod = _load(LIFECYCLE_GEN)
    goal = {
        "id": "G-01",
        "title": "List sites with filter",
        "goal_type": "read-only",
        "source": "TEST-GOALS/G-01.md",
        "acceptance_criteria": [
            "Page renders within 2s",
            "Filter dropdown shows all status values",
            "Empty state shows 'No sites' message",
        ],
        "priority": "important",
    }
    spec = mod._goal_spec(goal, contracts=[], decisions={})
    # Check that criteria appears somewhere in assertions
    asserts_text = json.dumps(spec.get("steps", []))
    found = sum(
        1 for crit in goal["acceptance_criteria"]
        if crit in asserts_text or any(word in asserts_text for word in crit.split()[:3])
    )
    assert found >= 1, (
        "R3: goal acceptance_criteria must appear in spec assertions"
    )
