"""Task 35 — finding-ID namespace validator."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "scripts/validators/verify-finding-id-namespace.py"


def test_conforming_id_passes(tmp_path: Path) -> None:
    """Real PV3 format: ### EP-001 [MAJOR] GET /api/..."""
    feedback = tmp_path / "REVIEW-FEEDBACK.md"
    feedback.write_text(textwrap.dedent("""
        # Review Feedback

        ### EP-001 [MAJOR] GET /api/users — handler missing
        Description: handler not registered in app.ts.

        ### DR-002 [MINOR] Foundation drift on field naming
        Description: snake_case vs camelCase drift.
    """).strip(), encoding="utf-8")
    result = subprocess.run([
        "python3", str(VALIDATOR),
        "--feedback", str(feedback),
        "--phase", "test-1.0",
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_legacy_E_001_emits_warn_telemetry(tmp_path: Path) -> None:
    """AI emits old `E-001` (from PV3 history) — validator catches + suggests fix."""
    feedback = tmp_path / "REVIEW-FEEDBACK.md"
    feedback.write_text(textwrap.dedent("""
        ### E-001 [MAJOR] GET /api/users — handler missing
    """).strip(), encoding="utf-8")
    ev_out = tmp_path / "ev.json"
    result = subprocess.run([
        "python3", str(VALIDATOR),
        "--feedback", str(feedback),
        "--phase", "test-1.0",
        "--evidence-out", str(ev_out),
    ], capture_output=True, text=True)
    # Warn-tier: returncode 0 (don't fail review yet, gradual rollout)
    assert result.returncode == 0
    import json
    ev = json.loads(ev_out.read_text(encoding="utf-8"))
    assert ev["non_conforming_count"] == 1
    assert ev["suggestions"][0]["original"] == "E-001"
    assert ev["suggestions"][0]["suggested"] == "EP-001"


def test_invalid_prefix_emits_warn(tmp_path: Path) -> None:
    """Single-letter prefix not in allowed set → suggest 2-letter equivalent."""
    feedback = tmp_path / "REVIEW-FEEDBACK.md"
    feedback.write_text(textwrap.dedent("""
        ### Z-005 [MINOR] unknown category
    """).strip(), encoding="utf-8")
    ev_out = tmp_path / "ev.json"
    subprocess.run([
        "python3", str(VALIDATOR),
        "--feedback", str(feedback),
        "--phase", "test-1.0",
        "--evidence-out", str(ev_out),
    ], capture_output=True, text=True, check=False)
    import json
    ev = json.loads(ev_out.read_text(encoding="utf-8"))
    assert ev["non_conforming_count"] == 1
    # No mapping for Z- → suggestion is null (manual review needed)
    assert ev["suggestions"][0]["suggested"] is None


def test_scanner_contract_namespace_section_present() -> None:
    """scanner-report-contract.md MUST document the prefix table."""
    text = (REPO / "commands/vg/_shared/scanner-report-contract.md").read_text(encoding="utf-8")
    for prefix in ("EP-", "DR-", "RV-", "GC-", "FN-", "SC-", "TM-"):
        assert prefix in text, f"prefix {prefix} missing from scanner-report-contract.md"


def test_module_constants() -> None:
    """scanner_report_contract.py exports the prefix list + regex."""
    sys.path.insert(0, str(REPO / "scripts/lib"))
    from scanner_report_contract import VALID_PREFIXES, FINDING_ID_REGEX
    assert "EP" in VALID_PREFIXES
    assert "DR" in VALID_PREFIXES
    assert FINDING_ID_REGEX.match("EP-001")
    assert not FINDING_ID_REGEX.match("E-001")  # 1-letter rejected
    assert not FINDING_ID_REGEX.match("EP-1")   # not zero-padded
    sys.path.remove(str(REPO / "scripts/lib"))


def test_review_md_declares_finding_id_invalid_telemetry() -> None:
    text = (REPO / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "review.finding_id_invalid" in text, \
        "review.md must_emit_telemetry must declare 'review.finding_id_invalid' (else Stop hook silent-skips)"
