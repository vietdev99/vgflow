"""tests/test_h4_idempotency_default_off.py — Batch 7 H4 safety gates.

Verifies:
1. runtime.md 5b-2 is OFF unless config.test.idempotency.enabled=true.
2. runtime.md 5b-2 HARD-GATEs against production-like ENVIRONMENT values.
3. config templates document the test.idempotency.* block.
4. Skip behavior is observable (event/log line) so user knows why skipped.
"""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
RUNTIME = REPO / "commands" / "vg" / "_shared" / "test" / "runtime.md"
CONFIG = REPO / "vg.config.template.md"
MIRROR_CONFIG = REPO / ".claude" / "templates" / "vg" / "vg.config.template.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_idempotency_default_off():
    body = _read(RUNTIME)
    # Must check config.test.idempotency.enabled before running
    assert "test.idempotency.enabled" in body or "IDEMPOTENCY_ENABLED" in body, (
        "H4: 5b-2 must gate on config.test.idempotency.enabled (default false). "
        "Currently auto-ON for billing/auth/payment/payout/transaction domains."
    )
    # Must reference the gate location
    assert "Skip if" in body and "idempotency" in body.lower()


def test_idempotency_production_hard_gate():
    body = _read(RUNTIME)
    # Must refuse production-like ENVIRONMENT
    assert ("ENVIRONMENT" in body and "production" in body.lower()) or "PROD_GUARD" in body, (
        "H4: 5b-2 must HARD-GATE when ENVIRONMENT in (production, prod, live). "
        "Cannot pollute production with double-POSTs of real Bearer-token payloads."
    )


def test_config_documents_idempotency_block():
    body = _read(CONFIG)
    assert "idempotency" in body.lower(), (
        "H4: vg.config.template.md must document test.idempotency.{enabled,allowed_envs} block"
    )
    assert "enabled" in body and "allowed_envs" in body, (
        "H4: config block must expose enabled + allowed_envs keys"
    )


def test_skip_emits_observable_signal():
    body = _read(RUNTIME)
    # Skip path must echo a reason (not silent skip)
    skip_block_start = body.find("test.idempotency.enabled")
    if skip_block_start == -1:
        skip_block_start = body.find("IDEMPOTENCY_ENABLED")
    assert skip_block_start > 0
    skip_block = body[skip_block_start:skip_block_start + 600]
    assert "echo" in skip_block or "emit-event" in skip_block, (
        "H4: skip path must emit reason — silent skip hides safety behavior from user"
    )


def test_mirror_config():
    if MIRROR_CONFIG.is_file():
        assert _read(CONFIG) == _read(MIRROR_CONFIG)
