"""tests/test_batch37_edge_negative_first_class.py — Batch 37.

Codex F3+F4 (deferred from Batch 35):
F3: edge_cases[] not first-class in LIFECYCLE-SPECS schema. Boundary
    values, empty strings, unicode, large payloads absent unless already
    in upstream EDGE-CASES.md.
F4: negative paths prompt-only — codegen told "never invent assertions
    beyond TEST-GOALS". No required 401/403/422/validation/auth/timeout
    tests.

Batch 37 fix: extend LIFECYCLE-SPECS generator to emit edge_cases[] +
negative_specs[] arrays per goal. Codegen subagent prompt updated to
emit specs covering these arrays as test.each() variants.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIFECYCLE_GEN = REPO / "scripts" / "generate-lifecycle-specs.py"


def _load():
    spec = importlib.util.spec_from_file_location("ls", LIFECYCLE_GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_f3_edge_cases_helper_exists():
    """LIFECYCLE-SPECS generator must derive edge_cases[] per goal."""
    mod = _load()
    assert hasattr(mod, "_derive_edge_cases"), (
        "Batch 37 F3: must define _derive_edge_cases helper"
    )


def test_f4_negative_specs_helper_exists():
    """Must derive negative_specs[] per goal."""
    mod = _load()
    assert hasattr(mod, "_derive_negative_specs"), (
        "Batch 37 F4: must define _derive_negative_specs helper"
    )


def test_f3_goal_spec_includes_edge_cases():
    """_goal_spec output must include edge_cases[] key with default 4+
    variants: boundary_min, boundary_max, empty_string, unicode_special."""
    mod = _load()
    goal = {
        "id": "G-01",
        "title": "Create site",
        "goal_type": "create-only",
        "source": "TEST-GOALS/G-01.md",
        "mutation_evidence": "POST /api/sites returns 201",
    }
    spec = mod._goal_spec(goal, contracts=[], decisions={})
    assert "edge_cases" in spec, (
        "Batch 37 F3: _goal_spec output must contain edge_cases[]"
    )
    edge_cases = spec["edge_cases"]
    assert isinstance(edge_cases, list)
    assert len(edge_cases) >= 4, (
        f"F3: must emit ≥4 default edge cases, got {len(edge_cases)}"
    )
    kinds = {e.get("kind") for e in edge_cases}
    expected_min = {"boundary", "empty_string", "unicode_special"}
    missing = expected_min - kinds
    assert not missing, f"F3: edge case kinds missing: {missing}"


def test_f4_goal_spec_includes_negative_specs():
    """_goal_spec output must include negative_specs[] with at minimum:
    unauthorized_401, forbidden_403, validation_422 for mutation goals."""
    mod = _load()
    goal = {
        "id": "G-01",
        "title": "Create site",
        "goal_type": "create-only",
        "source": "TEST-GOALS/G-01.md",
        "mutation_evidence": "POST /api/sites",
    }
    spec = mod._goal_spec(goal, contracts=[], decisions={})
    assert "negative_specs" in spec, (
        "Batch 37 F4: _goal_spec output must contain negative_specs[]"
    )
    neg = spec["negative_specs"]
    kinds = {n.get("kind") for n in neg}
    required = {"unauthorized_401", "forbidden_403", "validation_422"}
    missing = required - kinds
    assert not missing, f"F4: negative spec kinds missing: {missing}"


def test_f4_negative_specs_have_expected_status():
    """Each negative spec must have expected_status field for assertion."""
    mod = _load()
    goal = {
        "id": "G-01",
        "title": "Create site",
        "goal_type": "create-only",
        "source": "TEST-GOALS/G-01.md",
        "mutation_evidence": "POST /api/sites",
    }
    spec = mod._goal_spec(goal, contracts=[], decisions={})
    for n in spec.get("negative_specs", []):
        assert "expected_status" in n, (
            f"F4: negative spec {n.get('kind')} must have expected_status"
        )
        assert n["expected_status"] in {401, 403, 422, 400, 404, 429, 500, 503}


def test_readonly_goal_has_edge_cases_too():
    """Read-only goals also get edge_cases (filter boundary, pagination
    edge, sort with empty list)."""
    mod = _load()
    goal = {
        "id": "G-02",
        "title": "List sites",
        "goal_type": "read-only",
        "source": "TEST-GOALS/G-02.md",
    }
    spec = mod._goal_spec(goal, contracts=[], decisions={})
    assert "edge_cases" in spec
    assert len(spec["edge_cases"]) >= 3, "read-only also needs edge cases"
