"""tests/test_f1_codegen_verdict_gate.py — F1 test-spec codegen verdict gate."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
TS = REPO / "commands" / "vg" / "test-spec.md"


def test_codegen_step_has_post_spawn_gate():
    body = TS.read_text(encoding="utf-8")
    # Find step 4_codegen
    idx = body.find('<step name="4_codegen">')
    assert idx > 0
    # Within next 3500 chars must reference CODEGEN-MANIFEST or playwright spec count check
    block = body[idx:idx + 4000]
    assert ("CODEGEN-MANIFEST" in block or "spec_count" in block.lower() or "playwright" in block.lower() and "count" in block.lower()), (
        "F1: 4_codegen step must reference CODEGEN-MANIFEST file or spec count "
        "check post-Agent-spawn (current spawn is comment-only)"
    )


def test_codegen_manifest_existence_gate_present():
    body = TS.read_text(encoding="utf-8")
    # Use step tag search to get the actual step body, not YAML header reference
    idx = body.find('<step name="4_codegen">')
    assert idx > 0, "4_codegen step tag not found"
    block = body[idx:idx + 4500]
    # Must check manifest file existence (similar to Batch 15 F3 spec-review pattern)
    assert ("CODEGEN-MANIFEST.json" in block and ("[ -f" in block or "[ ! -f" in block or "is_file" in block)), (
        "F1: codegen step must gate marker on CODEGEN-MANIFEST.json existence "
        "(Agent must write the manifest; missing file = exit 1)"
    )
