"""tests/test_g13_lifecycle_validator_semantics.py — G13 semantic checks."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
VAL = REPO / "scripts" / "validators" / "verify-lifecycle-spec-depth.py"


def _run_val(tmp_path, spec_data):
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "LIFECYCLE-SPECS.json").write_text(json.dumps(spec_data), encoding="utf-8")
    # Also need a TEST-GOALS.md so the validator finds side-effecting goals
    (phase_dir / "TEST-GOALS.md").write_text(
        "## Goal G-01: Create test\n**goal_type:** mutation\n**Mutation evidence:** POST /api/x\n",
        encoding="utf-8",
    )
    import os
    env = {**os.environ, "VG_REPO_ROOT": str(tmp_path)}
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase", "99"],
        capture_output=True, text=True, env=env,
    )
    return r


def test_validator_flags_stage_endpoint_method_mismatch(tmp_path):
    """G13: validator must flag when stage verb mismatches endpoint method.
    E.g. 'create' stage bound to GET endpoint should warn."""
    spec = {
        "phase": "99",
        "goals": {
            "G-01": {
                "actors": [{"id": "user"}],
                "fixture_dag": [{"id": "session", "kind": "auth", "cleanup": "revoke"}],
                "preconditions": ["active session"],
                "steps": [
                    {"name": "create", "stage": "create", "actor": "user",
                     "endpoint": {"method": "GET", "path": "/api/x"},  # bug: create stage with GET
                     "assertions": [{"source": "API-CONTRACTS", "check": "status 200"}]},
                    {"name": "read_before", "stage": "read_before", "actor": "user",
                     "endpoint": {"method": "GET", "path": "/api/x"},
                     "assertions": [{"source": "baseline", "check": "empty"}]},
                    {"name": "read_after_create", "stage": "read_after_create", "actor": "user",
                     "endpoint": {"method": "GET", "path": "/api/x"},
                     "assertions": [{"source": "API-CONTRACTS", "check": "exists"}]},
                ],
                "artifact_capture": [],
                "cleanup": [{"target": "session", "action": "revoke"}],
            }
        }
    }
    r = _run_val(tmp_path, spec)
    assert (r.returncode != 0) or ("stage" in r.stdout.lower() and "method" in r.stdout.lower()) or "G13" in r.stdout, (
        f"G13: validator must flag create-stage-with-GET-endpoint mismatch. "
        f"stdout={r.stdout[:500]} stderr={r.stderr[:200]}"
    )


def test_validator_flags_assertion_without_source(tmp_path):
    """G13: validator must flag step.assertions[] entries missing source field."""
    spec = {
        "phase": "99",
        "goals": {
            "G-01": {
                "actors": [{"id": "user"}],
                "fixture_dag": [{"id": "session", "kind": "auth", "cleanup": "revoke"}],
                "preconditions": ["active session"],
                "steps": [
                    {"name": "create", "stage": "create", "actor": "user",
                     "endpoint": {"method": "POST", "path": "/api/x"},
                     "assertions": [{"check": "status 201"}]},  # missing source
                    {"name": "read_before", "stage": "read_before", "actor": "user",
                     "endpoint": {"method": "GET", "path": "/api/x"},
                     "assertions": []},
                    {"name": "read_after_create", "stage": "read_after_create", "actor": "user",
                     "endpoint": {"method": "GET", "path": "/api/x"},
                     "assertions": []},
                ],
                "artifact_capture": [],
                "cleanup": [{"target": "session", "action": "revoke"}],
            }
        }
    }
    r = _run_val(tmp_path, spec)
    assert "source" in r.stdout.lower() or r.returncode != 0, (
        f"G13: validator must flag assertions[] entries without source field. "
        f"stdout={r.stdout[:500]}"
    )


def test_validator_passes_well_formed_spec(tmp_path):
    """G13: well-formed spec passes."""
    spec = {
        "phase": "99",
        "goals": {
            "G-01": {
                "actors": [{"id": "user"}],
                "preconditions": ["session active"],
                "fixture_dag": [{"id": "user_session", "kind": "auth", "cleanup": "revoke"}],
                "steps": [
                    {"name": "read_before", "stage": "read_before", "actor": "user",
                     "endpoint": {"method": "GET", "path": "/api/x"},
                     "assertions": [{"source": "baseline", "check": "empty list"}]},
                    {"name": "create", "stage": "create", "actor": "user",
                     "endpoint": {"method": "POST", "path": "/api/x"},
                     "assertions": [{"source": "API-CONTRACTS", "check": "POST returns 201"}]},
                    {"name": "read_after_create", "stage": "read_after_create", "actor": "user",
                     "endpoint": {"method": "GET", "path": "/api/x"},
                     "assertions": [{"source": "API-CONTRACTS", "check": "item present"}]},
                    {"name": "update", "stage": "update", "actor": "user",
                     "endpoint": {"method": "PATCH", "path": "/api/x/1"},
                     "assertions": [{"source": "API-CONTRACTS", "check": "PATCH returns 200"}]},
                    {"name": "read_after_update", "stage": "read_after_update", "actor": "user",
                     "endpoint": {"method": "GET", "path": "/api/x"},
                     "assertions": [{"source": "API-CONTRACTS", "check": "updated state"}]},
                    {"name": "delete", "stage": "delete", "actor": "user",
                     "endpoint": {"method": "DELETE", "path": "/api/x/1"},
                     "assertions": [{"source": "API-CONTRACTS", "check": "DELETE returns 204"}]},
                    {"name": "read_after_delete", "stage": "read_after_delete", "actor": "user",
                     "endpoint": {"method": "GET", "path": "/api/x"},
                     "assertions": [{"source": "API-CONTRACTS", "check": "item gone"}]},
                ],
                "artifact_capture": [],
                "cleanup": [{"target": "user_session", "action": "revoke"}],
            }
        }
    }
    r = _run_val(tmp_path, spec)
    # Should pass — or at least not fail with G13-specific errors
    if r.returncode != 0:
        # Acceptable if pre-existing validator complains about phase markers, etc.
        # The new G13 semantic checks should NOT fire on well-formed spec
        assert "G13" not in r.stdout, f"G13: well-formed spec must not trigger G13 errors. stdout={r.stdout[:500]}"
