"""Stage 6 task 3/5 — causal misattribution regression (Codex #9).

End-to-end check that the cargo-cult prevention chain still holds:

  1. orchestrator `emit-event bootstrap.outcome_recorded` rejects procedural
     outcomes with empty `executed_step_ids[]`. Without this gate, an
     executor that bypasses the rule's sequence entirely could log PASS for
     the rule and falsely promote it.
  2. prober `bootstrap-attribute-outcome.py`, given a deploy log where the
     executor ran a totally different command, returns
     `executed_step_ids == []`. Combined with #1, this means the outcome
     event will be rejected at the orchestrator gate.

Together these cover the "promote rule → fire it → executor bypasses
sequence → attribution rejection" loop the design doc Section 13.4 calls
out as the core cargo-cult prevention.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
ORCHESTRATOR = str(REPO / ".claude" / "scripts" / "vg-orchestrator")
PROBER = str(REPO / ".claude" / "scripts" / "bootstrap-attribute-outcome.py")


def _attribution_rejection(result: subprocess.CompletedProcess) -> bool:
    text = (result.stderr + result.stdout).lower()
    return (
        "attribution" in text
        or "executed_step" in text
        or "cargo-cult" in text
        or "bypassed sequence" in text
        or "bypass" in text
    )


def test_outcome_with_empty_executed_steps_rejected_by_orchestrator():
    """Codex #9 cargo-cult prevention — orchestrator emit-event MUST reject
    a procedural outcome with empty executed_step_ids[]."""
    payload = {
        "slug": "test-rule",
        "rule_type": "procedural",
        "attribution": {
            "executed_step_ids": [],
            "total_steps": 2,
            "matched_signals_count": 0,
        },
    }
    result = subprocess.run(
        [
            sys.executable, ORCHESTRATOR, "emit-event",
            "bootstrap.outcome_recorded",
            "--actor", "orchestrator",
            "--outcome", "PASS",
            "--payload", json.dumps(payload),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, (
        f"orchestrator MUST reject empty executed_step_ids; got rc=0\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert _attribution_rejection(result), (
        f"expected attribution-gate rejection signature; got\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


def test_prober_returns_empty_when_executor_bypassed(tmp_path):
    """Prober + outcome gate together: when the executor ran a totally
    different command than the rule's sequence specifies, the prober MUST
    return executed_step_ids=[] so the orchestrator gate (above) rejects."""
    rule = tmp_path / "rule.md"
    rule.write_text(
        "---\n"
        "slug: x\n"
        "type: procedural\n"
        "authority: advisory\n"
        "target_step: deploy\n"
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"expected-cmd\"\n"
        "    expected_signals: []\n"
        "success_signals: []\n"
        "attribution_required: true\n"
        "---\n",
        encoding="utf-8",
    )
    log = tmp_path / "log.txt"
    # Executor bypasses: ran a totally different command. Prober should
    # see no match for s1's cmd → empty executed_step_ids.
    log.write_text(
        "$ totally-different-cmd\noutput\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable, PROBER,
            "--rule", str(rule),
            "--log", str(log),
            "--json",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"prober failed: rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert payload["executed_step_ids"] == [], (
        f"bypassed executor → empty executed_step_ids; got {payload}"
    )
