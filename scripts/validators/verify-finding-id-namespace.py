#!/usr/bin/env python3
"""verify-finding-id-namespace — Task 35 validator (warn-tier rollout)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts/lib"))

from scanner_report_contract import (  # type: ignore
    FEEDBACK_HEADER_REGEX, is_conforming, suggest_replacement,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feedback", required=True, help="path to REVIEW-FEEDBACK.md")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--evidence-out")
    parser.add_argument("--severity", choices=("warn", "block"), default="warn",
                        help="warn (default, gradual rollout) or block (post-soak promotion)")
    args = parser.parse_args()

    feedback_path = Path(args.feedback)
    if not feedback_path.exists():
        print(f"ℹ no REVIEW-FEEDBACK.md at {feedback_path} — skip namespace check")
        return 0

    text = feedback_path.read_text(encoding="utf-8")
    findings: list[dict] = []
    suggestions: list[dict] = []

    for m in FEEDBACK_HEADER_REGEX.finditer(text):
        fid = m.group(1)
        conforming = is_conforming(fid)
        findings.append({"finding_id": fid, "conforming": conforming, "line_match": m.group(0)})
        if not conforming:
            suggestions.append({"original": fid, "suggested": suggest_replacement(fid)})

    summary = {
        "phase": args.phase,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(findings),
        "conforming_count": sum(1 for f in findings if f["conforming"]),
        "non_conforming_count": sum(1 for f in findings if not f["conforming"]),
        "suggestions": suggestions,
    }

    if args.evidence_out:
        Path(args.evidence_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if summary["non_conforming_count"] > 0:
        print(f"⚠ {summary['non_conforming_count']} non-conforming finding-ID(s) in REVIEW-FEEDBACK.md", file=sys.stderr)
        for s in suggestions[:5]:
            sug = s["suggested"] or "(no mapping — manual review)"
            print(f"   {s['original']} → {sug}", file=sys.stderr)

        # Emit warn-tier telemetry
        import subprocess
        subprocess.run([
            "python3", ".claude/scripts/vg-orchestrator", "emit-event",
            "review.finding_id_invalid",
            "--actor", "validator", "--outcome", "WARN",
            "--payload", json.dumps({
                "phase": args.phase,
                "non_conforming_count": summary["non_conforming_count"],
                "first_offenders": [s["original"] for s in suggestions[:3]],
            }),
        ], capture_output=True, timeout=10)

        if args.severity == "block":
            return 1  # Future: BLOCK after 14-day soak

    print(f"✓ finding-ID namespace: {summary['conforming_count']}/{summary['total']} conforming")
    return 0


if __name__ == "__main__":
    sys.exit(main())
