"""Stage 3 task 3/3 of meta-memory v1.1 (Codex #9 / design Section 13.4):
gate bootstrap.outcome_recorded for procedural rules.

Without this gate, rule fires + phase passes → rule logged PASS even when
executor bypassed sequence entirely → cargo-cult promotion. This test
locks the gate behavior:

  * procedural rule WITHOUT attribution.executed_step_ids   → reject (rc != 0)
  * procedural rule WITH empty   attribution.executed_step_ids → reject
  * procedural rule WITH full    attribution                → accept
  * declarative rule (any payload)                          → accept
  * legacy event (no rule_type)                             → accept (treated as declarative)
  * other event types (e.g. bootstrap.rule_fired)           → unaffected by gate

CLI uses `--payload <JSON>` (the orchestrator's existing flag), not `--metadata`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ORCHESTRATOR = str(REPO / ".claude" / "scripts" / "vg-orchestrator")


def _emit_event(payload: dict,
                event_type: str = "bootstrap.outcome_recorded",
                outcome: str = "PASS") -> subprocess.CompletedProcess:
    """Run vg-orchestrator emit-event with given payload. Returns CompletedProcess.

    Note: when no active run exists, _resolve_emit_event_target returns rc=1
    AFTER the attribution gate. So an event that PASSES the gate may still
    return rc=1 due to "No active run". Tests differentiate by inspecting
    stderr — the attribution rejection has a unique signature.
    """
    return subprocess.run(
        [sys.executable, ORCHESTRATOR, "emit-event", event_type,
         "--actor", "orchestrator",
         "--outcome", outcome,
         "--payload", json.dumps(payload)],
        capture_output=True, text=True,
    )


def _attribution_rejection(result: subprocess.CompletedProcess) -> bool:
    """True iff stderr/stdout signal an attribution-gate rejection."""
    text = (result.stderr + result.stdout).lower()
    return ("attribution" in text or "executed_step" in text or
            "cargo-cult" in text or "bypassed sequence" in text)


def _no_active_run_only(result: subprocess.CompletedProcess) -> bool:
    """True iff the only failure path is the post-gate 'no active run' branch."""
    text = result.stderr + result.stdout
    return "No active run" in text and not _attribution_rejection(result)


def test_procedural_outcome_without_attribution_rejected():
    """Procedural rule outcome MUST have attribution.executed_step_ids."""
    result = _emit_event({"slug": "test-rule", "rule_type": "procedural"})
    assert result.returncode != 0, (
        f"expected reject; got rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert _attribution_rejection(result), (
        f"expected attribution-gate rejection signature; got\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_procedural_outcome_with_empty_executed_steps_rejected():
    """Empty executed_step_ids = executor bypassed = reject (cargo-cult prevention)."""
    result = _emit_event({
        "slug": "test-rule",
        "rule_type": "procedural",
        "attribution": {
            "executed_step_ids": [],
            "total_steps": 2,
            "matched_signals_count": 0,
        },
    })
    assert result.returncode != 0, (
        f"expected reject; got rc={result.returncode}\n"
        f"stderr: {result.stderr}"
    )
    assert _attribution_rejection(result), (
        f"expected attribution-gate rejection; got\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_procedural_outcome_with_full_attribution_passes_gate():
    """Procedural rule with full attribution payload PASSES the attribution gate.

    The orchestrator may still rc=1 with 'No active run' (downstream of the
    gate) — that's not the gate rejecting; it's the resolver. We assert the
    gate rejection signature is ABSENT.
    """
    result = _emit_event({
        "slug": "test-rule",
        "rule_type": "procedural",
        "attribution": {
            "executed_step_ids": ["s1", "s2"],
            "total_steps": 2,
            "matched_signals_count": 2,
            "sequence_checksum": "abc123def456",
        },
    })
    assert not _attribution_rejection(result), (
        f"attribution gate must NOT fire for full-attribution payload; got\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Either rc=0 (active run exists in env) or rc=1 with 'No active run' is OK.
    assert result.returncode == 0 or _no_active_run_only(result), (
        f"unexpected rc/error: rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_declarative_outcome_no_attribution_required():
    """Non-procedural rules (declarative) don't need attribution payload — gate skipped."""
    result = _emit_event({"slug": "test-decl", "rule_type": "declarative"})
    assert not _attribution_rejection(result), (
        f"attribution gate must NOT fire for declarative rules; got\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.returncode == 0 or _no_active_run_only(result)


def test_outcome_without_rule_type_treated_as_declarative():
    """Backwards compat: legacy events without rule_type field → not procedural → accept."""
    result = _emit_event({"slug": "legacy-rule"})
    assert not _attribution_rejection(result), (
        f"attribution gate must NOT fire for legacy events without rule_type; got\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.returncode == 0 or _no_active_run_only(result)


def test_other_event_types_unaffected():
    """Gate ONLY applies to bootstrap.outcome_recorded. Other event types accept normally.

    bootstrap.rule_fired is NOT reserved (validators emit it directly, but CLI
    is not blocked); it carries no attribution requirement at the CLI gate.
    """
    result = _emit_event(
        {"slug": "test", "rule_type": "procedural"},
        event_type="bootstrap.rule_fired",
    )
    assert not _attribution_rejection(result), (
        f"attribution gate must NOT fire for non-outcome events; got\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.returncode == 0 or _no_active_run_only(result)
