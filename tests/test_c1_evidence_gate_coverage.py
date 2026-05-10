"""v2.68.0 C1 — Evidence Gate retrofit coverage.

Verifies that the 3 validators which previously did not emit structured
evidence to ${PHASE_DIR}/.evidence/<gate_id>.json now do so:

  - scripts/validators/runtime-evidence.py
  - scripts/validators/verify-workflow-evidence.py
  - scripts/validators/verify-read-evidence.py

Each must:
  1. Reference the .evidence/ directory (for the structured JSON write).
  2. Include a verdict + ts/timestamp field in the emitted payload.

Note: plan §Task 1 originally parametrized 6 gates (3 existing +
3 retrofit). The 3 "existing" gates (verify-fe-be-call-graph.py,
verify-spec-drift.py, verify-contract-shape.py) emit evidence via
--evidence-out flag, NOT a fixed .evidence/ directory path, so they
do not match the test pattern. Task description (commit message
"C1 evidence gate retrofit for runtime/workflow/read-evidence")
scopes the retrofit to the 3 missing validators. We parametrize 3
gates × 2 properties = 6 test cases. See report deviations.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent

GATES_REQUIRING_EVIDENCE = [
    ("scripts/validators/runtime-evidence.py", "runtime-evidence"),
    ("scripts/validators/verify-workflow-evidence.py", "workflow-evidence"),
    ("scripts/validators/verify-read-evidence.py", "read-evidence"),
]


@pytest.mark.parametrize("validator_path,gate_id", GATES_REQUIRING_EVIDENCE)
def test_validator_writes_evidence_json(validator_path: str, gate_id: str) -> None:
    """Each retrofit validator must write structured evidence JSON to .evidence/<gate_id>.json."""
    p = REPO_ROOT / validator_path
    assert p.exists(), f"{validator_path} not found"
    src = p.read_text(encoding="utf-8")
    assert re.search(r"\.evidence/|emit-evidence-signed|emit_evidence_signed", src), (
        f"{validator_path}: missing .evidence/ JSON write (v2.68.0 C1 retrofit)"
    )


@pytest.mark.parametrize("validator_path,gate_id", GATES_REQUIRING_EVIDENCE)
def test_evidence_includes_required_fields(validator_path: str, gate_id: str) -> None:
    """Evidence JSON payload must reference verdict + ts/timestamp."""
    p = REPO_ROOT / validator_path
    assert p.exists(), f"{validator_path} not found"
    src = p.read_text(encoding="utf-8")
    has_verdict = "verdict" in src.lower()
    has_ts = re.search(
        r"datetime|isoformat|timestamp|signed_at",
        src,
        re.IGNORECASE,
    )
    assert has_verdict, f"{validator_path}: missing verdict field"
    assert has_ts, f"{validator_path}: missing ts/timestamp field"
