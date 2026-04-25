#!/usr/bin/env python3
"""
verify-security-baseline-project.py — Phase M Batch 1 of v2.5.2 hardening.

Problem closed:
  Individual runtime security validators (cookie flags, headers, authz
  negative paths, dep vuln budget, container hardening) answer narrow
  questions. For gate integration we need ONE orchestrator that runs
  them all against a live target, aggregates results, applies per-check
  risk profile weighting, and emits a unified verdict.

Sub-validators invoked (all in same dir):
  - verify-cookie-flags-runtime.py
  - verify-security-headers-runtime.py
  - verify-authz-negative-paths.py       (optional — needs fixtures)
  - verify-dependency-vuln-budget.py
  - verify-container-hardening.py         (static but part of baseline)

Aggregation:
  - Each sub-validator invoked with --json; its block_count contributes
    to the total.
  - Risk profile per sub-validator:
      critical -> any block → orchestrator BLOCKS
      low      -> blocks logged but orchestrator still PASSES

Waivers:
  .vg/security-runtime-waivers.yml — list of {validator, reason, expiry}.
  Matching validator's blocks are demoted to warns.

Exit codes:
  0 = aggregate PASS (or waived to warn)
  1 = at least one critical-profile sub-validator BLOCKS
  2 = config error (target unreachable for all sub-validators)

Usage:
  verify-security-baseline-project.py --target-url http://localhost:3000
  verify-security-baseline-project.py --target-url X \\
                                       --fixtures .vg/authz-fixtures.json
  verify-security-baseline-project.py --target-url X --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


VALIDATORS_DIR = Path(__file__).resolve().parent

SUB_VALIDATORS = [
    {
        "name": "cookie_flags",
        "script": "verify-cookie-flags-runtime.py",
        "risk_profile": "critical",
        "needs_target": True,
    },
    {
        "name": "security_headers",
        "script": "verify-security-headers-runtime.py",
        "risk_profile": "critical",
        "needs_target": True,
    },
    {
        "name": "authz_negative",
        "script": "verify-authz-negative-paths.py",
        "risk_profile": "critical",
        "needs_target": True,
        "needs_fixtures": True,
    },
    {
        "name": "dep_vuln_budget",
        "script": "verify-dependency-vuln-budget.py",
        "risk_profile": "critical",
        "needs_target": False,
    },
    {
        "name": "container_hardening",
        "script": "verify-container-hardening.py",
        "risk_profile": "low",
        "needs_target": False,
    },
]


def _load_waivers(path: Path) -> dict:
    """Return dict {validator_name: reason} (minimal YAML parsing)."""
    if not path.exists():
        return {}
    out: dict = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    # Scan `- validator: NAME` + paired `reason: TEXT`
    current: dict = {}
    for line in text.splitlines():
        m = re.match(r"^\s*-\s+validator\s*:\s*(\S+)", line)
        if m:
            if current.get("validator"):
                out[current["validator"]] = current.get("reason", "")
            current = {"validator": m.group(1)}
            continue
        m = re.match(r"^\s*reason\s*:\s*(.+)$", line)
        if m and current:
            current["reason"] = m.group(1).strip()
    if current.get("validator"):
        out[current["validator"]] = current.get("reason", "")
    return out


def _invoke(script_path: Path, args_list: list[str],
            timeout: float) -> dict:
    """Run sub-validator with --json. Return parsed report + exit code."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), *args_list, "--json"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", env=env,
        )
    except subprocess.TimeoutExpired:
        return {"exit_code": 2, "report": {"error": "timeout"},
                "stderr": "timeout"}
    try:
        report = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        report = {"error": "unparseable-json", "raw": proc.stdout[:500]}
    return {
        "exit_code": proc.returncode,
        "report": report,
        "stderr": proc.stderr.strip(),
    }


def _build_args(sv: dict, args: argparse.Namespace) -> list[str] | None:
    """Build CLI args for sub-validator. Returns None if prerequisite missing."""
    name = sv["name"]
    if sv["needs_target"] and not args.target_url:
        return None
    if name == "cookie_flags":
        return ["--target-url", args.target_url, "--probe-only",
                "--timeout", str(args.timeout)]
    if name == "security_headers":
        out = ["--target-url", args.target_url, "--paths", args.paths,
               "--timeout", str(args.timeout)]
        if args.require_recommended:
            out.append("--require-recommended")
        return out
    if name == "authz_negative":
        if not args.fixtures or not Path(args.fixtures).exists():
            return None
        return ["--target-url", args.target_url, "--fixtures", args.fixtures,
                "--timeout", str(args.timeout)]
    if name == "dep_vuln_budget":
        out = ["--project-root", args.project_root]
        if args.budget_high is not None:
            out += ["--budget-high", str(args.budget_high)]
        if args.budget_medium is not None:
            out += ["--budget-medium", str(args.budget_medium)]
        return out
    if name == "container_hardening":
        return ["--project-root", args.project_root]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target-url", default=None,
                    help="base URL of live app")
    ap.add_argument("--paths", default="/",
                    help="paths for header probe")
    ap.add_argument("--fixtures", default=None,
                    help="authz fixtures JSON (enables authz_negative)")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--budget-high", type=int, default=None)
    ap.add_argument("--budget-medium", type=int, default=None)
    ap.add_argument("--require-recommended", action="store_true")
    ap.add_argument("--waiver-file", default=".vg/security-runtime-waivers.yml")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--only", default=None,
                    help="comma-separated sub-validators (default: all)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")
    args = ap.parse_args()

    waivers = _load_waivers(Path(args.project_root) / args.waiver_file)
    only = set(args.only.split(",")) if args.only else None

    if not args.target_url and only is None:
        # At least one non-target sub-validator still runs; but warn.
        print("⚠  No --target-url provided. Target-dependent sub-validators "
              "will be skipped.", file=sys.stderr)

    subreports: list[dict] = []
    aggregate_blocks = 0
    aggregate_warns = 0
    critical_block = False
    at_least_one_ran = False

    for sv in SUB_VALIDATORS:
        if only is not None and sv["name"] not in only:
            continue
        script_path = VALIDATORS_DIR / sv["script"]
        if not script_path.exists():
            subreports.append({
                "name": sv["name"], "status": "missing",
                "error": f"{sv['script']} not installed",
            })
            continue
        built = _build_args(sv, args)
        if built is None:
            subreports.append({
                "name": sv["name"], "status": "skipped",
                "reason": "prerequisite missing (target URL or fixtures)",
            })
            continue

        result = _invoke(script_path, built, args.timeout)
        at_least_one_ran = True
        block_count = 0
        warn_count = 0
        rpt = result["report"] or {}
        if isinstance(rpt, dict):
            block_count = rpt.get("block_count", 0)
            warn_count = rpt.get("warn_count", 0)
        # Apply waiver
        waived = sv["name"] in waivers
        if waived:
            warn_count += block_count
            block_count = 0

        aggregate_blocks += block_count
        aggregate_warns += warn_count

        if block_count > 0 and sv["risk_profile"] == "critical" and not waived:
            critical_block = True

        subreports.append({
            "name": sv["name"],
            "risk_profile": sv["risk_profile"],
            "exit_code": result["exit_code"],
            "block_count": block_count,
            "warn_count": warn_count,
            "waived": waived,
            "waiver_reason": waivers.get(sv["name"]) if waived else None,
            "stderr": result["stderr"],
            "report": rpt,
            "status": "ran",
        })

    if not at_least_one_ran:
        print("⛔ No sub-validators ran. Check --target-url / "
              "project-root / --only.", file=sys.stderr)
        return 2

    aggregate = {
        "target": args.target_url,
        "sub_validators": subreports,
        "aggregate_block_count": aggregate_blocks,
        "aggregate_warn_count": aggregate_warns,
        "critical_block": critical_block,
        "waivers_applied": list(waivers.keys()),
    }

    if args.json:
        print(json.dumps(aggregate, indent=2))
    else:
        if critical_block:
            print(f"⛔ Security baseline: critical BLOCK — "
                  f"{aggregate_blocks} block(s), {aggregate_warns} warn(s)\n")
        elif aggregate_warns and not args.quiet:
            print(f"⚠  Security baseline: {aggregate_warns} WARN (no "
                  f"critical blocks)")
        elif not args.quiet:
            print(
                f"✓ Security baseline OK — "
                f"{len([s for s in subreports if s.get('status') == 'ran'])}"
                f"/{len(SUB_VALIDATORS)} sub-validator(s) ran"
            )
        for sr in subreports:
            status = sr.get("status", "?")
            if status == "ran":
                marker = "X" if sr["block_count"] else ("!" if sr["warn_count"] else "+")
                waived_txt = " [WAIVED]" if sr.get("waived") else ""
                print(f"  [{marker}] {sr['name']}{waived_txt}: "
                      f"{sr['block_count']} block, {sr['warn_count']} warn "
                      f"({sr['risk_profile']})")
            else:
                print(f"  [-] {sr['name']}: {status} "
                      f"{sr.get('reason') or sr.get('error') or ''}")

    return 1 if critical_block else 0


if __name__ == "__main__":
    sys.exit(main())
