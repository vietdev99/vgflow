#!/usr/bin/env python3
"""
Validator: verify-rule-phase-scope.py

Harness v2.6 Phase D (2026-04-26): hygiene gate for grandfathered rules
that fire across many phases without an explicit `phase_pattern` constraint.

Problem: rules learned in one milestone can leak into unrelated phases
because the default `phase_pattern: ".*"` matches everything. When a rule
fires across 3+ disjoint phases without ever having an explicit pattern
declared, that's a strong signal the operator should review whether the
rule is genuinely universal or accidentally over-broad.

This validator scans `.vg/events.jsonl` for rule-fire events
(bootstrap.rule_promoted, bootstrap.candidate_surfaced, validation.failed
referencing a rule id) and counts distinct phases per rule. For rules with
no explicit `phase_pattern` (or `phase_pattern == ".*"`) AND fired in 3+
distinct phases, emit a WARN suggesting the operator either narrow the
pattern OR confirm `.*` explicitly via the schema.

Severity: WARN — hygiene only, never BLOCK. Surfaces at /vg:accept.

Skip when:
  - .vg/events.jsonl is missing (PASS, no data)
  - .vg/bootstrap/ACCEPTED.md missing (PASS, no rules to evaluate)
  - All rules already declare an explicit phase_pattern

Usage:
  verify-rule-phase-scope.py
  verify-rule-phase-scope.py --threshold 5     # custom phase count threshold

Output: canonical validator JSON
  {"validator": "verify-rule-phase-scope",
   "verdict": "PASS|WARN|BLOCK", ...}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Rule-fire event types — broad set to maximize signal
RULE_FIRE_EVENT_TYPES = {
    "bootstrap.rule_promoted",
    "bootstrap.rule_demoted",
    "bootstrap.candidate_surfaced",
    "bootstrap.candidate_drafted",
    "validation.failed",
}

# Phase number pattern (e.g. 7.14.3, 12, 14.0.1)
PHASE_NUMBER_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


def _scan_events_for_rule_phases(events_path: Path) -> dict[str, set[str]]:
    """Build map of {rule_id -> set(phase_numbers)} from events.jsonl.

    Reads each event line, extracts a rule id from the payload (multiple
    field names possible: id, rule_id, candidate_id), and the phase number
    from the payload or top-level event. Robust to malformed lines —
    skip silently.
    """
    rule_phases: dict[str, set[str]] = {}
    if not events_path.exists():
        return rule_phases

    try:
        lines = events_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rule_phases

    for raw in lines:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue

        evt_type = evt.get("type") or evt.get("event_type") or ""
        if evt_type not in RULE_FIRE_EVENT_TYPES:
            continue

        # Extract payload (sometimes nested as JSON string)
        payload = evt.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}

        # Find rule id (multiple naming conventions)
        rule_id = (
            payload.get("id")
            or payload.get("rule_id")
            or payload.get("candidate_id")
            or evt.get("rule_id")
        )
        if not rule_id or not isinstance(rule_id, str):
            continue

        # Find phase number
        phase = (
            payload.get("phase")
            or payload.get("phase_number")
            or evt.get("phase")
            or evt.get("phase_number")
        )
        if not phase or not isinstance(phase, str):
            continue
        if not PHASE_NUMBER_RE.match(phase):
            continue

        rule_phases.setdefault(rule_id, set()).add(phase)

    return rule_phases


def _load_accepted_rules(accepted_path: Path) -> dict[str, dict]:
    """Parse ACCEPTED.md → {rule_id -> {pattern, explicit}}.

    `explicit` distinguishes operator-confirmed universal scope (`.*` declared)
    from grandfather default (no field at all). Validator silences WARN only
    for explicit declarations.
    """
    rules: dict[str, dict] = {}
    if not accepted_path.exists():
        return rules

    try:
        text = accepted_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rules

    # Split on rule headers — each block starts at "- id: L-..." or "id: L-..."
    blocks = re.split(r"(?m)^(?:-\s+)?id:\s*", text)
    for block in blocks[1:]:  # skip preamble
        m_id = re.match(r"\"?([A-Za-z0-9_\-]+)\"?", block)
        if not m_id:
            continue
        rule_id = m_id.group(1).strip()
        block_chunk = block[: 4000]  # cap to one rule
        m_pat = re.search(
            r'phase_pattern:\s*"([^"]*)"|phase_pattern:\s*([^\s,#]+)',
            block_chunk,
        )
        if m_pat:
            pat = (m_pat.group(1) or m_pat.group(2) or ".*").strip()
            rules[rule_id] = {"pattern": pat, "explicit": True}
        else:
            rules[rule_id] = {"pattern": ".*", "explicit": False}

    return rules


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", help="(orchestrator-injected; ignored — scans all rules)")
    ap.add_argument(
        "--threshold",
        type=int,
        default=3,
        help="Min distinct phases that triggers WARN for grandfathered rule (default 3)",
    )
    args = ap.parse_args()

    out = Output(validator="verify-rule-phase-scope")
    with timer(out):
        events_path = REPO_ROOT / ".vg" / "events.jsonl"
        accepted_path = REPO_ROOT / ".vg" / "bootstrap" / "ACCEPTED.md"

        # Graceful skip when no telemetry data exists yet
        if not events_path.exists():
            emit_and_exit(out)

        rule_phases = _scan_events_for_rule_phases(events_path)
        if not rule_phases:
            # No rule-fire events found → nothing to evaluate
            emit_and_exit(out)

        accepted_rules = _load_accepted_rules(accepted_path)

        threshold = max(1, args.threshold)
        suspects: list[dict] = []

        for rule_id, phases in sorted(rule_phases.items()):
            if len(phases) < threshold:
                continue
            # Look up declared pattern; absent rule treated as implicit grandfather
            spec = accepted_rules.get(rule_id, {"pattern": ".*", "explicit": False})
            # Silence WARN when operator EXPLICITLY declared a pattern (any
            # value, including ".*" — that's an explicit universal-scope
            # confirmation). Only IMPLICIT grandfather drift surfaces.
            if spec.get("explicit"):
                continue
            # Compute suggested narrow pattern from major components
            majors = sorted({p.split(".")[0] for p in phases})
            if len(majors) == 1:
                suggested = f"^{majors[0]}\\."
            elif len(majors) == 2:
                suggested = f"^({majors[0]}|{majors[1]})\\."
            else:
                # 3+ majors — rule may genuinely be universal; suggest explicit ".*"
                suggested = ".*  (3+ disjoint majors — confirm universal scope)"
            suspects.append({
                "rule_id": rule_id,
                "distinct_phases": sorted(phases),
                "phase_count": len(phases),
                "suggested_pattern": suggested,
            })

        if suspects:
            sample = "; ".join(
                f"{s['rule_id']} fired in {s['phase_count']} phases "
                f"({', '.join(s['distinct_phases'][:4])}{'…' if s['phase_count'] > 4 else ''}) "
                f"→ suggest {s['suggested_pattern']}"
                for s in suspects[:5]
            )
            evidence = Evidence(
                type="rule_phase_scope_unconstrained",
                message=(
                    f"{len(suspects)} rule(s) fired in {threshold}+ distinct phases "
                    f"without explicit phase_pattern (silent global drift risk)"
                ),
                actual=sample,
                fix_hint=(
                    "Review each suspect rule. Either:\n"
                    "  (a) narrow the pattern (e.g. `phase_pattern: \"^7\\\\.\"`) if the rule is "
                    "milestone-local — edit `.vg/bootstrap/ACCEPTED.md` directly, OR\n"
                    "  (b) confirm explicit `phase_pattern: \".*\"` to acknowledge universal scope.\n"
                    "Either path silences this WARN. Default-grandfather without confirmation "
                    "leaves the door open for unrelated phases to trip rules accidentally."
                ),
            )
            out.warn(evidence)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
