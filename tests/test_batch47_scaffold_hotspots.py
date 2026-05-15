"""tests/test_batch47_scaffold_hotspots.py — Batch 47.

scaffold-detector.py findings after Batch 46:
- C HIGH (failure swallow): build.md + deploy/persist-and-close.md silently
  swallow run-complete failures with `|| true`. Pipeline-end mark fires
  even when orchestrator detects integrity issues.
- H LOW (glob bypass): codegen/delegation.md uses Python rglob(*.spec.ts)
  for R7 console check when CODEGEN-MANIFEST.json is canonical source.

Fix: capture rc + emit event on failure; switch glob to manifest read.
"""
from __future__ import annotations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "commands" / "vg" / "build.md"
DEPLOY_CLOSE = REPO / "commands" / "vg" / "_shared" / "deploy" / "persist-and-close.md"
CODEGEN_DEL = REPO / "commands" / "vg" / "_shared" / "test" / "codegen" / "delegation.md"


def test_build_partial_wave_run_complete_captures_rc():
    body = BUILD.read_text(encoding="utf-8")
    idx = body.find('run-complete --partial-wave')
    assert idx > 0
    block = body[idx:idx + 600]
    # Must capture rc (no double || true swallow)
    assert "PARTIAL_RC=$?" in block or "RUN_COMPLETE_RC=$?" in block or "PARTIAL_WAVE_RC" in block, (
        "Batch 47 C: build.md partial-wave run-complete must capture rc, "
        "not double `|| true` swallow"
    )


def test_deploy_persist_close_captures_run_complete_rc():
    body = DEPLOY_CLOSE.read_text(encoding="utf-8")
    # Use rfind: capture happens in LAST run-complete bash block (the actual call)
    idx = body.rfind("vg-orchestrator run-complete")
    assert idx > 0
    block = body[idx:idx + 600]
    assert "RUN_COMPLETE_RC" in block or "DEPLOY_RC=$?" in block, (
        "Batch 47 C: deploy/persist-and-close.md must capture run-complete rc, "
        "not pipe to tail with `|| true` swallow"
    )
    assert "deploy.run_complete_failed" in body, "must emit event on rc!=0"


def test_codegen_delegation_prefers_manifest_over_glob():
    body = CODEGEN_DEL.read_text(encoding="utf-8")
    idx = body.find('tests_dir.rglob("*.spec.ts")')
    assert idx > 0
    block = body[max(0, idx - 1500):idx + 500]
    # Must check CODEGEN-MANIFEST first
    assert "CODEGEN-MANIFEST" in block, (
        "Batch 47 H: codegen/delegation.md R7 console check must read "
        "CODEGEN-MANIFEST.json before falling back to glob"
    )


def test_mirrors_in_sync():
    for src in [BUILD, DEPLOY_CLOSE, CODEGEN_DEL]:
        mirror = REPO / ".claude" / src.relative_to(REPO)
        assert src.read_text(encoding="utf-8") == mirror.read_text(encoding="utf-8")
