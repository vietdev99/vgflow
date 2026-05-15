"""tests/test_batch56_variants_json.py — Batch 56.

EDGE-CASES/G-NN.md (Batch 48) is markdown — codegen subagent must
regex-parse to build test.each(variants). Brittle: markdown formatting
drift breaks the parse.

Batch 56 also emits EDGE-CASES/VARIANTS.json with strict schema:
  { phase, schema_version, source,
    goals: { goal_id: [{variant_id, kind, label, input_hint, expected,
                        source, priority, idempotent}] } }

Codegen prefers JSON over markdown. verify-variants-json.py gates
schema + coverage vs LIFECYCLE-SPECS.

Coverage:
  1. derive emits VARIANTS.json alongside G-NN.md
  2. Schema fields populated for edge_cases + negative_specs
  3. variant_id format matches existing convention (b1, u2, n1)
  4. negative_specs marked source='negative_specs', idempotent rules
  5. Validator PASSES for well-formed VARIANTS.json
  6. Validator FAILS strict when file missing
  7. Validator FAILS strict when variant missing from LIFECYCLE
  8. Validator FAILS strict on bad schema
  9. delegation.md cites VARIANTS.json + has import example
  10. test-spec.md gates VARIANTS.json validity
  11. Mirror parity
"""
from __future__ import annotations
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DERIVE = REPO / "scripts" / "derive-edge-cases-from-lifecycle.py"
DERIVE_MIRROR = REPO / ".claude" / "scripts" / "derive-edge-cases-from-lifecycle.py"
VAL = REPO / "scripts" / "validators" / "verify-variants-json.py"
VAL_MIRROR = REPO / ".claude" / "scripts" / "validators" / "verify-variants-json.py"
DEL = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"
DEL_MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"
TEST_SPEC = REPO / "commands" / "vg" / "test-spec.md"
TEST_SPEC_MIRROR = REPO / ".claude" / "commands" / "vg" / "test-spec.md"


def _write_lifecycle(phase_dir: Path, goals: dict) -> None:
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(
        json.dumps({"goals": goals}), encoding="utf-8"
    )


def _run_derive(phase_dir: Path, phase: str = "7"):
    return subprocess.run(
        ["python", str(DERIVE), "--phase", phase, "--phase-dir", str(phase_dir), "--force"],
        capture_output=True, text=True,
    )


def test_derive_emits_variants_json(tmp_path):
    phase_dir = tmp_path / "phases" / "7"
    phase_dir.mkdir(parents=True)
    _write_lifecycle(phase_dir, {
        "G-01": {
            "title": "Foo",
            "edge_cases": [{"kind": "boundary"}, {"kind": "unicode_special"}],
            "negative_specs": [{"kind": "unauthorized_401", "expected_status": 401}],
        }
    })
    r = _run_derive(phase_dir)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    vp = phase_dir / "EDGE-CASES" / "VARIANTS.json"
    assert vp.is_file()
    doc = json.loads(vp.read_text(encoding="utf-8"))
    assert doc["phase"] == "7"
    assert doc["schema_version"] == "1.0"
    assert "G-01" in doc["goals"]
    variants = doc["goals"]["G-01"]
    assert len(variants) == 3
    vids = {v["variant_id"] for v in variants}
    assert vids == {"G-01-b1", "G-01-u2", "G-01-n1"}


def test_variant_schema_fields_populated(tmp_path):
    phase_dir = tmp_path / "phases" / "8"
    phase_dir.mkdir(parents=True)
    _write_lifecycle(phase_dir, {
        "G-01": {
            "edge_cases": [{
                "kind": "boundary",
                "label": "min-boundary",
                "input_hint": "set to MIN",
                "expected": "row accepted",
                "priority": "critical",
            }],
        }
    })
    _run_derive(phase_dir, "8")
    doc = json.loads((phase_dir / "EDGE-CASES" / "VARIANTS.json").read_text())
    v = doc["goals"]["G-01"][0]
    assert v["variant_id"] == "G-01-b1"
    assert v["kind"] == "boundary"
    assert v["label"] == "min-boundary"
    assert v["input_hint"] == "set to MIN"
    assert v["expected"] == "row accepted"
    assert v["source"] == "edge_cases"
    assert v["priority"] == "critical"
    assert v["idempotent"] is True


def test_negative_spec_idempotent_rules(tmp_path):
    """rate_limit_429 is NOT idempotent (rate limit window); others are."""
    phase_dir = tmp_path / "phases" / "9"
    phase_dir.mkdir(parents=True)
    _write_lifecycle(phase_dir, {
        "G-01": {
            "edge_cases": [{"kind": "boundary"}],
            "negative_specs": [
                {"kind": "unauthorized_401", "expected_status": 401},
                {"kind": "rate_limit_429", "expected_status": 429},
            ],
        }
    })
    _run_derive(phase_dir, "9")
    doc = json.loads((phase_dir / "EDGE-CASES" / "VARIANTS.json").read_text())
    by_id = {v["variant_id"]: v for v in doc["goals"]["G-01"]}
    assert by_id["G-01-n1"]["idempotent"] is True
    assert by_id["G-01-n2"]["idempotent"] is False  # rate limit
    assert by_id["G-01-n1"]["source"] == "negative_specs"


def test_validator_passes_on_well_formed(tmp_path):
    phase_dir = tmp_path / "phases" / "10"
    phase_dir.mkdir(parents=True)
    _write_lifecycle(phase_dir, {"G-01": {"edge_cases": [{"kind": "boundary"}]}})
    _run_derive(phase_dir, "10")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "10", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


def test_validator_fails_strict_when_missing(tmp_path):
    phase_dir = tmp_path / "phases" / "11"
    phase_dir.mkdir(parents=True)
    _write_lifecycle(phase_dir, {"G-01": {"edge_cases": [{"kind": "boundary"}]}})
    # NO derive run → VARIANTS.json missing
    r = subprocess.run(
        ["python", str(VAL), "--phase", "11", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0


def test_validator_fails_strict_when_variant_missing(tmp_path):
    phase_dir = tmp_path / "phases" / "12"
    phase_dir.mkdir(parents=True)
    _write_lifecycle(phase_dir, {
        "G-01": {"edge_cases": [{"kind": "boundary"}, {"kind": "unicode_special"}]}
    })
    edge_dir = phase_dir / "EDGE-CASES"
    edge_dir.mkdir()
    # Only G-01-b1 in JSON, missing G-01-u2
    (edge_dir / "VARIANTS.json").write_text(json.dumps({
        "phase": "12",
        "schema_version": "1.0",
        "source": "test",
        "goals": {"G-01": [{
            "variant_id": "G-01-b1", "goal_id": "G-01", "kind": "boundary",
            "label": "x", "source": "edge_cases", "priority": "important",
        }]},
    }), encoding="utf-8")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "12", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "G-01-u2" in (r.stderr + r.stdout)


def test_validator_fails_strict_on_bad_schema(tmp_path):
    phase_dir = tmp_path / "phases" / "13"
    phase_dir.mkdir(parents=True)
    _write_lifecycle(phase_dir, {"G-01": {"edge_cases": [{"kind": "boundary"}]}})
    edge_dir = phase_dir / "EDGE-CASES"
    edge_dir.mkdir()
    # Missing required field 'kind'
    (edge_dir / "VARIANTS.json").write_text(json.dumps({
        "phase": "13",
        "schema_version": "1.0",
        "source": "test",
        "goals": {"G-01": [{
            "variant_id": "G-01-b1", "goal_id": "G-01",
            "label": "x", "source": "edge_cases", "priority": "important",
        }]},
    }), encoding="utf-8")
    r = subprocess.run(
        ["python", str(VAL), "--phase", "13", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "kind" in (r.stderr + r.stdout)


def test_delegation_md_cites_variants_json():
    body = DEL.read_text(encoding="utf-8")
    assert "VARIANTS.json" in body
    assert "Batch 56" in body
    # Import pattern shown
    assert "require" in body or "import" in body


def test_test_spec_gates_variants_json():
    body = TEST_SPEC.read_text(encoding="utf-8")
    assert "verify-variants-json.py" in body
    assert "--allow-variants-shortfall" in body
    assert "test_spec.variants_json_shortfall" in body


def test_no_lifecycle_skips_gracefully(tmp_path):
    """No LIFECYCLE-SPECS.json → validator returns 0 without error."""
    phase_dir = tmp_path / "phases" / "14"
    phase_dir.mkdir(parents=True)
    r = subprocess.run(
        ["python", str(VAL), "--phase", "14", "--phase-dir", str(phase_dir), "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0


def test_mirrors_in_sync():
    assert DERIVE.read_text(encoding="utf-8") == DERIVE_MIRROR.read_text(encoding="utf-8")
    assert VAL.read_text(encoding="utf-8") == VAL_MIRROR.read_text(encoding="utf-8")
    assert DEL.read_text(encoding="utf-8") == DEL_MIRROR.read_text(encoding="utf-8")
    assert TEST_SPEC.read_text(encoding="utf-8") == TEST_SPEC_MIRROR.read_text(encoding="utf-8")
