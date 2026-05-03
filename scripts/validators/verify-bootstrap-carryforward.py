#!/usr/bin/env python3
"""
verify-bootstrap-carryforward.py — Phase P of v2.5.2 hardening.

Problem closed (v2.5.1 Codex finding):
  v2.5.1's bootstrap validators grep-checked for event log having
  `bootstrap.loaded` entry. AI executor could emit the event (via
  telemetry API) without actually reading the rule into its prompt.
  Paperwork check, not behavioral.

This validator is BEHAVIORAL:
  1. Reads .vg/runs/<run_id>/executor-prompts/*.prompt.txt (captured by
     prompt_capture.py at spawn time — AI cannot forge; capture is
     in orchestrator path before handing off to subagent)
  2. Parses .vg/bootstrap/LEARN-RULES.md for active (state: approved) rules
  3. For each active rule, asserts its text body appears in >=N% of
     captured prompts for current run (default 100% for critical,
     80% for recommended)
  4. Drift detected (rule active but not in prompts) → BLOCK

Exit codes:
  0 = all active rules present in captured prompts
  1 = one or more rules not propagated to prompts
  2 = config error (no prompts, no rules, missing run_id)

Usage:
  verify-bootstrap-carryforward.py --run-id <uuid>
  verify-bootstrap-carryforward.py --run-id X --rules-file .vg/bootstrap/LEARN-RULES.md
  verify-bootstrap-carryforward.py --run-id X --min-coverage 0.8 --severity important
  verify-bootstrap-carryforward.py --run-id X --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def _parse_learn_rules(rules_file: Path) -> list[dict]:
    """
    Parse LEARN-RULES.md, return list of rules.

    Expected format per rule (markdown heading + metadata):
        ## L-042 — rule title
        **State:** approved
        **Severity:** critical | important | nice
        **Rule:** the actual text to inject into executor prompts
        **Evidence:** (references)

    Returns list of {id, title, state, severity, rule_text}.
    """
    if not rules_file.exists():
        return []

    text = rules_file.read_text(encoding="utf-8", errors="replace")
    rules: list[dict] = []

    # Split by `## L-<N>` heading
    blocks = re.split(r"\n(?=##\s+L-\d+)", text)
    for block in blocks:
        m = re.match(r"##\s+(L-\d+)\s*[—\-–]\s*(.+?)(?:\n|$)", block)
        if not m:
            continue
        rule_id = m.group(1)
        title = m.group(2).strip()

        state_m = re.search(r"\*\*State:\*\*\s*(\w+)", block, re.IGNORECASE)
        severity_m = re.search(r"\*\*Severity:\*\*\s*(\w+)", block, re.IGNORECASE)
        rule_m = re.search(
            r"\*\*Rule:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)",
            block, re.DOTALL | re.IGNORECASE,
        )

        rules.append({
            "id": rule_id,
            "title": title,
            "state": (state_m.group(1) if state_m else "unknown").lower(),
            "severity": (severity_m.group(1) if severity_m else "nice").lower(),
            "rule_text": (rule_m.group(1) if rule_m else "").strip(),
        })

    return rules


def _load_prompts(run_id: str) -> list[dict]:
    """Return list of {task_seq, text, path} for captured prompts."""
    prompt_dir = REPO_ROOT / ".vg" / "runs" / run_id / "executor-prompts"
    if not prompt_dir.exists():
        return []

    manifest_path = prompt_dir / "manifest.json"
    if not manifest_path.exists():
        return []

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    prompts = []
    for entry in manifest.get("entries", []):
        file_path = prompt_dir / entry.get("file", "")
        if not file_path.exists():
            continue
        try:
            prompts.append({
                "task_seq": entry.get("task_seq"),
                "text": file_path.read_text(encoding="utf-8"),
                "path": str(file_path),
                "sha256": entry.get("sha256"),
            })
        except OSError:
            continue

    return prompts


def _rule_present_in_prompt(rule_text: str, prompt_text: str) -> bool:
    """
    Test whether rule body appears in prompt.

    Uses first-60-chars anchor match (AI prompts may reformat trailing text
    but first-60 chars of a rule are usually preserved verbatim).

    Ignores case + whitespace collapse for robustness to prompt-style drift.
    """
    if not rule_text:
        return False

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().lower()

    anchor = _norm(rule_text)[:60]
    if len(anchor) < 20:
        anchor = _norm(rule_text)  # very short rules — require full text

    return anchor in _norm(prompt_text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--rules-file",
                    default=".vg/bootstrap/LEARN-RULES.md")
    ap.add_argument("--min-coverage", type=float, default=1.0,
                    help="Min fraction of prompts that must contain each "
                         "active rule (default 1.0 = 100%)")
    ap.add_argument("--severity", default="critical",
                    choices=["critical", "important", "nice", "all"],
                    help="Which severity rules to enforce (default critical)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")
    args = ap.parse_args()

    rules_path = REPO_ROOT / args.rules_file
    rules = _parse_learn_rules(rules_path)
    active_rules = [r for r in rules if r["state"] == "approved"]
    if args.severity != "all":
        active_rules = [r for r in active_rules if r["severity"] == args.severity]

    prompts = _load_prompts(args.run_id)

    if not prompts:
        msg = f"No captured prompts for run {args.run_id}"
        if args.json:
            print(json.dumps({
                "run_id": args.run_id,
                "error": msg,
                "prompts_count": 0,
                "active_rules_count": len(active_rules),
            }))
        else:
            print(f"\033[33m{msg}\033[0m")
        return 2

    if not active_rules:
        msg = (f"No active rules at severity={args.severity} in {rules_path} "
               "— nothing to enforce (benign)")
        if args.json:
            print(json.dumps({
                "run_id": args.run_id,
                "prompts_count": len(prompts),
                "active_rules_count": 0,
                "coverage": [],
            }))
        elif not args.quiet:
            print(f"✓ {msg}")
        return 0

    coverage_report = []
    failures = []

    for rule in active_rules:
        present_count = sum(
            1 for p in prompts
            if _rule_present_in_prompt(rule["rule_text"], p["text"])
        )
        coverage = present_count / len(prompts) if prompts else 0.0
        record = {
            "rule_id": rule["id"],
            "title": rule["title"],
            "severity": rule["severity"],
            "present_in": present_count,
            "total_prompts": len(prompts),
            "coverage": round(coverage, 3),
            "meets_min": coverage >= args.min_coverage,
        }
        coverage_report.append(record)

        if coverage < args.min_coverage:
            failures.append(record)

    result = {
        "run_id": args.run_id,
        "prompts_count": len(prompts),
        "active_rules_count": len(active_rules),
        "min_coverage_required": args.min_coverage,
        "severity_filter": args.severity,
        "coverage": coverage_report,
        "failures": failures,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if failures:
            print(f"\033[38;5;208mBootstrap carryforward: {len(failures)}/\033[0m"
                  f"{len(active_rules)} active rule(s) missing from prompts\n")
            for f in failures:
                print(f"  [{f['rule_id']}] {f['title']}")
                print(f"    severity={f['severity']} coverage={f['coverage']} "
                      f"(present in {f['present_in']}/{f['total_prompts']} prompts)")
        elif not args.quiet:
            print(f"✓ Bootstrap carryforward OK — {len(active_rules)} active rule(s), "
                  f"all >= {args.min_coverage*100:.0f}% prompt coverage")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
