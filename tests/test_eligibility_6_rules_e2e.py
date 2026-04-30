"""6-rule eligibility gate E2E coverage (Task 29, v2.40.0).

One fixture per rule violation under tests/fixtures/eligibility-fail-rule-N/.
Each fixture is a minimal phase directory whose 6-rule check fails on EXACTLY
one rule. Verifies:

  - eligibility.passed is False
  - reasons[] mentions the violated rule
  - .recursive-probe-skipped.yaml is written with via_override=False
  - planned_spawns is absent (skip short-circuits before plan composition)

Rules (ordered as in spawn_recursive_probe.check_eligibility):
  1. phase_profile ∈ {feature, feature-legacy, hotfix}
  2. surface ∈ {ui, ui-mobile}
  3. CRUD-SURFACES.md declares ≥1 resource
  4. touched_resources intersects CRUD names
  5. surface != 'visual' / 'visual-only'
  6. ENV-CONTRACT.md disposable_seed_data + all stubs stubbed

Note: rules 2 and 5 share the surface field. Rule 5 fires first when
surface is 'visual'; rule 2 fires when surface is some other invalid
value (e.g. 'api').
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "spawn_recursive_probe.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _copy_fixture(src_name: str, tmp_path: Path) -> Path:
    """Clone an eligibility-fail fixture into tmp_path so the test does not
    pollute the source dir with .recursive-probe-skipped.yaml."""
    dst = tmp_path / "phase"
    shutil.copytree(FIXTURES / src_name, dst)
    return dst


def _run_dry(phase_dir: Path) -> dict:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--phase-dir", str(phase_dir),
         "--dry-run", "--json", "--non-interactive"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# Per-rule cases — table-driven via @pytest.mark.parametrize
# ---------------------------------------------------------------------------
RULE_CASES = [
    pytest.param(
        "eligibility-fail-rule-1", "phase_profile",
        id="rule-1-phase-profile-docs",
    ),
    pytest.param(
        "eligibility-fail-rule-2", "surface 'api' not in",
        id="rule-2-surface-api",
    ),
    pytest.param(
        "eligibility-fail-rule-3", "CRUD-SURFACES.md declares 0 resources",
        id="rule-3-no-crud-resources",
    ),
    pytest.param(
        "eligibility-fail-rule-4", "does not intersect CRUD names",
        id="rule-4-touched-no-intersect",
    ),
    pytest.param(
        "eligibility-fail-rule-5", "visual-only (rule 5)",
        id="rule-5-visual-only-surface",
    ),
    pytest.param(
        "eligibility-fail-rule-6", "ENV-CONTRACT.md disposable_seed_data not true",
        id="rule-6-env-contract-non-disposable",
    ),
]


@pytest.mark.parametrize("fixture_name,reason_substr", RULE_CASES)
def test_each_rule_violation_skips_with_reason(
    fixture_name: str, reason_substr: str, tmp_path: Path,
) -> None:
    p = _copy_fixture(fixture_name, tmp_path)
    out = _run_dry(p)

    elig = out["eligibility"]
    assert elig["passed"] is False, f"{fixture_name} should fail: {elig}"
    assert elig["skipped_via_override"] is False
    reasons = " ".join(elig["reasons"])
    assert reason_substr in reasons, (
        f"{fixture_name}: expected substring {reason_substr!r} in reasons={elig['reasons']}"
    )

    # Skip evidence YAML must be written.
    skip_yaml = p / ".recursive-probe-skipped.yaml"
    assert skip_yaml.is_file(), f"{fixture_name} did not emit .recursive-probe-skipped.yaml"
    audit = yaml.safe_load(skip_yaml.read_text(encoding="utf-8"))
    assert audit["via_override"] is False
    assert reason_substr in " ".join(audit["reasons"])

    # No spawns when eligibility fails.
    assert not out.get("planned_spawns"), (
        f"{fixture_name} produced spawns despite failed eligibility: {out}"
    )


# ---------------------------------------------------------------------------
# Sanity test — every fixture directory exists with required files
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("idx", [1, 2, 3, 4, 5, 6])
def test_each_fixture_dir_well_formed(idx: int) -> None:
    fix = FIXTURES / f"eligibility-fail-rule-{idx}"
    assert fix.is_dir(), f"missing fixture: {fix}"
    for required in (".phase-profile", "CRUD-SURFACES.md",
                     "ENV-CONTRACT.md", "SUMMARY.md"):
        assert (fix / required).is_file(), f"{fix}: missing {required}"
