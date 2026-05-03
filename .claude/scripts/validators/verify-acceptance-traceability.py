#!/usr/bin/env python3
"""Verify full traceability chain at /vg:accept: scanner → goal → decision → spec.

This is the FINAL gate before phase ships. Walks the chain end-to-end:
  scanner output (RUNTIME-MAP) → goal frontmatter → decision (CONTEXT) →
  business rule (DISCUSSION-LOG) → spec section (SPECS).

Each link must resolve. Any broken link = BLOCK accept.

Severity: BLOCK at /vg:accept hard gate.
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
    find_business_rule_in_log,
    find_decision_in_context,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify full traceability chain at accept")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument("--allow-traceability-gaps", action="store_true")
    args = parser.parse_args()

    out = Output(validator="acceptance-traceability")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        # Load all artifacts
        goals_text = _read(phase_dir / "TEST-GOALS.md")
        context_text = _read(phase_dir / "CONTEXT.md")
        log_text = _read(phase_dir / "DISCUSSION-LOG.md")
        specs_text = _read(phase_dir / "SPECS.md")
        runtime_path = phase_dir / "RUNTIME-MAP.json"

        if not goals_text:
            emit_and_exit(out)

        goals = parse_goals_with_frontmatter(goals_text)
        try:
            runtime = json.loads(_read(runtime_path)) if runtime_path.exists() else {}
        except json.JSONDecodeError:
            runtime = {}
        sequences = runtime.get("goal_sequences") or {}

        violations = 0
        chain_status: list[tuple[str, str, str]] = []  # (goal_id, link, status)

        for goal in goals:
            gid = goal["id"]
            seq = sequences.get(gid)
            result = str(seq.get("result", "") if isinstance(seq, dict) else "").lower()
            # Only verify goals claiming pass
            if result not in {"passed", "pass", "ready"}:
                continue

            # Link 1: scanner output → goal
            if not isinstance(seq, dict) or not seq.get("steps"):
                violations += 1
                out.add(
                    Evidence(
                        type="chain_broken_scanner_to_goal",
                        message=f"{gid}: scanner output missing or empty",
                    ),
                    escalate=(args.severity == "block" and not args.allow_traceability_gaps),
                )
                continue

            # Link 2: goal → decision
            for d_ref in goal.get("decisions") or []:
                local_id = d_ref.split(".")[-1]
                # Same-phase decisions resolved in CONTEXT
                if "." not in d_ref or d_ref.startswith("D-"):
                    if not find_decision_in_context(local_id, context_text):
                        violations += 1
                        out.add(
                            Evidence(
                                type="chain_broken_goal_to_decision",
                                message=f"{gid}: cites {d_ref} but not in CONTEXT.md",
                            ),
                            escalate=(args.severity == "block" and not args.allow_traceability_gaps),
                        )

            # Link 3: goal → business rule (DISCUSSION-LOG)
            if log_text:
                for rule_id in goal.get("business_rules") or []:
                    if not find_business_rule_in_log(rule_id, log_text):
                        violations += 1
                        out.add(
                            Evidence(
                                type="chain_broken_goal_to_rule",
                                message=f"{gid}: cites {rule_id} but not in DISCUSSION-LOG.md",
                            ),
                            escalate=(args.severity == "block" and not args.allow_traceability_gaps),
                        )

            # Link 4: goal → spec section
            spec_ref = goal.get("spec_ref", "")
            if spec_ref and "#" in spec_ref:
                _, anchor = spec_ref.split("#", 1)
                anchor_norm = anchor.lower().replace("_", "-").replace(" ", "-")
                found = False
                if specs_text:
                    for line in specs_text.splitlines():
                        if line.startswith("#"):
                            heading = line.lstrip("#").strip()
                            slug = re.sub(r"[^\w\s-]", "", heading.lower()).strip().replace(" ", "-")
                            if slug == anchor_norm or anchor_norm in slug:
                                found = True
                                break
                if not found:
                    violations += 1
                    out.add(
                        Evidence(
                            type="chain_broken_goal_to_spec",
                            message=f"{gid}: spec_ref='{spec_ref}' anchor not found in SPECS.md",
                        ),
                        escalate=(args.severity == "block" and not args.allow_traceability_gaps),
                    )

        if violations and (args.severity == "warn" or args.allow_traceability_gaps):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} traceability gap(s) downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
