"""Task 43 — verify <workflow_context> block in waves-delegation.md prompt template.

Pin: prompt template MUST declare a <workflow_context> block that
substitutes ${WORKFLOW_SLICE_BLOCK}. Orchestrator resolves to either
@${workflow_slice_path} (when capsule.workflow_id present) or literal
NONE string (when null).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WAVES_DEL = REPO / "commands/vg/_shared/build/waves-delegation.md"
BUILD_MD = REPO / "commands/vg/build.md"


def test_workflow_context_block_present() -> None:
    text = WAVES_DEL.read_text(encoding="utf-8")
    assert "<workflow_context>" in text and "</workflow_context>" in text, \
        "waves-delegation.md prompt template must contain <workflow_context> block"


def test_workflow_slice_block_substitution_documented() -> None:
    text = WAVES_DEL.read_text(encoding="utf-8")
    assert "${WORKFLOW_SLICE_BLOCK}" in text, \
        "block must use ${WORKFLOW_SLICE_BLOCK} substitution token"


def test_documents_none_fallback_for_non_workflow_tasks() -> None:
    text = WAVES_DEL.read_text(encoding="utf-8")
    # Should mention literal NONE substitution when workflow_id is null
    pattern = r"workflow_id\s*(?:==|is)?\s*null|non-workflow task"
    assert re.search(pattern, text, re.IGNORECASE), \
        "must document NONE substitution behavior when capsule.workflow_id is null"


def test_block_instructs_state_after_discipline() -> None:
    text = WAVES_DEL.read_text(encoding="utf-8")
    # Block must tell subagent to honor state_after declarations from WF spec
    assert "state_after" in text, \
        "block must instruct subagent to honor state_after declarations"


def test_workflow_state_drift_telemetry_declared() -> None:
    text = BUILD_MD.read_text(encoding="utf-8")
    assert "build.workflow_state_drift_detected" in text, \
        "build.md must declare workflow_state_drift_detected telemetry event"
