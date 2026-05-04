#!/usr/bin/env python3
"""
Validator: context-structure.py

Purpose: CONTEXT.md produced by /vg:scope must have enriched decisions, not
just headers. Audit found phases where CONTEXT had 0 decisions or decisions
without Endpoints/Test Scenarios subsections → blueprint planned against
empty context → downstream junk.

Checks:
- File exists + >=500 bytes
- Contains at least 1 decision header (### P{X}.D-NN or ### D-NN)
- At least 50% of decisions have Endpoints OR Test Scenarios subsection
- Each decision has at least 1 non-header content line

Usage: context-structure.py --phase <N>
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"


DECISION_RE = re.compile(r"^### (P[\d.]+\.)?D-(\d+)[:\s]", re.MULTILINE)
ENDPOINTS_RE = re.compile(r"^\*\*Endpoints?:\*\*|^- .+ /api/", re.MULTILINE)
TESTS_RE = re.compile(r"^\*\*Test Scenarios?:\*\*|^- TS-\d+", re.MULTILINE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="context-structure")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        phase_dirs = [phase_dir] if phase_dir else []
        if not phase_dirs:
            out.add(Evidence(type="missing_file",
                             message=f"phase dir for {args.phase} not found"))
            emit_and_exit(out)

        context = phase_dirs[0] / "CONTEXT.md"
        if not context.exists():
            out.add(Evidence(type="missing_file",
                             message="CONTEXT.md missing",
                             file=str(context),
                             fix_hint="Run /vg:scope <phase> to produce CONTEXT.md"))
            emit_and_exit(out)

        size = context.stat().st_size
        if size < 500:
            out.add(Evidence(
                type="empty_file",
                message=f"CONTEXT.md is {size} bytes — too shallow for meaningful planning",
                file=str(context),
                expected=">=500 bytes",
                actual=size,
                fix_hint="Re-run /vg:scope — ensure decisions are enriched with rationale.",
            ))
            emit_and_exit(out)

        text = context.read_text(encoding="utf-8", errors="replace")
        decisions = DECISION_RE.findall(text)
        decision_count = len(decisions)

        if decision_count == 0:
            out.add(Evidence(
                type="count_below_threshold",
                message="0 decision headers found (expected ### D-XX or ### P{x}.D-XX)",
                file=str(context),
                expected=">=1",
                actual=0,
                fix_hint="scope.md must emit decisions; re-run with --auto=false to force discussion.",
            ))
            emit_and_exit(out)

        # Split into decision blocks to check enrichment per-decision
        block_starts = [m.start() for m in DECISION_RE.finditer(text)]
        block_starts.append(len(text))  # sentinel
        blocks = [text[block_starts[i]:block_starts[i+1]]
                  for i in range(decision_count)]

        enriched = sum(
            1 for b in blocks
            if ENDPOINTS_RE.search(b) or TESTS_RE.search(b)
        )
        enrichment_rate = enriched / decision_count if decision_count else 0

        if enrichment_rate < 0.5:
            out.warn(Evidence(
                type="count_below_threshold",
                message=(
                    f"{enriched}/{decision_count} decisions have Endpoints or Test "
                    f"Scenarios subsection ({enrichment_rate*100:.0f}%)"
                ),
                expected=">=50%",
                actual=f"{enrichment_rate*100:.0f}%",
                fix_hint="Consider /vg:scope <phase> re-run to add sub-sections.",
            ))

        # Check for stub/placeholder decisions
        stub_decisions = 0
        for b in blocks:
            lines = [line for line in b.splitlines()
                     if line.strip() and not line.startswith("#")]
            if len(lines) < 2:
                stub_decisions += 1
        if stub_decisions > 0:
            out.warn(Evidence(
                type="malformed_content",
                message=f"{stub_decisions} decisions have <2 lines of content (stubs)",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
