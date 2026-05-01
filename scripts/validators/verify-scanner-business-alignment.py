#!/usr/bin/env python3
"""Adversarial verifier: did scanner test the SAME flow goal claimed?

Closes Phase 3.2 dogfood gap: scanner can RCRURD-correctly walk through a
flow but the flow tested is NOT the flow goal claims to verify. Validators
above (rcrurd-depth, asserted-rule-match) catch structural drift but not
semantic drift like "tested generic flag, not specifically count threshold".

This validator spawns an isolated Haiku subagent (zero parent context) to
read goal frontmatter + scanner steps + expected_assertion, then adjudicate:
  Q: "Did scanner steps actually verify expected_assertion or did they
      shortcut/drift to a different verification path?"

The fresh-context constraint prevents echo chamber — verifier doesn't see
why scanner made its choices, only the artifact text.

Severity: BLOCK at /vg:review Phase 4. Tunable via VG_VERIFIER_TIMEOUT_S.

Implementation: this validator emits a structured prompt to a stdout
"verifier_request" record. The orchestrator (review.md Phase 4) reads
records, spawns Haiku via Agent tool, feeds prompt, parses verdict, and
re-runs this validator with --verifier-results consuming the verdict file.
This decouples the spawn (orchestrator-only capability) from the gate logic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402
from _traceability import (  # noqa: E402
    parse_goals_with_frontmatter,
    infer_goal_class,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def build_verifier_prompt(goal: dict, seq: dict) -> str:
    """Build adversarial verifier prompt for one goal."""
    steps = seq.get("steps") or []
    return f"""You are an adversarial verifier with ZERO parent context. Your only job:
adjudicate whether the scanner output below ACTUALLY verifies the goal's
expected_assertion, or drifted to a different verification path.

# Goal {goal['id']}
Title: {goal['title']}
Priority: {goal.get('priority')}
Surface: {goal.get('surface')}
Goal class: {goal.get('goal_class') or infer_goal_class(goal)}

## Expected assertion (verbatim from business rule)
{goal.get('expected_assertion', '<not declared>')}

## Decisions cited
{', '.join(goal.get('decisions') or ['<none>'])}

## Business rules cited
{', '.join(goal.get('business_rules') or ['<none>'])}

# Scanner steps[]  ({len(steps)} entries)
{json.dumps(steps, indent=2, ensure_ascii=False)[:4000]}

# Adjudicate (return JSON)
{{
  "goal_id": "{goal['id']}",
  "alignment": "yes" | "no" | "partial",
  "drift_type": "none" | "wrong_flow" | "shallow" | "fabricated" | "rationalized",
  "evidence": "<verbatim quote from scanner steps that proves OR disproves alignment>",
  "missing_actions": ["<action expected by assertion but absent from steps>", "..."],
  "summary": "<1-sentence verdict>"
}}

Hard rules:
- alignment="yes" ONLY if steps clearly perform the action described in
  expected_assertion AND verify the postcondition.
- alignment="no" if steps test something different, even partially.
- "rationalized" drift = scanner classified error as 'expected security' or
  similar, instead of recording verbatim error.
- "fabricated" drift = steps claim outcomes not supported by network/console evidence.
- Be skeptical. Default to "no" / "partial" unless evidence is unambiguous.

Output ONLY the JSON object. No prose.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Adversarial scanner-business alignment verifier")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument(
        "--verifier-results",
        type=Path,
        help="Path to JSONL file with verifier verdicts (one per goal). "
             "When provided, validator gates on these. When absent, validator "
             "emits prompts only (orchestrator must spawn verifier separately).",
    )
    parser.add_argument(
        "--prompts-out",
        type=Path,
        help="Path to write verifier prompts JSONL (orchestrator consumes to spawn).",
    )
    parser.add_argument(
        "--allow-business-drift",
        action="store_true",
    )
    args = parser.parse_args()

    out = Output(validator="scanner-business-alignment")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        runtime_path = phase_dir / "RUNTIME-MAP.json"
        if not goals_path.exists() or not runtime_path.exists():
            emit_and_exit(out)

        goals = parse_goals_with_frontmatter(_read(goals_path))
        try:
            runtime = json.loads(_read(runtime_path))
        except json.JSONDecodeError:
            emit_and_exit(out)
        sequences = runtime.get("goal_sequences") or {}

        # Phase 1: emit prompts for each goal that needs verification
        prompts: list[dict] = []
        for goal in goals:
            gid = goal["id"]
            seq = sequences.get(gid)
            if not isinstance(seq, dict):
                continue
            if str(seq.get("result", "")).lower() not in {"passed", "pass", "ready"}:
                continue
            cls = infer_goal_class(goal)
            if cls not in {"mutation", "approval", "crud-roundtrip", "wizard", "webhook"}:
                continue
            if not goal.get("expected_assertion"):
                continue
            prompts.append(
                {
                    "goal_id": gid,
                    "prompt": build_verifier_prompt(goal, seq),
                }
            )

        # If --prompts-out, write and exit (orchestrator will spawn verifier)
        if args.prompts_out:
            args.prompts_out.parent.mkdir(parents=True, exist_ok=True)
            with args.prompts_out.open("w", encoding="utf-8") as f:
                for p in prompts:
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")
            out.add(
                Evidence(
                    type="prompts_emitted",
                    message=f"Emitted {len(prompts)} verifier prompts to {args.prompts_out}",
                ),
                escalate=False,
            )
            emit_and_exit(out)

        # Phase 2: gate on verifier-results if provided
        if not args.verifier_results or not args.verifier_results.exists():
            # No verdicts available — degrade to advisory
            out.add(
                Evidence(
                    type="verifier_not_run",
                    message=(
                        f"{len(prompts)} goal(s) need adversarial verification but no "
                        f"--verifier-results provided. Orchestrator must spawn verifier first."
                    ),
                    fix_hint=(
                        "Run validator twice: (1) --prompts-out=path emits prompts, "
                        "(2) orchestrator spawns Haiku per prompt, (3) re-run with "
                        "--verifier-results=results.jsonl to gate."
                    ),
                ),
                escalate=False,
            )
            emit_and_exit(out)

        # Parse verdicts
        verdicts: dict[str, dict] = {}
        for line in args.verifier_results.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
                if "goal_id" in v:
                    verdicts[v["goal_id"]] = v
            except json.JSONDecodeError:
                continue

        violations = 0
        for p in prompts:
            gid = p["goal_id"]
            verdict = verdicts.get(gid)
            if not verdict:
                violations += 1
                out.add(
                    Evidence(
                        type="verifier_verdict_missing",
                        message=f"{gid}: no verifier verdict in {args.verifier_results}",
                    ),
                    escalate=(args.severity == "block" and not args.allow_business_drift),
                )
                continue

            alignment = verdict.get("alignment", "unknown").lower()
            if alignment != "yes":
                violations += 1
                out.add(
                    Evidence(
                        type="business_alignment_failed",
                        message=(
                            f"{gid}: adversarial verifier returned alignment='{alignment}' "
                            f"drift_type='{verdict.get('drift_type', '?')}'. "
                            f"Summary: {verdict.get('summary', '')}"
                        ),
                        actual=str(verdict.get("evidence", ""))[:200],
                        expected=str(verdict.get("missing_actions", "")),
                        fix_hint=(
                            "Re-run /vg:review for this goal with explicit instruction to "
                            "perform missing_actions. Scanner shortcut detected."
                        ),
                    ),
                    escalate=(args.severity == "block" and not args.allow_business_drift),
                )

        if violations and (args.severity == "warn" or args.allow_business_drift):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} alignment failures downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
