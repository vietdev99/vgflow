#!/usr/bin/env python3
"""verify-lens-action-trace.py — M2 MCP action-trace cross-check (Task 26).

The MCP server (Playwright MCP, Codex MCP) emits a tool-call log for every
browser action. Log lives at `${PHASE_DIR}/.mcp-trace/<run_id>.jsonl`,
written externally by the MCP server (NOT by the worker).

Worker self-reports `actions_taken: N` in run artifact. Gate compares:
  - mcp_action_count(run_id) == artifact.actions_taken → PASS
  - mismatch > tolerance (default ±2 for tool-internal retries) → BLOCK
    (hard anti-fake — no advisory phase-in on present-trace mismatches)
  - trace file MISSING + mcp_trace_required=false (default) → ADVISORY
    (Codex round 7: MCP producer not yet plumbed; flip default once ready)
  - trace file MISSING + mcp_trace_required=true → BLOCK

Tolerance accounts for MCP-internal retries on transient errors. Drift
> tolerance cannot be explained by retries alone — implies fabrication.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _count_mcp_actions(trace_path: Path, run_id: str) -> int:
    if not trace_path.exists():
        return -1
    count = 0
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("run_id") == run_id and str(entry.get("tool", "")).startswith("browser_"):
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--mcp-trace", required=True)
    parser.add_argument("--tolerance", type=int, default=2)
    parser.add_argument("--mcp-trace-required", action="store_true",
                        help="When set, missing trace = BLOCK. Default: ADVISORY (producer plumbing pending).")
    parser.add_argument("--evidence-out")
    args = parser.parse_args()

    artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    self_reported = artifact.get("actions_taken", 0)
    run_id = artifact.get("run_id")
    mcp_count = _count_mcp_actions(Path(args.mcp_trace), run_id)

    if mcp_count == -1:
        severity = "BLOCK" if args.mcp_trace_required else "ADVISORY"
        msg = f"{'⛔' if severity == 'BLOCK' else '⚠'} MCP trace missing for run_id {run_id} ({severity})"
        print(msg, file=sys.stderr)
        if args.evidence_out:
            ev = {
                "warning_id": f"lens-trace-missing-{run_id}",
                "severity": severity,
                "category": "lens_action_trace_missing",
                "summary": f"MCP trace file absent for run_id {run_id}.",
                "detected_by": "verify-lens-action-trace.py",
                "details": {"run_id": run_id, "mcp_trace_required": args.mcp_trace_required},
            }
            Path(args.evidence_out).write_text(json.dumps(ev, indent=2), encoding="utf-8")
        return 1 if severity == "BLOCK" else 0

    drift = abs(self_reported - mcp_count)
    if drift > args.tolerance:
        print(f"⛔ M2 trace mismatch: self_reported={self_reported}, "
              f"mcp_count={mcp_count}, drift={drift} > tolerance={args.tolerance}",
              file=sys.stderr)
        if args.evidence_out:
            ev = {
                "warning_id": f"lens-trace-mismatch-{run_id}",
                "severity": "BLOCK",
                "category": "lens_action_trace_mismatch",
                "summary": (f"Worker reported {self_reported} actions but MCP log shows "
                            f"{mcp_count}. Drift {drift} > tolerance {args.tolerance}. "
                            "AI fabrication suspected."),
                "detected_by": "verify-lens-action-trace.py",
                "details": {"run_id": run_id, "self_reported": self_reported,
                            "mcp_count": mcp_count, "drift": drift,
                            "tolerance": args.tolerance},
            }
            Path(args.evidence_out).write_text(json.dumps(ev, indent=2), encoding="utf-8")
        return 1

    print(f"✓ M2 trace match: {self_reported} ≈ {mcp_count} (drift {drift} ≤ {args.tolerance})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
