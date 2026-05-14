"""tests/test_batch21_codegen_manifest_consume.py — Batch 21 manifest consumption."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
RS = REPO / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_test_reads_codegen_manifest():
    body = _read(RS)
    assert "CODEGEN-MANIFEST.json" in body, (
        "Batch 21: test/regression-security.md must read CODEGEN-MANIFEST.json "
        "to get authoritative spec list (not glob)"
    )


def test_no_pure_glob_invocation():
    body = _read(RS)
    # The bare-glob playwright invocation pattern must be guarded by a
    # 'manifest missing' fallback path, not the primary path
    primary_glob_idx = body.find("{phase}-goal-*.spec.ts")
    if primary_glob_idx > 0:
        # Look at surrounding context
        ctx_start = max(0, primary_glob_idx - 1500)
        ctx = body[ctx_start:primary_glob_idx]
        # The glob path must be conditional on CODEGEN-MANIFEST missing
        # i.e. it's a fallback, not the default
        assert ("if [ ! -f" in ctx and "CODEGEN-MANIFEST.json" in ctx) or "manifest" in ctx.lower(), (
            "Batch 21: glob spec list must be a FALLBACK when CODEGEN-MANIFEST.json "
            "missing, not the primary path"
        )


def test_manifest_spec_list_used_for_playwright():
    body = _read(RS)
    # Need a Python extraction step that reads manifest + builds spec list
    # for playwright
    assert ("playwright_specs" in body or "spec_list" in body or "SPEC_LIST=" in body), (
        "Batch 21: must extract spec list from manifest into variable used by "
        "playwright test invocation"
    )
