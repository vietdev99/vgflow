from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pre_test_gate_wires_summary_reconcile() -> None:
    text = (
        REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "pre-test-gate.md"
    ).read_text(encoding="utf-8")

    assert ".claude/scripts/reconcile-build-summary.py" in text
    assert '--phase-dir "${PHASE_DIR}"' in text
    assert '--pre-test-report "${PHASE_DIR}/PRE-TEST-REPORT.md"' in text
    assert "failed to reconcile SUMMARY.md with fix-loop/pre-test artifacts" in text


def test_fix_loop_persists_fixed_manifests() -> None:
    text = (
        REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "in-scope-fix-loop.md"
    ).read_text(encoding="utf-8")

    assert 'FIX_RESULT_PATH="${EVIDENCE_DIR}/classified/$(basename "$ev").fixed.json"' in text
    assert "SUBAGENT_OUTPUT" in text
    assert 'mv "${FIX_RESULT_PATH}.tmp" "${FIX_RESULT_PATH}"' in text


def test_fix_loop_delegation_declares_fixed_manifest_contract() -> None:
    text = (
        REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "in-scope-fix-loop-delegation.md"
    ).read_text(encoding="utf-8")

    assert ".evidence/classified/in-scope.<warning-file>.fixed.json" in text
    assert "before counting unresolved warnings or reconciling `SUMMARY.md` in STEP 6.5" in text
