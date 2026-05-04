#!/usr/bin/env python3
"""verify-pre-test-tier-1-2.py — STEP 6.5 Tier 1 + Tier 2 gate.

Runs Tier 1 (static: typecheck + lint + debug-leftover grep + secret scan) +
Tier 2 (unit/integration tests). Writes a JSON report. Exits 1 on any BLOCK,
0 if all PASS or SKIPPED.

Codex Round 2 Correction A: missing-expected-tool promotion. When ENV-BASELINE.md
declares a tool but no runtime command is detected, SKIPPED → BLOCK with
`promoted_from: SKIPPED` field.

Skip flags (for partial runs):
  --skip-typecheck --skip-lint --skip-tests --skip-debug-grep --skip-secret-scan
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from pre_test_runner import (  # type: ignore
    grep_debug_leftovers, grep_secrets, run_typecheck, run_lint, run_tier_2_tests,
    declared_tools,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--env-baseline", default=".vg/ENV-BASELINE.md")
    parser.add_argument("--skip-typecheck", action="store_true")
    parser.add_argument("--skip-lint", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-debug-grep", action="store_true")
    parser.add_argument("--skip-secret-scan", action="store_true")
    args = parser.parse_args()

    src = Path(args.source_root)
    repo_root = Path(args.repo_root).resolve()
    if not src.exists():
        print(f"ERROR: source-root not found: {src}", file=sys.stderr)
        return 2

    skipped = lambda reason: {"status": "SKIPPED", "reason": reason, "duration_ms": 0}

    report = {
        "phase": args.phase,
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tier_1": {
            "typecheck":      skipped("--skip-typecheck") if args.skip_typecheck else run_typecheck(repo_root),
            "lint":           skipped("--skip-lint")      if args.skip_lint      else run_lint(repo_root),
            "debug_leftover": skipped("--skip-debug-grep") if args.skip_debug_grep else grep_debug_leftovers(src),
            "secret_scan":    skipped("--skip-secret-scan") if args.skip_secret_scan else grep_secrets(src),
        },
        "tier_2": skipped("--skip-tests") if args.skip_tests else run_tier_2_tests(repo_root),
        "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    declared = declared_tools(Path(args.env_baseline))

    def _promote_if_expected(expected_key: str, result: dict) -> dict:
        """Codex round 2: missing-expected-tooling = BLOCK, not SKIPPED."""
        if result.get("status") == "SKIPPED" and declared.get(expected_key):
            return {
                **result,
                "status": "BLOCK",
                "reason": f"ENV-BASELINE.md declares {expected_key} but no tool detected at runtime",
                "promoted_from": "SKIPPED",
            }
        return result

    report["tier_1"]["typecheck"] = _promote_if_expected("typecheck", report["tier_1"]["typecheck"])
    report["tier_1"]["lint"]      = _promote_if_expected("lint", report["tier_1"]["lint"])
    report["tier_2"]              = _promote_if_expected("unit_test", report["tier_2"])

    Path(args.report_out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    blocks: list[str] = []
    for k, v in report["tier_1"].items():
        if isinstance(v, dict) and v.get("status") == "BLOCK":
            blocks.append(f"tier_1.{k}")
    if isinstance(report["tier_2"], dict) and report["tier_2"].get("status") == "BLOCK":
        blocks.append("tier_2")

    if blocks:
        print(f"⛔ pre-test BLOCK: {', '.join(blocks)}", file=sys.stderr)
        print(f"   Report: {args.report_out}", file=sys.stderr)
        return 1

    print(f"✓ pre-test T1+T2: all PASS or SKIPPED ({args.report_out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
