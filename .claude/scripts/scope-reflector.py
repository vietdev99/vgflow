#!/usr/bin/env python3
"""
scope-reflector.py — post-round reflection helper for /vg:scope.

OHOK v2 Day 5 finish — closes user point #4 (scope branching).

Prior state: /vg:scope runs 5 fixed rounds. After each round, decisions
accumulate. If a decision mentions "options A/B/C" but round advances
without sub-decisions for the chosen branch, unresolved implications
sneak into blueprint → executor surprises.

This helper reads the current CONTEXT.md, identifies "branching" decisions
(text mentions options/alternatives/forks), and flags those without
sub-decisions AND without explicit "finalized" note. Output consumed by:
- Scope skill step 4.5: decide whether to propose an extra round
- Acceptance reconciliation (already shipped Day 4): same check at final gate

Output formats:
- --format=json: machine-readable for orchestrator dispatch
- --format=prose: human-readable for interactive prompt
- --format=count: just the number (useful for shell conditionals)

Exit codes:
  0 — reflection succeeded (may have findings)
  1 — CONTEXT.md missing / unreadable
  2 — script error

Usage:
  python scope-reflector.py --phase <N>                 # default json
  python scope-reflector.py --phase <N> --format=count  # → "N"
  python scope-reflector.py --phase <N> --format=prose  # → user-facing
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"

# Decision header: `### P14.D-01:` OR `### D-01:`
DECISION_RE = re.compile(
    r"^###\s+(P[\d.]+\.)?D-(\d+(?:\.\d+)?)[:\s]",
    re.MULTILINE,
)
# Branching keywords in decision body
BRANCHING_KW_RE = re.compile(
    r"\b(option\s*[A-Z1-9]|alternative|branch(?:es)?|choice|tradeoff|"
    r"either|or\s+we|diverge|fork|option\s+[ab1])\b",
    re.IGNORECASE,
)
# "Finalized" explicit note
FINALIZED_RE = re.compile(
    r"\b(final(?:ized)?|locked|decided|chosen|rejected alternatives|"
    r"one-way|resolved\s+in)\b",
    re.IGNORECASE,
)


def find_phase_dir(phase: str) -> Path | None:
    for pattern in (f"{phase}-*", f"{phase.zfill(2)}-*", phase):
        matches = list(PHASES_DIR.glob(pattern))
        if matches:
            return matches[0]
    return None


def analyze(context_text: str) -> list[dict]:
    """Return list of findings — each an unresolved branching decision."""
    matches = list(DECISION_RE.finditer(context_text))
    if not matches:
        return []

    findings: list[dict] = []
    decision_ids = {m.group(2) for m in matches}

    for i, m in enumerate(matches):
        d_id = m.group(2)
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) \
            else len(context_text)
        body = context_text[block_start:block_end]

        branch_m = BRANCHING_KW_RE.search(body)
        if not branch_m:
            continue
        if FINALIZED_RE.search(body):
            continue

        # Sub-decision check: D-XX.Y with same base XX
        base_id = d_id.split(".")[0]
        has_subdecisions = any(
            other.startswith(f"{base_id}.")
            for other in decision_ids if other != d_id
        )
        if has_subdecisions:
            continue

        # Extract first 80-char snippet around branching keyword for context
        snippet_start = max(0, branch_m.start() - 30)
        snippet_end = min(len(body), branch_m.end() + 50)
        snippet = body[snippet_start:snippet_end].strip().replace("\n", " ")
        snippet = re.sub(r"\s+", " ", snippet)[:120]

        findings.append({
            "decision_id": f"D-{d_id}",
            "branching_keyword": branch_m.group(0),
            "snippet": snippet,
        })

    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--format", choices=["json", "prose", "count"],
                    default="json")
    args = ap.parse_args()

    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(f"\033[38;5;208mphase {args.phase} not found\033[0m", file=sys.stderr)
        return 1

    context = phase_dir / "CONTEXT.md"
    if not context.exists():
        print(f"\033[38;5;208m{context} not found\033[0m", file=sys.stderr)
        return 1

    text = context.read_text(encoding="utf-8", errors="replace")
    findings = analyze(text)

    if args.format == "count":
        print(len(findings))
    elif args.format == "prose":
        if not findings:
            print("✓ No unresolved branching — all option/alternative "
                  "decisions have sub-decisions or 'finalized' notes.")
            return 0
        print(f"\033[33m{len(findings)} unresolved branching decision(s):\033[0m")
        for f in findings:
            print(f"   • {f['decision_id']} mentions {f['branching_keyword']!r}: "
                  f"{f['snippet']}")
        print()
        print("Options:")
        print("  (a) Add sub-decisions D-XX.1 / D-XX.2 for each branch")
        print("  (b) Add explicit 'Finalized:' note with rationale")
        print("  (c) Run /vg:scope {phase} --deepen=D-XX for targeted drill-down")
    else:  # json
        print(json.dumps({
            "phase": args.phase,
            "unresolved_count": len(findings),
            "findings": findings,
        }, indent=2))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\033[38;5;208mscope-reflector crashed: {e}\033[0m", file=sys.stderr)
        sys.exit(2)
