"""R6 Task 6 — accept STEP 3 abort path must satisfy run-complete contract,
and UAT 6-section validator must require canonical A/B/C/D/E/F enum.

Background:
  - STEP 3 (`4_build_uat_checklist`) abort branch in
    `commands/vg/_shared/accept/uat/checklist-build/overview.md` claimed
    "remaining steps short-circuit" but accept.md `must_touch_markers` still
    requires all 17 markers. Run-complete BLOCKs because aborted runs cannot
    satisfy the contract: missing markers + missing `.uat-responses.json`.
  - Inline UAT validator in the same overview.md only checked
    `sections[] length >= 5` — weaker than ISTQB CT-AcT 6-section standard,
    which requires the canonical A/B/C/D/E/F enum (with optional A.1/B.1
    sub-sections + N/A inside any section).

These tests assert the post-fix shape:
  - Abort branch writes minimal `.uat-responses.json`, touches all
    profile-applicable markers (4_build_uat_checklist + downstream
    4b/5/5_quorum/6b/6c/6/7), and emits an explicit
    `accept.aborted_with_short_circuit` event.
  - The new validator `scripts/validators/verify-uat-checklist-sections.py`
    enforces the canonical 6-section enum.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ABORT_REF = (
    REPO_ROOT
    / "commands"
    / "vg"
    / "_shared"
    / "accept"
    / "uat"
    / "checklist-build"
    / "overview.md"
)
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-uat-checklist-sections.py"

# Markers downstream of `4_build_uat_checklist` that abort path must touch.
# accept.md must_touch_markers minus the steps that already ran by the time
# we hit STEP 3 abort (preflight + gates 0..3c + 4 itself).
DOWNSTREAM_MARKERS = (
    "4b_uat_narrative_autofire",
    "5_interactive_uat",
    "5_uat_quorum_gate",
    "6b_security_baseline",
    "6c_learn_auto_surface",
    "6_write_uat_md",
    "7_post_accept_actions",
)


# ---------------------------------------------------------------------------
# Abort branch shape
# ---------------------------------------------------------------------------


def _abort_section_text() -> str:
    """Return the abort-branch chunk of overview.md (from 'aborts' to end)."""
    text = ABORT_REF.read_text(encoding="utf-8")
    # Capture from the abort line through the rest of the file. Anchor on the
    # exact phrase that introduces the abort branch.
    match = re.search(r"If user aborts.*", text, re.DOTALL)
    assert match, "abort branch not found in overview.md"
    return match.group(0)


def test_abort_branch_writes_minimal_uat_responses():
    """Abort path must write `.uat-responses.json` so must_write contract passes."""
    section = _abort_section_text()
    assert ".uat-responses.json" in section, (
        "abort branch must write minimal `.uat-responses.json` "
        "(must_write contract requires it)"
    )


def test_abort_branch_writes_uat_md_with_aborted_verdict():
    """Abort path must write UAT.md with Verdict: ABORTED so must_write passes."""
    section = _abort_section_text()
    assert "ABORTED" in section, "abort branch must record ABORTED verdict in UAT.md"
    assert "Verdict:" in section, (
        "abort branch must include `Verdict:` line (must_write content_required_sections)"
    )


def test_abort_branch_touches_all_downstream_markers():
    """Abort path must touch every must_touch_markers entry that follows STEP 3."""
    section = _abort_section_text()
    missing = [m for m in DOWNSTREAM_MARKERS if m not in section]
    assert not missing, (
        f"abort branch missing marker touches for: {missing}. "
        "must_touch_markers contract in commands/vg/accept.md requires all 17."
    )


def test_abort_branch_emits_short_circuit_event():
    """Abort path must emit a canonical event so override/audit telemetry sees it."""
    section = _abort_section_text()
    assert "accept.aborted_with_short_circuit" in section, (
        "abort branch must emit `accept.aborted_with_short_circuit` event "
        "(audit trail for short-circuit path)"
    )


def test_abort_branch_emits_required_completion_telemetry():
    """Abort path still hits accept.completed so run-complete telemetry contract passes."""
    section = _abort_section_text()
    assert "accept.completed" in section, (
        "abort branch must emit `accept.completed` (must_emit_telemetry contract)"
    )


def test_abort_branch_calls_run_complete():
    """Abort path must finalize the run via vg-orchestrator run-complete."""
    section = _abort_section_text()
    assert "run-complete" in section, (
        "abort branch must invoke `vg-orchestrator run-complete` so the run "
        "is closed cleanly (otherwise current-run.json stays orphaned)"
    )


# ---------------------------------------------------------------------------
# 6-section validator
# ---------------------------------------------------------------------------


def test_validator_file_exists():
    assert VALIDATOR.exists(), f"missing validator: {VALIDATOR}"
    assert VALIDATOR.stat().st_size > 100, "validator too small"


def test_validator_rejects_legacy_length_check_in_overview():
    """Inline `sections[] length >= 5` in overview.md must be replaced by the
    canonical 6-section enum check."""
    text = ABORT_REF.read_text(encoding="utf-8")
    # Reject the legacy length-only enforcement phrasing.
    assert "length ≥ 5" not in text and "length >= 5" not in text, (
        "overview.md still contains legacy `length >= 5` check — replace with "
        "canonical A/B/C/D/E/F enum (delegate to verify-uat-checklist-sections.py)"
    )


def _run_validator(stdin_payload: dict) -> tuple[int, dict]:
    """Run the validator with --stdin, return (rc, parsed JSON)."""
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--stdin"],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    try:
        body = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        body = {"_raw_stdout": proc.stdout, "_stderr": proc.stderr}
    return proc.returncode, body


def test_validator_passes_canonical_six_sections():
    sections = [
        {"name": "A", "title": "Decisions", "items": []},
        {"name": "B", "title": "Goals", "items": []},
        {"name": "C", "title": "Ripple HIGH", "items": []},
        {"name": "D", "title": "Design refs", "items": []},
        {"name": "E", "title": "Deliverables", "items": []},
        {"name": "F", "title": "Mobile gates", "items": []},
    ]
    rc, body = _run_validator({"sections": sections})
    assert rc == 0, f"validator should PASS canonical 6 sections, got rc={rc} body={body}"
    assert body.get("verdict") == "PASS", body


def test_validator_passes_canonical_with_subsections():
    """A.1 + B.1 sub-sections are allowed alongside the canonical 6."""
    sections = [
        {"name": "A", "title": "Decisions", "items": []},
        {"name": "A.1", "title": "Foundation cites", "items": []},
        {"name": "B", "title": "Goals", "items": []},
        {"name": "B.1", "title": "CRUD surfaces", "items": []},
        {"name": "C", "title": "Ripple HIGH", "items": []},
        {"name": "D", "title": "Design refs", "items": []},
        {"name": "E", "title": "Deliverables", "items": []},
        {"name": "F", "title": "Mobile gates", "items": []},
    ]
    rc, body = _run_validator({"sections": sections})
    assert rc == 0, f"validator should accept sub-sections, body={body}"


def test_validator_passes_na_section_for_non_mobile():
    """Section F may be marked N/A (e.g. web-fullstack profile) but key MUST exist."""
    sections = [
        {"name": "A", "title": "Decisions", "items": []},
        {"name": "B", "title": "Goals", "items": []},
        {"name": "C", "title": "Ripple HIGH", "items": []},
        {"name": "D", "title": "Design refs", "items": []},
        {"name": "E", "title": "Deliverables", "items": []},
        {"name": "F", "title": "Mobile gates", "items": [], "status": "N/A"},
    ]
    rc, body = _run_validator({"sections": sections})
    assert rc == 0, f"validator should accept N/A section, body={body}"


def test_validator_blocks_missing_section():
    """Missing canonical section → BLOCK (not just WARN)."""
    sections = [
        {"name": "A", "title": "Decisions", "items": []},
        {"name": "B", "title": "Goals", "items": []},
        {"name": "C", "title": "Ripple HIGH", "items": []},
        {"name": "D", "title": "Design refs", "items": []},
        {"name": "E", "title": "Deliverables", "items": []},
        # F missing
    ]
    rc, body = _run_validator({"sections": sections})
    assert rc != 0, f"validator should BLOCK on missing F section, body={body}"
    assert body.get("verdict") == "BLOCK", body


def test_validator_blocks_legacy_5_section_payload():
    """A 5-section payload that previously passed `length >= 5` must now BLOCK."""
    # Legacy payload: A, B, B.1, D, E (no C, no F) — old check accepted len>=5.
    sections = [
        {"name": "A", "title": "Decisions", "items": []},
        {"name": "B", "title": "Goals", "items": []},
        {"name": "B.1", "title": "CRUD surfaces", "items": []},
        {"name": "D", "title": "Design refs", "items": []},
        {"name": "E", "title": "Deliverables", "items": []},
    ]
    rc, body = _run_validator({"sections": sections})
    assert rc != 0, (
        "validator should reject legacy 5-section payload (missing C and F) — "
        "previous `length >= 5` check accepted this incorrectly. "
        f"body={body}"
    )
