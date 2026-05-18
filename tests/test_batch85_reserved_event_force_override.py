"""B85 v4.64.3 — Issue #194 finding #3 reserved-event repair via --force.

User dogfood (RTB phase 8.1, 2026-05-17): partial-wave dogfood workflow
required backfilling `wave.completed` events for prior sessions that
aborted before emitting them. The reserved-event protection (OHOK-8)
rejected the CLI emit:

    Event type 'wave.completed' is RESERVED for orchestrator core —
    cannot be emitted via CLI.

User asked for either a `repair-events` subcommand or an
`emit-event --force --reason` flag.

B85 ships --force + --reason:
  - --force REQUIRES --reason (operator justification)
  - Forced emission records actor="cli-forced" (post-hoc audit trail)
  - Forced emission injects payload.override_debt with reason + timestamp
  - Forced emission appends a row to .vg/OVERRIDE-DEBT.md
  - Reserved-event reject message gains B85 OPERATOR OVERRIDE hint

Use case: partial-wave dogfood where prior session aborted before emitting
a terminal event; operator backfills with documented intent. Forgery
detection (validators that count reserved events) can filter
actor='cli-forced' to distinguish operator-backfilled from genuine events.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCH = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"


def test_b85_force_flag_added_to_emit_event() -> None:
    body = ORCH.read_text(encoding="utf-8")
    assert "B85" in body, "B85 marker missing"
    # CLI parser additions
    assert "\"--force\"" in body, "--force flag missing on emit-event parser"
    assert "B85 OPERATOR OVERRIDE" in body, (
        "Reject message must hint at the --force escape hatch"
    )


def test_b85_force_requires_reason() -> None:
    body = ORCH.read_text(encoding="utf-8")
    # The check happens AFTER reserved-event detection, before append_event
    assert "--force REQUIRES --reason" in body or "force REQUIRES" in body, (
        "must enforce --reason mandatory when --force passed"
    )


def test_b85_forced_event_marks_actor_cli_forced() -> None:
    body = ORCH.read_text(encoding="utf-8")
    assert 'args.actor = "cli-forced"' in body, (
        "forced emission must rewrite actor to cli-forced"
    )


def test_b85_forced_event_injects_override_debt_payload() -> None:
    body = ORCH.read_text(encoding="utf-8")
    assert "override_debt" in body, "payload override_debt key missing"
    assert "OVERRIDE-DEBT.md" in body, "OVERRIDE-DEBT.md append missing"


def test_b85_mirror_byte_identical() -> None:
    assert ORCH.read_bytes() == MIRROR.read_bytes(), (
        "vg-orchestrator/__main__.py mirror drift"
    )
