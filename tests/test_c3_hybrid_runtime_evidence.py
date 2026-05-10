"""v2.68.0 C3 — Hybridize runtime-evidence.py.

Verifies that runtime-evidence.py adopts a hybrid (deterministic-then-LLM-fallback)
verdict model: it must define an AMBIGUOUS branch alongside PASS/FAIL, emit a
confidence score (high|medium|low), and document the LLM-fallback path so
downstream reviewers know to break ties on ambiguous evidence.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_EVIDENCE = REPO_ROOT / "scripts" / "validators" / "runtime-evidence.py"


def test_runtime_evidence_has_ambiguous_branch() -> None:
    """runtime-evidence.py must handle ambiguous case (v2.68.0 C3)."""
    src = RUNTIME_EVIDENCE.read_text(encoding="utf-8")
    assert re.search(r"ambiguous|AMBIGUOUS", src), (
        "runtime-evidence.py must handle ambiguous case (v2.68.0 C3)"
    )


def test_runtime_evidence_emits_confidence() -> None:
    """runtime-evidence.py must emit confidence score (high/medium/low)."""
    src = RUNTIME_EVIDENCE.read_text(encoding="utf-8")
    assert re.search(r"confidence", src, re.IGNORECASE), (
        "runtime-evidence.py must emit confidence score"
    )


def test_runtime_evidence_documents_llm_fallback() -> None:
    """runtime-evidence.py must document LLM-fallback for AMBIGUOUS verdicts."""
    src = RUNTIME_EVIDENCE.read_text(encoding="utf-8")
    assert re.search(
        r"(?:LLM|crossai|reviewer)\s+(?:fallback|judge|judgment|review)",
        src,
        re.IGNORECASE,
    ), "must document LLM fallback path"
