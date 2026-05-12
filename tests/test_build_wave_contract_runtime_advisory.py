"""tests/test_build_wave_contract_runtime_advisory.py — Codex deferred Item 1."""
from __future__ import annotations
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POST_EXEC = REPO_ROOT / "commands" / "vg" / "_shared" / "build" / "post-execution-overview.md"
MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "build" / "post-execution-overview.md"


def test_post_execution_invokes_contract_runtime_advisory():
    """Wave-level verify-contract-runtime must run after each wave, advisory severity."""
    body = POST_EXEC.read_text(encoding="utf-8")
    assert "verify-contract-runtime.py" in body, (
        "post-execution must invoke verify-contract-runtime.py at wave close"
    )
    # Must be advisory (warn) not block
    assert "--severity warn" in body or "advisory" in body.lower() or "|| true" in body, (
        "wave-level invocation must be advisory (warn-only / non-blocking) — close.md owns BLOCK"
    )


def test_post_execution_documents_advisory_intent():
    body = POST_EXEC.read_text(encoding="utf-8")
    # Inline comment must explain why wave-level is ADVISORY not BLOCK
    pattern = re.compile(r"verify-contract-runtime.*?(?:advisory|warn|build close|terminal)", re.DOTALL)
    assert pattern.search(body), (
        "must document why wave-level is advisory (close.md owns the BLOCK)"
    )


def test_mirror_byte_identical():
    assert POST_EXEC.read_bytes() == MIRROR.read_bytes()
