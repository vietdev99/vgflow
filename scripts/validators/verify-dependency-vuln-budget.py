#!/usr/bin/env python3
"""
verify-dependency-vuln-budget.py — Phase M Batch 1 of v2.5.2 hardening.

Problem closed:
  deps-security-scan.py blocks on a single-severity threshold (e.g. any
  HIGH fails). Real-world release gates need graduated budgets — e.g.
  "0 high, up to 5 medium acceptable this sprint, any low is fine".
  This validator implements the budget-based model so critical phases
  can tune policy without a binary all-or-nothing threshold.

Detects ecosystem via lockfile presence:
  - package-lock.json / pnpm-lock.yaml / yarn.lock → npm/pnpm/yarn audit
  - requirements.txt / pyproject.toml              → pip-audit
  - Cargo.lock                                     → cargo audit
  (first detected ecosystem wins; pass --ecosystem to override)

Counts findings by severity, compares to budget:
  high:   BLOCK if count > budget-high (default 0)
  medium: WARN if count > budget-medium (BLOCK if --strict-medium)
  low:    unlimited by default

Respects .vg/cve-waivers.yml — same format as deps-security-scan.py.
Waived CVEs are excluded from counts.

Exit codes:
  0 = within budget (waivers applied)
  1 = budget exceeded (BLOCK severities)
  2 = audit tool missing / not found

Usage:
  verify-dependency-vuln-budget.py --project-root .
  verify-dependency-vuln-budget.py --budget-high 0 --budget-medium 5
  verify-dependency-vuln-budget.py --strict-medium --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _detect_ecosystem(root: Path) -> str | None:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "package-lock.json").exists():
        return "npm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "Cargo.lock").exists():
        return "cargo"
    if (root / "requirements.txt").exists() or \
       (root / "pyproject.toml").exists():
        return "pip"
    return None


def _resolve_cmd(name: str) -> str | None:
    """Resolve executable on PATH respecting PATHEXT on Windows."""
    return shutil.which(name)


def _run_audit(ecosystem: str, root: Path, timeout: float) -> dict:
    """Return {ok, findings: [{id, severity, package}], raw, error}."""
    cmd_map = {
        "pnpm": ["pnpm", "audit", "--json"],
        "npm": ["npm", "audit", "--json"],
        "yarn": ["yarn", "audit", "--json"],
        "pip": ["pip-audit", "-f", "json"],
        "cargo": ["cargo", "audit", "--json"],
    }
    cmd = cmd_map.get(ecosystem)
    if cmd is None:
        return {"ok": False, "error": f"unknown ecosystem {ecosystem}",
                "findings": [], "raw": ""}

    resolved = _resolve_cmd(cmd[0])
    if resolved is None:
        return {"ok": False,
                "error": f"{ecosystem} audit tool not installed",
                "findings": [], "raw": ""}

    try:
        proc = subprocess.run(
            [resolved, *cmd[1:]],
            cwd=str(root), capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return {"ok": False, "error": f"{ecosystem} audit tool not installed",
                "findings": [], "raw": ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "audit timeout",
                "findings": [], "raw": ""}

    raw = proc.stdout or "{}"
    findings = _parse_findings(ecosystem, raw)
    return {"ok": True, "findings": findings, "raw": raw,
            "exit_code": proc.returncode}


def _parse_findings(ecosystem: str, raw: str) -> list[dict]:
    """Extract {id, severity, package} list. Schema varies per tool."""
    findings: list[dict] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return findings

    if ecosystem in ("npm", "pnpm"):
        # npm/pnpm audit JSON: "vulnerabilities": { "<pkg>": {severity, via}}
        vulns = data.get("vulnerabilities") or {}
        if isinstance(vulns, dict):
            for pkg, info in vulns.items():
                if not isinstance(info, dict):
                    continue
                sev = (info.get("severity") or "").lower()
                via = info.get("via") or []
                if isinstance(via, list):
                    for v in via:
                        if isinstance(v, dict):
                            findings.append({
                                "id": v.get("source") or v.get("url") or pkg,
                                "package": pkg,
                                "severity": sev,
                                "title": v.get("title", ""),
                            })
                        else:
                            findings.append({
                                "id": pkg, "package": pkg,
                                "severity": sev, "title": str(v),
                            })
                else:
                    findings.append({
                        "id": pkg, "package": pkg,
                        "severity": sev, "title": "",
                    })
    elif ecosystem == "pip":
        # pip-audit: {"dependencies": [{"name","version","vulns":[{id,fix_versions,description}]}]}
        for dep in (data.get("dependencies") or []):
            pkg = dep.get("name", "")
            for v in dep.get("vulns", []):
                findings.append({
                    "id": v.get("id", ""),
                    "package": pkg,
                    "severity": (v.get("severity") or "medium").lower(),
                    "title": v.get("description", "")[:80],
                })
    elif ecosystem == "cargo":
        for vuln in (data.get("vulnerabilities", {}).get("list", []) or []):
            adv = vuln.get("advisory", {}) or {}
            findings.append({
                "id": adv.get("id", ""),
                "package": adv.get("package", ""),
                "severity": (adv.get("severity") or "medium").lower(),
                "title": adv.get("title", ""),
            })
    return findings


def _load_waivers(path: Path) -> set:
    """Return set of waived CVE ids. Super-light YAML parser (stdlib only)."""
    if not path.exists():
        return set()
    waived: set = set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return waived
    # Accept simple `- id: CVE-XXXX-YYYY` list entries + `cve: CVE-...` forms
    for m in re.finditer(r"(?:^|\n)\s*(?:-\s+)?(?:id|cve|cve_id)\s*:\s*"
                         r"([^\s#]+)", text):
        waived.add(m.group(1).strip().strip('"').strip("'"))
    return waived


def _bucketize(findings: list[dict], waived: set) -> dict:
    """Count by severity, excluding waived."""
    buckets: dict = {"critical": 0, "high": 0, "medium": 0,
                     "moderate": 0, "low": 0, "info": 0, "other": 0}
    kept: list[dict] = []
    for f in findings:
        if f.get("id") in waived:
            continue
        s = (f.get("severity") or "").lower()
        if s in buckets:
            buckets[s] += 1
        else:
            buckets["other"] += 1
        kept.append(f)
    # Fold moderate→medium (npm uses moderate, others use medium)
    buckets["medium"] += buckets.pop("moderate", 0)
    # Fold critical→high for budget comparison (caller can split)
    return {"buckets": buckets, "kept_findings": kept}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project-root", default=".",
                    help="repo root containing lockfile (default: .)")
    ap.add_argument("--ecosystem", choices=["npm", "pnpm", "yarn", "pip",
                                             "cargo"],
                    default=None, help="override auto-detection")
    ap.add_argument("--budget-high", type=int, default=0,
                    help="max high-severity CVEs allowed (default: 0)")
    ap.add_argument("--budget-medium", type=int, default=5,
                    help="max medium-severity CVEs (WARN only by default)")
    ap.add_argument("--strict-medium", action="store_true",
                    help="treat medium-over-budget as BLOCK")
    ap.add_argument("--waiver-file", default=".vg/cve-waivers.yml",
                    help="path to waiver file (default: .vg/cve-waivers.yml)")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"⛔ project-root missing: {root}", file=sys.stderr)
        return 2

    ecosystem = args.ecosystem or _detect_ecosystem(root)
    if ecosystem is None:
        print("⛔ No lockfile detected (package-lock.json, pnpm-lock.yaml, "
              "yarn.lock, Cargo.lock, requirements.txt)", file=sys.stderr)
        return 2

    result = _run_audit(ecosystem, root, args.timeout)
    if not result["ok"]:
        print(f"⛔ Audit failed: {result.get('error')}", file=sys.stderr)
        return 2

    waivers = _load_waivers(root / args.waiver_file)
    analysis = _bucketize(result["findings"], waivers)
    buckets = analysis["buckets"]

    # Critical counts as high for budget
    high_count = buckets.get("high", 0) + buckets.get("critical", 0)
    medium_count = buckets.get("medium", 0)
    low_count = buckets.get("low", 0) + buckets.get("info", 0)

    violations: list[dict] = []
    if high_count > args.budget_high:
        violations.append({
            "severity": "BLOCK", "bucket": "high",
            "found": high_count, "budget": args.budget_high,
        })
    if medium_count > args.budget_medium:
        violations.append({
            "severity": "BLOCK" if args.strict_medium else "WARN",
            "bucket": "medium",
            "found": medium_count, "budget": args.budget_medium,
        })

    blocks = [v for v in violations if v["severity"] == "BLOCK"]
    warns = [v for v in violations if v["severity"] == "WARN"]

    report = {
        "ecosystem": ecosystem,
        "project_root": str(root),
        "waivers_applied": len(waivers),
        "buckets": buckets,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "violations": violations,
        "block_count": len(blocks),
        "warn_count": len(warns),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if blocks:
            print(f"⛔ Dependency vuln budget: {len(blocks)} BLOCK, "
                  f"{len(warns)} WARN\n")
            for v in violations:
                print(f"  [{v['severity']}] {v['bucket']}: found "
                      f"{v['found']} / budget {v['budget']}")
        elif warns and not args.quiet:
            print(f"⚠  Dep vuln: {len(warns)} WARN within budget tolerance")
            for v in warns:
                print(f"  [WARN] {v['bucket']}: found "
                      f"{v['found']} / budget {v['budget']}")
        elif not args.quiet:
            print(
                f"✓ Dep vuln budget OK — high={high_count}/"
                f"{args.budget_high}, medium={medium_count}/"
                f"{args.budget_medium} ({ecosystem})"
            )

    return 1 if blocks else 0


if __name__ == "__main__":
    sys.exit(main())
