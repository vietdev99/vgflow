#!/usr/bin/env python3
"""
derive-findings.py — v2.35.0 findings aggregator.

Reads every `runs/{resource}-{role}.json` run artifact, extracts findings
(steps with status==fail), dedupes, and writes:

  ${PHASE_DIR}/REVIEW-FINDINGS.json   — machine-readable, schema-validated
  ${PHASE_DIR}/REVIEW-BUGS.md         — Strix-style human-readable triage doc

Findings are NOT auto-routed to /vg:build in v2.35.0 (deferred to v2.37
after schema dogfood per Codex review).

Dedupe key: `{resource}-{role}-{step}-{normalized_title}`

Usage:
  derive-findings.py --phase-dir <path>
  derive-findings.py --phase-dir <path> --json
  derive-findings.py --phase-dir <path> --severity-floor high  # only emit >= high

Exit codes:
  0 — derivation succeeded
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
SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def load_run(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_runs(phase_dir: Path) -> list[dict]:
    runs_dir = phase_dir / "runs"
    if not runs_dir.is_dir():
        return []
    out: list[dict] = []
    # v2.40 Task 26h — per-tool subdir layout: runs/{gemini,codex,claude}/.
    # Backward-compat: also pick up legacy artifacts at runs/ root.
    paths = list(runs_dir.glob("*.json"))
    paths.extend(runs_dir.glob("*/recursive-*.json"))
    paths.extend(runs_dir.glob("*/*.json"))
    seen_paths: set[Path] = set()
    for p in sorted(paths):
        if p in seen_paths:
            continue
        seen_paths.add(p)
        if p.name in {"INDEX.json"}:
            continue
        data = load_run(p)
        if data:
            data["_source_path"] = str(p)
            out.append(data)
    return out


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def dedupe(findings: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for f in findings:
        key = f.get("dedupe_key") or f"{f.get('resource', '?')}-{f.get('role', '?')}-{f.get('step_ref', '?')}-{normalize_title(f.get('title', ''))}"
        if key in seen:
            seen[key].setdefault("duplicate_count", 1)
            seen[key]["duplicate_count"] += 1
        else:
            f["dedupe_key"] = key
            seen[key] = f
    return list(seen.values())


def aggregate_findings(runs: list[dict], severity_floor: str | None) -> list[dict]:
    floor_n = SEVERITY_ORDER.get(severity_floor or "info", 0)
    out: list[dict] = []
    for run in runs:
        resource = run.get("resource", "?")
        role = run.get("role", "?")
        for finding in run.get("findings") or []:
            sev = (finding.get("severity") or "info").lower()
            if SEVERITY_ORDER.get(sev, 0) < floor_n:
                continue
            entry = {**finding, "resource": resource, "role": role}
            entry.setdefault("dedupe_key", "")
            out.append(entry)
    return dedupe(out)


def aggregate_coverage(runs: list[dict]) -> dict:
    totals = {"attempted": 0, "passed": 0, "failed": 0, "blocked": 0, "skipped": 0}
    by_resource_role: list[dict] = []
    for run in runs:
        cov = run.get("coverage") or {}
        for k in totals:
            totals[k] += int(cov.get(k, 0))
        by_resource_role.append({
            "resource": run.get("resource"),
            "role": run.get("role"),
            "kit": run.get("kit"),
            "coverage": cov,
            "cleanup_status": run.get("cleanup_status"),
        })
    return {"totals": totals, "by_resource_role": by_resource_role}


def write_findings_json(out_path: Path, findings: list[dict], coverage: dict, run_count: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "generated": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runs_processed": run_count,
        "coverage": coverage,
        "findings_total": len(findings),
        "findings": sorted(findings, key=lambda f: -SEVERITY_ORDER.get((f.get("severity") or "info").lower(), 0)),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_bugs_md(out_path: Path, findings: list[dict], coverage: dict, run_count: int) -> None:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_sev: dict[str, list[dict]] = {}
    for f in findings:
        by_sev.setdefault((f.get("severity") or "info").lower(), []).append(f)

    lines: list[str] = []
    lines.append("# REVIEW-BUGS.md")
    lines.append("")
    lines.append(f"_Generated: {now}_")
    lines.append("")
    lines.append("Auto-derived from CRUD round-trip workflow runs (`runs/{resource}-{role}.json`).")
    lines.append("Each entry maps to a real divergence between expected behavior (per CRUD-SURFACES expected_behavior matrix) and observed runtime behavior.")
    lines.append("")
    lines.append("## Coverage summary")
    lines.append("")
    t = coverage.get("totals", {})
    lines.append(f"- Runs processed: {run_count}")
    lines.append(f"- Steps attempted: {t.get('attempted', 0)}")
    lines.append(f"- Passed: {t.get('passed', 0)} | Failed: {t.get('failed', 0)} | Blocked: {t.get('blocked', 0)} | Skipped: {t.get('skipped', 0)}")
    lines.append(f"- **Findings total: {len(findings)}**")
    lines.append("")

    for sev in ("critical", "high", "medium", "low", "info"):
        items = by_sev.get(sev) or []
        if not items:
            continue
        lines.append(f"## {sev.upper()} — {len(items)}")
        lines.append("")
        for f in items:
            lines.append(f"### `{f.get('id', '?')}` — {f.get('title', '(no title)')}")
            lines.append("")
            lines.append(f"- **Resource × Role:** {f.get('resource', '?')} × {f.get('role', '?')}")
            lines.append(f"- **Step:** {f.get('step_ref', '?')}")
            lines.append(f"- **Security impact:** {f.get('security_impact', 'none')}")
            lines.append(f"- **Confidence:** {f.get('confidence', 'unknown')}")
            if f.get("trace_id"):
                lines.append(f"- **Trace ID:** `{f['trace_id']}`")
            if f.get("cwe"):
                lines.append(f"- **CWE:** {f['cwe']}")
            lines.append("")

            actor = f.get("actor") or {}
            if actor:
                actor_str = ", ".join(f"{k}={v}" for k, v in actor.items() if v)
                lines.append(f"**Actor:** {actor_str or '(unknown)'}")
                lines.append("")

            req = f.get("request") or {}
            resp = f.get("response") or {}
            if req or resp:
                lines.append("**Request/response evidence:**")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps({"request": req, "response": resp}, indent=2)[:2000])
                lines.append("```")
                lines.append("")

            data_created = f.get("data_created") or []
            if data_created:
                lines.append("**Data created during repro:**")
                lines.append("")
                for dc in data_created:
                    lines.append(f"- {dc}")
                lines.append("")

            cleanup = f.get("cleanup_status")
            if cleanup:
                lines.append(f"**Cleanup status:** `{cleanup}`")
                lines.append("")

            remediation = f.get("remediation_steps") or []
            if remediation:
                lines.append("**Remediation:**")
                lines.append("")
                for step in remediation:
                    lines.append(f"- {step}")
                lines.append("")

            if f.get("duplicate_count", 1) > 1:
                lines.append(f"_(Observed {f['duplicate_count']} times across runs — deduped by `{f.get('dedupe_key')}`)_")
                lines.append("")

            lines.append("---")
            lines.append("")

    if not findings:
        lines.append("✅ No findings emitted. All run artifacts had `coverage.failed == 0`.")
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--severity-floor", default=None, choices=list(SEVERITY_ORDER.keys()))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 1

    runs = load_runs(phase_dir)
    if not runs:
        if not args.quiet:
            print(f"  (no runs/*.json found in {phase_dir} — nothing to derive)")
        return 0

    findings = aggregate_findings(runs, args.severity_floor)
    coverage = aggregate_coverage(runs)

    findings_path = phase_dir / "REVIEW-FINDINGS.json"
    bugs_path = phase_dir / "REVIEW-BUGS.md"

    write_findings_json(findings_path, findings, coverage, len(runs))
    write_bugs_md(bugs_path, findings, coverage, len(runs))

    if args.json:
        print(json.dumps({
            "findings_path": str(findings_path),
            "bugs_md_path": str(bugs_path),
            "findings_total": len(findings),
            "runs_processed": len(runs),
            "coverage_totals": coverage["totals"],
        }, indent=2))
    elif not args.quiet:
        print(f"✓ REVIEW-FINDINGS.json — {len(findings)} finding(s) across {len(runs)} run(s)")
        t = coverage["totals"]
        print(f"  Steps: attempted={t['attempted']} pass={t['passed']} fail={t['failed']} blocked={t['blocked']} skip={t['skipped']}")
        print(f"  REVIEW-BUGS.md → {bugs_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
