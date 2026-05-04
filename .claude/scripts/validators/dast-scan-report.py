#!/usr/bin/env python3
"""
Validator: dast-scan-report.py

Phase B.5 v2.5 (2026-04-23): tier 2 dynamic scan report parser. Reads the
DAST report JSON produced by `.claude/commands/vg/_shared/lib/dast-runner.sh`
(ZAP baseline / full / api, OR Nuclei) and routes findings through a
severity matrix keyed on project `risk_profile`.

Severity matrix:
  risk_profile=critical  → Critical/High = HARD BLOCK, Medium = WARN
  risk_profile=moderate  → Critical/High = WARN,       Medium = advisory WARN
  risk_profile=low       → all findings  = advisory WARN (never blocks)

Special cases:
  - Report file missing → WARN (dast_scan_skipped)
  - Report malformed JSON → WARN (dast_report_unparseable)
  - grep-only format (cascade fallback) → WARN (dast_scan_skipped)

Usage:
  dast-scan-report.py --phase <N> --report <path> --risk-profile <level>

Exit codes:
  0 PASS or WARN
  1 BLOCK (Critical/High finding in critical risk profile)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

SEVERITY_ORDER = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1, "Info": 0}

# Map raw severity strings from scanners → canonical bucket labels.
SEVERITY_NORMALIZE = {
    "critical": "Critical",
    "high":     "High",
    "medium":   "Medium",
    "moderate": "Medium",
    "low":      "Low",
    "info":     "Info",
    "informational": "Info",
    "unknown":  "Info",
    "":         "Info",
}


def _normalize_severity(raw: object) -> str:
    # ZAP riskdesc is typically "High (Medium)" where the first token is the
    # risk level and the parenthesised value is the confidence — we only
    # care about the risk level.
    s = str(raw or "").strip().lower()
    if not s:
        return "Info"
    # Strip anything after first space / paren
    head = s.split("(")[0].split()[0].strip() if s else ""
    return SEVERITY_NORMALIZE.get(head, SEVERITY_NORMALIZE.get(s, "Info"))


def _detect_format(data: object) -> str:
    """Return 'zap' | 'nuclei' | 'grep-only' | 'unknown'."""
    if isinstance(data, dict):
        # grep-only fallback marker
        if data.get("format") == "grep-only":
            return "grep-only"
        # ZAP baseline output has top-level `site` array of site objects with
        # `alerts` list. `@programName` is also a ZAP marker.
        if "site" in data or "@programName" in data:
            return "zap"
        # Nuclei can emit single-object when only one finding — detect via info.severity
        info = data.get("info")
        if isinstance(info, dict) and "severity" in info:
            return "nuclei"
    if isinstance(data, list):
        # Nuclei jsonl-like: list of finding objects each with `info.severity`
        if data and isinstance(data[0], dict):
            info = data[0].get("info")
            if isinstance(info, dict) and "severity" in info:
                return "nuclei"
    return "unknown"


def _normalize_zap(data: dict) -> list[dict]:
    findings: list[dict] = []
    sites = data.get("site") or []
    if isinstance(sites, dict):
        sites = [sites]
    for site in sites:
        if not isinstance(site, dict):
            continue
        alerts = site.get("alerts") or []
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            instances = alert.get("instances") or [{}]
            first = instances[0] if isinstance(instances, list) and instances else {}
            findings.append({
                "tool": "zap",
                "name": alert.get("alert") or alert.get("name") or "(unnamed)",
                "severity": _normalize_severity(alert.get("riskdesc") or alert.get("risk")),
                "url": (first.get("uri") if isinstance(first, dict) else None) or site.get("@name", ""),
                "cwe": str(alert.get("cweid") or ""),
                "description": (alert.get("desc") or "")[:200],
            })
    return findings


def _normalize_nuclei(data: object) -> list[dict]:
    findings: list[dict] = []
    items = data if isinstance(data, list) else [data]
    for item in items:
        if not isinstance(item, dict):
            continue
        info = item.get("info") or {}
        classification = info.get("classification") or {}
        findings.append({
            "tool": "nuclei",
            "name": info.get("name") or item.get("template-id") or "(unnamed)",
            "severity": _normalize_severity(info.get("severity")),
            "url": item.get("matched-at") or item.get("host") or "",
            "cwe": ",".join(classification.get("cwe-id") or []) if isinstance(classification.get("cwe-id"), list) else str(classification.get("cwe-id") or ""),
            "description": (info.get("description") or "")[:200],
        })
    return findings


def _group_by_severity(findings: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {
        "Critical": [], "High": [], "Medium": [], "Low": [], "Info": [],
    }
    for f in findings:
        buckets.setdefault(f.get("severity", "Info"), []).append(f)
    return buckets


def _format_sample(findings: list[dict], limit: int = 5) -> str:
    out = []
    for f in findings[:limit]:
        url = f.get("url") or ""
        out.append(
            f"[{f.get('severity')}] {f.get('name')} "
            f"({f.get('tool')}{': ' + url if url else ''})"
        )
    return "; ".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--report", required=True,
                    help="Path to DAST JSON report")
    ap.add_argument("--risk-profile", default="moderate",
                    choices=["critical", "moderate", "low"])
    args = ap.parse_args()

    out = Output(validator="dast-scan-report")
    with timer(out):
        # Phase dir resolution is advisory here (for narration) — validator
        # never requires a phase dir to exist; the report file is what matters.
        find_phase_dir(args.phase)  # noqa: F841 (side-effect only)

        report_path = Path(args.report)
        if not report_path.exists():
            out.warn(Evidence(
                type="dast_scan_skipped",
                message=t("dast.scan_skipped.message", path=str(report_path)),
                actual=f"report file not found: {report_path}",
                fix_hint=t("dast.scan_skipped.fix_hint"),
            ))
            emit_and_exit(out)
            return

        try:
            text = report_path.read_text(encoding="utf-8", errors="replace")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError) as exc:
            out.warn(Evidence(
                type="dast_report_unparseable",
                message=t("dast.report_unparseable.message",
                          path=str(report_path)),
                actual=f"{type(exc).__name__}: {exc}",
                fix_hint=t("dast.report_unparseable.fix_hint"),
            ))
            emit_and_exit(out)
            return

        fmt = _detect_format(data)
        if fmt == "grep-only":
            out.warn(Evidence(
                type="dast_scan_skipped",
                message=t("dast.scan_skipped.message", path=str(report_path)),
                actual="DAST cascade fell back to grep-only (no live scanner)",
                fix_hint=t("dast.scan_skipped.fix_hint"),
            ))
            emit_and_exit(out)
            return
        if fmt == "unknown":
            out.warn(Evidence(
                type="dast_report_unparseable",
                message=t("dast.report_unparseable.message",
                          path=str(report_path)),
                actual="format unrecognized (not ZAP, not Nuclei)",
                fix_hint=t("dast.report_unparseable.fix_hint"),
            ))
            emit_and_exit(out)
            return

        findings = (
            _normalize_zap(data) if fmt == "zap"
            else _normalize_nuclei(data)
        )
        buckets = _group_by_severity(findings)

        critical_high = buckets["Critical"] + buckets["High"]
        medium = buckets["Medium"]

        profile = args.risk_profile

        # Severity routing
        if critical_high:
            if profile == "critical":
                out.add(Evidence(
                    type="dast_critical_high_findings",
                    message=t(
                        "dast.critical_high.message",
                        count=len(critical_high),
                        profile=profile,
                    ),
                    actual=_format_sample(critical_high),
                    fix_hint=t("dast.critical_high.fix_hint"),
                ))
            else:
                # moderate + low: downgrade to WARN
                out.warn(Evidence(
                    type="dast_medium_findings_advisory",
                    message=t(
                        "dast.medium_advisory.message",
                        count=len(critical_high),
                        profile=profile,
                    ),
                    actual=_format_sample(critical_high),
                    fix_hint=t("dast.medium_advisory.fix_hint"),
                ))

        if medium:
            # Medium is always advisory (never blocks) regardless of profile.
            out.warn(Evidence(
                type="dast_medium_findings_advisory",
                message=t(
                    "dast.medium_advisory.message",
                    count=len(medium),
                    profile=profile,
                ),
                actual=_format_sample(medium),
                fix_hint=t("dast.medium_advisory.fix_hint"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
