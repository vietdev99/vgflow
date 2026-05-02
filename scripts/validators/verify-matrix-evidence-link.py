#!/usr/bin/env python3
"""
verify-matrix-evidence-link.py — fail-closed-validators PR (Phase 3.2 dogfood)

Cross-checks GOAL-COVERAGE-MATRIX.md verdicts against the runtime evidence
they claim to summarize (RUNTIME-MAP.json goal_sequences[]).

Catches the false-positive class where /vg:review writes Status=READY
into the matrix even though:
  (a) goal_sequences[G-XX] is missing entirely (review never replayed it), or
  (b) goal_sequences[G-XX].result == "blocked" (replay observed a failure)

Phase 3.2 evidence: matrix said 65/67 READY but RUNTIME-MAP showed
40 goals with no sequence + 11 goals with result=blocked. Coverage stats
in RUNTIME-MAP.coverage block also lied (goals_passed_or_runtime_ready=65
vs reality=10). All silent. This validator stops the lie at review-exit.

Allowed Status values that DON'T require a runtime sequence:
  - INFRA_PENDING — goal needs infra not available, deferred to UAT
  - UNREACHABLE   — code not in repo
  - DEFERRED      — phase target not yet deployed

Any other Status (READY, MANUAL_VERIFIED, etc.) requires a non-empty
goal_sequences entry whose result is "passed" / "ready" / "ok".

Usage:
  verify-matrix-evidence-link.py --phase-dir <path>
  verify-matrix-evidence-link.py --phase <number>

Exit codes:
  0 — matrix and runtime evidence agree
  1 — mismatch found OR matrix unparseable (fail-closed)
  2 — config error (matrix or runtime-map missing)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Matrix table row: `| G-10 | critical | ui | READY | evidence text |`
MATRIX_ROW_RE = re.compile(
    r"^\|\s*(G-[A-Z0-9-]+)\s*\|"          # goal id
    r"\s*([^|]*?)\s*\|"                    # priority
    r"\s*([^|]*?)\s*\|"                    # surface
    r"\s*([A-Z_]+(?:[-/][A-Za-z_]+)?)\s*\|" # status
    r"\s*([^|]*?)\s*\|",                   # evidence
    re.MULTILINE,
)

# v2.47.1 (Issue #84) — BLOCKED added: when matrix Status=BLOCKED matches
# runtime goal_sequences[gid].result='blocked'/'failed'/'error', the two
# are semantically aligned and should NOT trigger
# matrix_status_contradicts_runtime_result. Pre-fix: workflow forced
# DEFERRED workaround instead of the natural BLOCKED.
STATUSES_WITHOUT_RUNTIME = {"INFRA_PENDING", "UNREACHABLE", "DEFERRED", "BLOCKED"}
RUNTIME_FAILURE_RESULTS = {"blocked", "failed", "error"}
RUNTIME_PASS_RESULTS = {"passed", "ready", "ok", "deferred-structural"}


def parse_matrix(matrix_path: Path) -> list[dict]:
    """Return list of {goal_id, priority, surface, status, evidence}."""
    if not matrix_path.is_file():
        return []
    text = matrix_path.read_text(encoding="utf-8", errors="replace")
    rows: list[dict] = []
    for m in MATRIX_ROW_RE.finditer(text):
        gid = m.group(1).strip().upper()
        if not gid.startswith("G-"):
            continue
        rows.append({
            "goal_id": gid,
            "priority": m.group(2).strip(),
            "surface": m.group(3).strip().lower(),
            "status": m.group(4).strip().upper(),
            "evidence": m.group(5).strip(),
        })
    return rows


def load_runtime_map(rmap_path: Path) -> dict:
    if not rmap_path.is_file():
        return {}
    try:
        return json.loads(rmap_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase-dir")
    g.add_argument("--phase")
    ap.add_argument("--severity", choices=["warn", "block"], default="block")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    output = Output(validator="matrix-evidence-link")

    with timer(output):
        if args.phase_dir:
            phase_dir = Path(args.phase_dir).resolve()
        else:
            phase_dir = find_phase_dir(args.phase)
            if not phase_dir:
                print(f"⛔ Phase dir not found for phase={args.phase}", file=sys.stderr)
                return 2

        if not phase_dir.is_dir():
            print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
            return 2

        matrix_path = phase_dir / "GOAL-COVERAGE-MATRIX.md"
        rmap_path = phase_dir / "RUNTIME-MAP.json"

        if not matrix_path.is_file():
            print(f"⛔ GOAL-COVERAGE-MATRIX.md missing in {phase_dir}", file=sys.stderr)
            return 2
        if not rmap_path.is_file():
            print(f"⛔ RUNTIME-MAP.json missing in {phase_dir}", file=sys.stderr)
            return 2

        rows = parse_matrix(matrix_path)
        if not rows:
            # FAIL CLOSED — matrix exists but no rows could be parsed.
            output.add(Evidence(
                type="matrix_unparseable",
                message=(
                    "GOAL-COVERAGE-MATRIX.md exists but no goal rows could be "
                    "parsed (expected `| G-XX | priority | surface | STATUS | evidence |` "
                    "table rows)."
                ),
                file=str(matrix_path),
                fix_hint=(
                    "Re-run /vg:review so the matrix is regenerated with valid "
                    "table rows, or check matrix manually for table format drift."
                ),
            ))
            print(output.to_json() if args.json else output.evidence[-1].message)
            return 1 if args.severity == "block" else 0

        rmap = load_runtime_map(rmap_path)
        sequences = rmap.get("goal_sequences") or {}

        for row in rows:
            gid = row["goal_id"]
            status = row["status"]

            if status in STATUSES_WITHOUT_RUNTIME:
                continue

            seq = sequences.get(gid)
            if not isinstance(seq, dict):
                output.add(Evidence(
                    type="matrix_status_without_runtime_sequence",
                    message=(
                        f"{gid}: matrix Status={status} but no goal_sequences[{gid}] "
                        f"entry in RUNTIME-MAP.json"
                    ),
                    file=str(matrix_path),
                    expected=f"goal_sequences[{gid}].steps non-empty with result in {sorted(RUNTIME_PASS_RESULTS)}",
                    actual="missing entry",
                    fix_hint=(
                        f"Re-run /vg:review {phase_dir.name} so the goal is replayed, "
                        f"OR change matrix Status to UNREACHABLE/INFRA_PENDING/DEFERRED "
                        f"with a justification."
                    ),
                ))
                continue

            steps = seq.get("steps") or []
            result = (seq.get("result") or seq.get("status") or "").lower()

            if not steps:
                output.add(Evidence(
                    type="matrix_status_with_empty_sequence",
                    message=(
                        f"{gid}: matrix Status={status} but goal_sequences[{gid}].steps "
                        f"is empty (review recorded a sequence shell but never replayed it)"
                    ),
                    file=str(matrix_path),
                    expected="steps[].length > 0",
                    actual=f"steps={len(steps)}, result={result or 'unset'}",
                    fix_hint=f"Re-run /vg:review {phase_dir.name} --retry-failed",
                ))
                continue

            if result and result not in RUNTIME_PASS_RESULTS:
                # v2.47.1 (Issue #84) — alignment short-circuit: if matrix
                # explicitly wrote a failure status (BLOCKED) and runtime
                # also recorded failure, both are saying the same thing.
                # Don't flag as contradiction.
                if status == "BLOCKED" and result in RUNTIME_FAILURE_RESULTS:
                    continue
                # Most common: matrix=READY, result=blocked
                output.add(Evidence(
                    type="matrix_status_contradicts_runtime_result",
                    message=(
                        f"{gid}: matrix Status={status} but RUNTIME-MAP "
                        f"goal_sequences[{gid}].result={result!r} (review observed "
                        f"a failure but matrix wrote a success status)"
                    ),
                    file=str(matrix_path),
                    expected=f"matrix Status reflects runtime result {result!r}",
                    actual=f"Status={status} contradicts result={result!r}",
                    fix_hint=(
                        f"Either fix the underlying issue and re-run /vg:review {phase_dir.name} "
                        f"--retry-failed (so result becomes 'passed'), OR change matrix Status "
                        f"to BLOCKED/UNREACHABLE per the actual failure."
                    ),
                ))

        if not output.evidence:
            output.evidence.append(Evidence(
                type="matrix_evidence_link_ok",
                message=(
                    f"Matrix evidence link OK — {len(rows)} matrix rows verified "
                    f"against {len(sequences)} goal_sequences entries."
                ),
            ))

    if args.json:
        print(output.to_json())
    else:
        if output.verdict == "BLOCK":
            print(f"⛔ Matrix evidence link: {len(output.evidence)} mismatch(es)")
            for e in output.evidence:
                print(f"   [{e.type}] {e.message}")
                if e.fix_hint:
                    print(f"     hint: {e.fix_hint}")
        else:
            print(f"✓ {output.evidence[0].message}")

    if output.verdict == "BLOCK" and args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
