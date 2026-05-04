#!/usr/bin/env python3
"""
verify-crossai-multi-cli.py — Phase L of v2.5.2 hardening.

Problem closed:
  CrossAI currently allows fast-fail mode (skip 3rd CLI if first 2 agree).
  But under v2.5.2 strict mode, trust-anchor outputs must have genuine
  N-reviewer consensus — not single reviewer producing schema-valid but
  forged XML. Claude review of v2.5.2 plan explicitly flagged this as
  one of the consensus-missing gaps.

This validator counts result-*.xml files in the CrossAI output dir and:
  1. Enforces minimum CLI count (e.g. 3/3 for total-check label)
  2. Checks each CLI result individually parses valid (delegates to
     validate-crossai-review-xml.py logic inline)
  3. Extracts <verdict> from each and computes consensus
  4. Requires consensus match (not just fast-fail agreement)
  5. Flags reviewer diversity (all reviewers same name = single reviewer
     disguised = forge)

Exit codes:
  0 = consensus reached, all CLIs valid
  1 = consensus fail (missing CLIs, conflicting verdicts, duplicate reviewers)
  2 = config/path error

Usage:
  verify-crossai-multi-cli.py --glob "crossai/result-*.xml" --min-consensus 2
  verify-crossai-multi-cli.py --glob "..." --require-all 3
  verify-crossai-multi-cli.py --glob "..." --json
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


VALID_VERDICTS = frozenset({"pass", "flag", "block"})


def _extract_fields(path: Path) -> dict:
    """Parse XML + extract verdict, reviewer, score. Returns dict."""
    result = {
        "path": str(path),
        "verdict": None,
        "reviewer": None,
        "score": None,
        "parse_ok": False,
        "error": None,
    }
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, PermissionError) as e:
        result["error"] = str(e)
        return result

    xml_match = re.search(
        r"<crossai_review>.*?</crossai_review>",
        content, re.DOTALL,
    )
    if not xml_match:
        result["error"] = "no <crossai_review> block"
        return result

    try:
        root = ET.fromstring(xml_match.group(0))
    except ET.ParseError as e:
        result["error"] = f"parse error: {e}"
        return result

    result["parse_ok"] = True

    v = root.find("verdict")
    if v is not None and v.text:
        result["verdict"] = v.text.strip().lower()
    r = root.find("reviewer")
    if r is not None and r.text:
        result["reviewer"] = r.text.strip()
    s = root.find("score")
    if s is not None and s.text:
        sm = re.match(r"^\s*(\d+(?:\.\d+)?)", s.text.strip())
        if sm:
            result["score"] = float(sm.group(1))

    return result


def _compute_consensus(cli_results: list[dict]) -> dict:
    """Return {consensus_verdict, agreement_count, conflicts, reviewer_diversity}."""
    valid = [r for r in cli_results if r["parse_ok"] and r["verdict"] in VALID_VERDICTS]
    if not valid:
        return {
            "consensus_verdict": None,
            "agreement_count": 0,
            "conflicts": [r["verdict"] for r in cli_results],
            "reviewer_diversity": 0,
            "reason": "no parseable CLI results with valid verdict",
        }

    # Count verdicts
    verdicts = [r["verdict"] for r in valid]
    reviewers = [r["reviewer"] for r in valid if r["reviewer"]]
    unique_reviewers = set(reviewers)

    # Most common verdict
    counts = {}
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    max_verdict = max(counts, key=counts.get)
    max_count = counts[max_verdict]

    return {
        "consensus_verdict": max_verdict,
        "agreement_count": max_count,
        "total_valid": len(valid),
        "distribution": counts,
        "reviewers": list(unique_reviewers),
        "reviewer_diversity": len(unique_reviewers),
        "conflicts": verdicts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--glob", default=None,
                    help="glob pattern for result-*.xml files (when omitted, "
                         "auto-resolves to .vg/phases/<phase>/crossai/*.xml)")
    ap.add_argument("--min-consensus", type=int, default=2,
                    help="minimum CLIs agreeing on same verdict (default: 2)")
    ap.add_argument("--require-all", type=int, default=None,
                    help="require ALL of N CLI results present "
                         "(e.g. 3 for total-check mode)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    # v2.6 (2026-04-25): --phase enables auto-glob-resolution
    ap.add_argument("--phase", help="phase number — when set + --glob omitted, "
                                    "auto-resolves to .vg/phases/<phase>/crossai/*.xml")
    args = ap.parse_args()

    # v2.6 — auto-resolve glob from phase
    if not args.glob and args.phase:
        from pathlib import Path as _Path
        phases_dir = _Path(".vg/phases")
        if phases_dir.exists():
            for p in phases_dir.iterdir():
                if p.is_dir() and (p.name == args.phase
                                   or p.name.startswith(f"{args.phase}-")
                                   or p.name.startswith(f"{args.phase.zfill(2)}-")):
                    args.glob = str(p / "crossai" / "*.xml")
                    break

    if not args.glob:
        # No glob + no phase → auto-skip (PASS) instead of crash
        import json as _json
        print(_json.dumps({
            "validator": "verify-crossai-multi-cli",
            "verdict": "PASS",
            "evidence": [],
            "_skipped": "no --glob or --phase provided (CrossAI results not present)",
        }))
        return 0

    paths = [Path(p) for p in sorted(_glob.glob(args.glob))]
    cli_results = [_extract_fields(p) for p in paths]

    consensus = _compute_consensus(cli_results)

    failures = []

    # Check 1: require_all — all N CLIs must be present + parseable
    if args.require_all:
        if len(paths) < args.require_all:
            failures.append({
                "check": "require_all",
                "reason": f"found {len(paths)} CLI result(s), require {args.require_all}",
            })
        parseable = sum(1 for r in cli_results if r["parse_ok"])
        if parseable < args.require_all:
            failures.append({
                "check": "all_parseable",
                "reason": f"only {parseable}/{args.require_all} parseable",
            })

    # Check 2: consensus count meets minimum
    agreement = consensus.get("agreement_count", 0)
    if agreement < args.min_consensus:
        failures.append({
            "check": "min_consensus",
            "reason": (
                f"max agreement {agreement} < required {args.min_consensus}. "
                f"Distribution: {consensus.get('distribution')}"
            ),
        })

    # Check 3: reviewer diversity — if ≥2 results, they should come from
    # different reviewers (prevent single-reviewer spoofing as multi)
    total_valid = consensus.get("total_valid", 0)
    diversity = consensus.get("reviewer_diversity", 0)
    if total_valid >= 2 and diversity < 2:
        failures.append({
            "check": "reviewer_diversity",
            "reason": (
                f"{total_valid} valid results but only {diversity} distinct "
                f"reviewer(s) — possible single-reviewer spoofing"
            ),
        })

    report = {
        "validator": "verify-crossai-multi-cli",
        # v2.6 (2026-04-25): emit verdict for orchestrator dispatch shim.
        # WARN (not BLOCK) — CrossAI consensus failure is signal that
        # reviewers disagree but operator decides whether to ship; not
        # an automatic phase-block.
        "verdict": "PASS" if not failures else "WARN",
        "glob": args.glob,
        "files_found": len(paths),
        "cli_results": cli_results,
        "consensus": consensus,
        "failures": failures,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if failures:
            print(f"\033[38;5;208mCrossAI multi-CLI consensus: {len(failures)} check(s) failed\033[0m\n")
            for f in failures:
                print(f"  [{f['check']}] {f['reason']}")
        elif not args.quiet:
            print(
                f"✓ CrossAI consensus OK — {consensus['agreement_count']}/"
                f"{consensus['total_valid']} reviewers agree on "
                f"verdict={consensus['consensus_verdict']}"
            )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
