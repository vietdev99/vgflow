#!/usr/bin/env python3
"""crossai-marker-write.py — v2.66.1 #154 verdict-gated marker writer.

Writes the CrossAI step marker file conditional on the aggregator verdict
+ ok_count.

- verdict in {pass, flag, partial, ok} AND ok_count > 0
    -> writes `${marker_dir}/${step}_crossai_review.done`
- otherwise (verdict=inconclusive, fail, block, or ok_count == 0)
    -> writes `${marker_dir}/${step}_crossai_review.inconclusive`

`/vg:next` and the orchestrator's step contract treat `.inconclusive` as
"not done — re-run on next invocation". Without this gate, `inconclusive`
runs (CLI auth missing, TLS bug, all 3 timed out) silently produced
`.done` and the next /vg:next skipped re-running CrossAI.

Usage:
  python crossai-marker-write.py \\
    --marker-dir <phase_dir>/.step-markers \\
    --step crossai_review \\
    --verdict <verdict> \\
    --ok-count <N>

  # If the aggregator JSON exists, derive verdict + ok_count from it:
  python crossai-marker-write.py \\
    --marker-dir <phase_dir>/.step-markers \\
    --step crossai_review \\
    --report-json <phase_dir>/crossai/review-check.report.json

Exit codes:
  0 — marker written (either .done or .inconclusive)
  1 — IO / arg error
  2 — wrote .inconclusive (signals caller marker is not "done")
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# v2.66.1 #154: passing verdicts that allow .done marker write.
# "ok" and "partial" are the canonical names from the original plan; "pass"
# and "flag" are the actual aggregator output names from
# crossai-normalize-results.py (VALID_VERDICTS = {"pass","flag","block","inconclusive"}).
PASSING_VERDICTS = {"pass", "flag", "ok", "partial"}


def write_marker(marker_dir: Path, step: str, verdict: str, ok_count: int) -> tuple[Path, bool]:
    """Decide which marker to write.

    Returns (path, is_done) where is_done == True for `.done` marker,
    False for `.inconclusive` marker.
    """
    marker_dir.mkdir(parents=True, exist_ok=True)
    v = (verdict or "").strip().lower()
    is_done = v in PASSING_VERDICTS and ok_count > 0
    suffix = "done" if is_done else "inconclusive"
    path = marker_dir / f"{step}.{suffix}"
    path.write_text("", encoding="utf-8")
    return path, is_done


def load_report(report_json: Path) -> tuple[str, int]:
    data = json.loads(report_json.read_text(encoding="utf-8"))
    return str(data.get("verdict", "inconclusive")), int(data.get("ok_count", 0))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--marker-dir", required=True)
    ap.add_argument("--step", default="crossai_review",
                    help="step name (default: crossai_review). Marker written as <step>.{done,inconclusive}")
    ap.add_argument("--verdict")
    ap.add_argument("--ok-count", type=int)
    ap.add_argument("--report-json",
                    help="Aggregator report JSON (e.g. <phase>/crossai/review-check.report.json) — derive verdict + ok_count from it")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.report_json:
        rj = Path(args.report_json)
        if not rj.is_file():
            print(f"report-json not found: {rj}", file=sys.stderr)
            return 1
        verdict, ok_count = load_report(rj)
    else:
        if args.verdict is None or args.ok_count is None:
            print("Either --report-json OR (--verdict + --ok-count) required", file=sys.stderr)
            return 1
        verdict = args.verdict
        ok_count = args.ok_count

    marker_dir = Path(args.marker_dir)
    path, is_done = write_marker(marker_dir, args.step, verdict, ok_count)

    if not args.quiet:
        if is_done:
            print(f"crossai marker DONE: verdict={verdict} ok_count={ok_count} -> {path}")
        else:
            print(f"crossai marker INCONCLUSIVE: verdict={verdict} ok_count={ok_count} -> {path}")
            print("  /vg:next will RE-RUN CrossAI on next invocation (.done marker NOT written).")

    return 0 if is_done else 2


if __name__ == "__main__":
    sys.exit(main())
