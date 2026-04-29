#!/usr/bin/env python3
"""
route-findings-to-build.py — v2.37.0 auto-fix loop.

Reads `${PHASE_DIR}/REVIEW-FINDINGS.json` (v2.35) and emits
`${PHASE_DIR}/AUTO-FIX-TASKS.md` with /vg:build-consumable task entries.

Per Codex review feedback (v2.35 design): not auto-routed in v2.35
because dedupe + confidence schema needed dogfood validation. v2.37
ships the route layer with conservative gates:

- Only severity ≥ high
- Only confidence == high
- Skip findings with cleanup_status != completed (data integrity risk)
- Group by dedupe_key (single fix task can address N occurrences)
- Manual approval still required — emits tasks file, /vg:build reads
  with --include-auto-fix flag (off by default in v2.37, may flip
  default in v2.38 after dogfood)

Usage:
  route-findings-to-build.py --phase-dir <path>
  route-findings-to-build.py --phase-dir <path> --include-medium
  route-findings-to-build.py --phase-dir <path> --json
  route-findings-to-build.py --phase-dir <path> --check  # report what would route, no write

Exit codes:
  0 — tasks emitted (or no qualifying findings)
  1 — IO error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


SEVERITY_PASS = {"critical", "high"}
SEVERITY_PASS_WITH_MEDIUM = {"critical", "high", "medium"}


def load_findings(phase_dir: Path) -> dict:
    p = phase_dir / "REVIEW-FINDINGS.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def filter_findings(findings: list[dict], include_medium: bool) -> list[dict]:
    sev_pass = SEVERITY_PASS_WITH_MEDIUM if include_medium else SEVERITY_PASS
    out: list[dict] = []
    for f in findings:
        sev = (f.get("severity") or "info").lower()
        if sev not in sev_pass:
            continue
        if (f.get("confidence") or "low").lower() != "high":
            continue
        if f.get("cleanup_status") and f.get("cleanup_status") != "completed":
            continue
        out.append(f)
    return out


def group_by_dedupe(findings: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for f in findings:
        key = f.get("dedupe_key") or f.get("id") or "unknown"
        groups.setdefault(key, []).append(f)
    return groups


def render_tasks(groups: dict[str, list[dict]], phase_dir: Path) -> str:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    lines.append("# AUTO-FIX-TASKS.md")
    lines.append("")
    lines.append(f"_Generated: {now} by `route-findings-to-build.py` (v2.37.0+)_")
    lines.append("")
    lines.append("Auto-routed from `REVIEW-FINDINGS.json`. Each task entry maps to a deduplicated finding cluster.")
    lines.append("")
    lines.append("`/vg:build` reads this file with `--include-auto-fix` flag (opt-in v2.37, may default-on in v2.38 after dogfood).")
    lines.append("")
    lines.append("**Filtering:** severity ≥ high, confidence == high, cleanup_status == completed.")
    lines.append("")
    lines.append(f"## Tasks ({len(groups)})")
    lines.append("")

    sorted_keys = sorted(groups.keys(), key=lambda k: -len(groups[k]))

    for idx, key in enumerate(sorted_keys, start=1):
        findings = groups[key]
        primary = findings[0]
        occurrence_count = len(findings)
        affected_resources = sorted({f.get("resource") for f in findings if f.get("resource")})
        affected_roles = sorted({f.get("role") for f in findings if f.get("role")})

        lines.append(f"### Task AF-{idx:03d} — {primary.get('title', '(no title)')}")
        lines.append("")
        lines.append(f"- **Severity:** {primary.get('severity', 'unknown')}")
        lines.append(f"- **Confidence:** {primary.get('confidence', 'unknown')}")
        lines.append(f"- **Security impact:** {primary.get('security_impact', 'none')}")
        lines.append(f"- **Dedupe key:** `{key}`")
        lines.append(f"- **Occurrence count:** {occurrence_count}")
        if affected_resources:
            lines.append(f"- **Affected resources:** {', '.join(affected_resources)}")
        if affected_roles:
            lines.append(f"- **Affected roles:** {', '.join(affected_roles)}")
        if primary.get("cwe"):
            lines.append(f"- **CWE:** {primary['cwe']}")
        lines.append("")

        remediation = primary.get("remediation_steps") or []
        if remediation:
            lines.append("**Remediation steps (from finding):**")
            lines.append("")
            for step in remediation:
                lines.append(f"- {step}")
            lines.append("")

        repro = primary.get("repro_preconditions") or []
        if repro:
            lines.append("**Repro preconditions:**")
            lines.append("")
            for r in repro:
                lines.append(f"- {r}")
            lines.append("")

        lines.append("**Source findings:**")
        lines.append("")
        for f in findings[:5]:
            lines.append(f"- `{f.get('id', '?')}` {f.get('resource', '?')} × {f.get('role', '?')} (step {f.get('step_ref', '?')})")
        if len(findings) > 5:
            lines.append(f"- … + {len(findings) - 5} more (see REVIEW-FINDINGS.json)")
        lines.append("")
        lines.append("**/vg:build instructions:**")
        lines.append("")
        lines.append("1. Read this task entry + corresponding REVIEW-FINDINGS.json finding(s)")
        lines.append("2. Apply remediation steps")
        lines.append("3. Re-run `/vg:review {phase}` to verify finding closed")
        lines.append("4. If verified: mark this task complete in commit message: `fix(P{phase}.AF-{idx:03d}):`".replace("{idx:03d}", f"{idx:03d}"))
        lines.append("")
        lines.append("---")
        lines.append("")

    if not groups:
        lines.append("✅ No qualifying findings to route. Either no high/critical bugs, or pending dogfood data quality.")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--include-medium", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"⛔ Phase dir not found: {phase_dir}", file=sys.stderr)
        return 1

    data = load_findings(phase_dir)
    findings = data.get("findings") or []

    qualified = filter_findings(findings, args.include_medium)
    groups = group_by_dedupe(qualified)

    payload = {
        "phase_dir": str(phase_dir),
        "total_findings": len(findings),
        "qualified": len(qualified),
        "task_groups": len(groups),
        "checked_only": args.check,
    }

    if args.check:
        if args.json:
            print(json.dumps(payload, indent=2))
        elif not args.quiet:
            print(f"  Total findings: {len(findings)}")
            print(f"  Qualified (≥{'medium' if args.include_medium else 'high'}, confidence=high, cleanup=completed): {len(qualified)}")
            print(f"  After dedupe: {len(groups)} task group(s)")
        return 0

    if not groups:
        if not args.quiet:
            print(f"  (no qualifying findings — AUTO-FIX-TASKS.md not written)")
        return 0

    body = render_tasks(groups, phase_dir)
    out_path = phase_dir / "AUTO-FIX-TASKS.md"
    tmp = out_path.with_suffix(".md.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(out_path)

    if args.json:
        payload["out_path"] = str(out_path)
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        print(f"✓ AUTO-FIX-TASKS.md written ({len(groups)} task group(s) from {len(findings)} finding(s))")
        print(f"  Path: {out_path}")
        print(f"  Run /vg:build {phase_dir.name.split('-')[0]} --include-auto-fix to consume")

    return 0


if __name__ == "__main__":
    sys.exit(main())
