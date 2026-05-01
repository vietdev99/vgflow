#!/usr/bin/env python3
"""Verify scanner asserted_quote per step matches business rule statement.

Closes Phase 3.2 dogfood gap: scanner can claim "passed" but assert against
its own paraphrase rather than the actual business rule. Code/test then
appear to verify the rule but actually verify a drifted statement.

Mechanism:
  1. Parse TEST-GOALS.md `expected_assertion` per goal (verbatim BR-NN text)
  2. Parse RUNTIME-MAP.json goal_sequences[gid].steps[].asserted_quote
  3. Cross-check Jaccard similarity ≥ 0.5 (allows minor wording but blocks
     drift like 'count threshold' → 'amount threshold')
  4. Cross-check `asserted_rule` field references actual BR-NN in DISCUSSION-LOG.md

Severity: BLOCK at /vg:review Phase 4.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402
from _traceability import (  # noqa: E402
    parse_goals_with_frontmatter,
    text_similarity,
    find_business_rule_in_log,
    infer_goal_class,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def collect_asserted_quotes(seq: dict) -> list[dict]:
    """Walk sequence steps and collect asserted_quote / asserted_rule fields.

    Scanner output schema (post-v2.46): each mutation step should have
    `asserted_quote: <verbatim BR-NN text>` and `asserted_rule: BR-NN`.
    """
    quotes: list[dict] = []
    steps = seq.get("steps") or []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        aq = step.get("asserted_quote") or step.get("assertion") or step.get("expected")
        ar = step.get("asserted_rule") or step.get("rule_id")
        if aq or ar:
            quotes.append(
                {
                    "step_idx": i,
                    "do": step.get("do") or step.get("action") or "?",
                    "asserted_quote": str(aq) if aq else "",
                    "asserted_rule": str(ar) if ar else "",
                }
            )
    return quotes


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify asserted_quote matches BR text")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.5,
    )
    parser.add_argument(
        "--allow-asserted-drift",
        action="store_true",
    )
    args = parser.parse_args()

    out = Output(validator="asserted-rule-match")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        runtime_path = phase_dir / "RUNTIME-MAP.json"
        log_path = phase_dir / "DISCUSSION-LOG.md"
        if not goals_path.exists() or not runtime_path.exists():
            emit_and_exit(out)

        goals = parse_goals_with_frontmatter(_read(goals_path))
        try:
            runtime = json.loads(_read(runtime_path))
        except json.JSONDecodeError:
            emit_and_exit(out)

        log_text = _read(log_path) if log_path.exists() else ""
        sequences = runtime.get("goal_sequences") or {}
        if not isinstance(sequences, dict):
            emit_and_exit(out)

        violations = 0
        for goal in goals:
            gid = goal["id"]
            seq = sequences.get(gid)
            if not isinstance(seq, dict):
                continue
            result = str(seq.get("result", "")).lower()
            if result not in {"passed", "pass", "ready", "yes"}:
                continue

            cls = infer_goal_class(goal)
            # Only mutation/approval/crud goals need asserted_quote
            if cls not in {"mutation", "approval", "crud-roundtrip", "wizard", "webhook"}:
                continue

            expected_assertion = goal.get("expected_assertion", "").strip()
            if not expected_assertion:
                continue  # No expected assertion declared; goal-traceability validator handles

            quotes = collect_asserted_quotes(seq)
            if not quotes:
                violations += 1
                out.add(
                    Evidence(
                        type="asserted_quote_missing",
                        message=(
                            f"{gid}: passed mutation goal but goal_sequences.steps has no "
                            f"asserted_quote field. Scanner must record verbatim quote of "
                            f"business rule per mutation step."
                        ),
                        file=str(runtime_path),
                        expected=f"steps[].asserted_quote matching expected_assertion",
                        fix_hint=(
                            "Update vg-haiku-scanner SKILL to record asserted_quote per "
                            "mutation step. See scanner-report-contract Section 2.X."
                        ),
                    ),
                    escalate=(args.severity == "block" and not args.allow_asserted_drift),
                )
                continue

            # Cross-check: at least one quote should ≥ similarity threshold
            best_sim = 0.0
            for q in quotes:
                if q["asserted_quote"]:
                    sim = text_similarity(expected_assertion, q["asserted_quote"])
                    if sim > best_sim:
                        best_sim = sim

            if best_sim < args.similarity_threshold:
                violations += 1
                out.add(
                    Evidence(
                        type="asserted_quote_drift",
                        message=(
                            f"{gid}: asserted_quote drift — best similarity {best_sim:.2f} "
                            f"< threshold {args.similarity_threshold} vs expected_assertion"
                        ),
                        file=str(runtime_path),
                        expected=expected_assertion[:120],
                        actual=quotes[0]["asserted_quote"][:120] if quotes else "",
                        fix_hint=(
                            "Scanner paraphrased rule; rerun and require verbatim quote. "
                            "Banned: scanner inventing assertion text."
                        ),
                    ),
                    escalate=(args.severity == "block" and not args.allow_asserted_drift),
                )

            # Cross-check: asserted_rule (if present) must exist in DISCUSSION-LOG
            for q in quotes:
                if q["asserted_rule"] and log_text:
                    if not find_business_rule_in_log(q["asserted_rule"], log_text):
                        violations += 1
                        out.add(
                            Evidence(
                                type="asserted_rule_unknown",
                                message=(
                                    f"{gid} step[{q['step_idx']}]: asserted_rule="
                                    f"'{q['asserted_rule']}' not found in DISCUSSION-LOG.md"
                                ),
                                file=str(runtime_path),
                                fix_hint="Define rule in DISCUSSION-LOG.md or fix asserted_rule field.",
                            ),
                            escalate=(args.severity == "block" and not args.allow_asserted_drift),
                        )

        if violations and (args.severity == "warn" or args.allow_asserted_drift):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} asserted_quote drift(s) downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
