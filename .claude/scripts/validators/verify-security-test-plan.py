#!/usr/bin/env python3
"""
Validator: verify-security-test-plan.py

Phase D v2.5 (2026-04-23): project-wide SECURITY-TEST-PLAN.md schema check.

Reads .vg/SECURITY-TEST-PLAN.md (fallback .planning/SECURITY-TEST-PLAN.md),
parses all 8 sections, enforces:
- §1: risk_profile ∈ {critical, moderate, low}
- §2: dast_tool ∈ {ZAP, Nuclei, Custom, None} + payload_profile filled
- §3: ≥1 SAST tool listed (non-empty)
- §4: approach ∈ {external-vendor-annual, internal-team-quarterly,
       bug-bounty-continuous, none} + last_test_date OR "pending"
- §5: required only if §4 approach != none (platform + scope)
- §6: framework ∈ {SOC2-Type-II, ISO-27001, PCI-DSS-L1..L4, HIPAA, GDPR, none}
       + ≥1 control line if framework != none
- §7: IR contact + escalation_path + disclosure_policy present
- §8: threshold present (≥1 severity tier line)

Cross-checks with FOUNDATION §9.5 (if both exist):
- FOUNDATION mentions "GDPR" but §6 says "none" → WARN
- §1 risk_profile = "critical" AND §2 dast_tool = "None" → HARD BLOCK

Severity:
- File missing + phase < 14 → skip (rc=0)
- File missing + phase >= 14 → HARD BLOCK
- Invalid enum value in §1-§4/§6 → HARD BLOCK
- critical risk + DAST=None → HARD BLOCK
- §5 empty when approach != none → BLOCK (§5 required)
- §7/§8 fields empty → WARN
- GDPR/FOUNDATION mismatch → WARN

Usage:
  verify-security-test-plan.py --phase <N>

Exit codes:
  0  PASS or WARN (advisory)
  1  BLOCK (hard gate violation)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Cutover phase: file is mandatory at phase >= this number
_CUTOVER_PHASE = 14

# Section header pattern: `## 1. ...` through `## 8. ...`
SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.+)$", re.MULTILINE)

# Allowed enum values (lower-cased for matching)
RISK_PROFILE_VALUES = {"critical", "moderate", "low"}
DAST_TOOL_VALUES = {"zap", "nuclei", "custom", "none"}
PENTEST_APPROACH_VALUES = {
    "external-vendor-annual",
    "internal-team-quarterly",
    "bug-bounty-continuous",
    "none",
}
COMPLIANCE_FRAMEWORK_VALUES = {
    "soc2-type-ii",
    "iso-27001",
    "pci-dss-l1",
    "pci-dss-l2",
    "pci-dss-l3",
    "pci-dss-l4",
    "hipaa",
    "gdpr",
    "none",
}


def _phase_number(phase_str: str) -> float:
    """Convert phase string to float for numeric comparison."""
    try:
        return float(phase_str.lstrip("0") or "0")
    except ValueError:
        return 0.0


def _find_stp_file() -> Path | None:
    """Locate SECURITY-TEST-PLAN.md in .vg/ then .planning/."""
    for candidate in (
        REPO_ROOT / ".vg" / "SECURITY-TEST-PLAN.md",
        REPO_ROOT / ".planning" / "SECURITY-TEST-PLAN.md",
    ):
        if candidate.exists():
            return candidate
    return None


def _split_sections(text: str) -> dict[int, str]:
    """Return {section_number: section_body_text} for all ## N. headers."""
    sections: dict[int, str] = {}
    matches = list(SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        num = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[num] = text[start:end]
    return sections


def _backtick_value(text: str) -> str | None:
    """Extract first `...` backtick-quoted value in text."""
    m = re.search(r"`([^`]+)`", text)
    return m.group(1).strip() if m else None


def _field_line(text: str, label: str) -> str | None:
    """Extract value from `**Label:** value` line."""
    m = re.search(
        rf"^\*\*{re.escape(label)}\s*:\*\*\s*(.+)$",
        text, re.MULTILINE | re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def _has_bullet_items(text: str) -> bool:
    """True if text contains ≥1 markdown list item (- or * followed by text)."""
    return bool(re.search(r"^\s*[-*]\s+\S", text, re.MULTILINE))


def _parse_foundation_section9(foundation_path: Path) -> str:
    """Return §9.5 (or §9) text from FOUNDATION.md if it exists."""
    if not foundation_path.exists():
        return ""
    raw = foundation_path.read_text(encoding="utf-8", errors="replace")
    # Try §9.5 first, then §9
    for pattern in (
        r"##\s+9\.5[^\n]*\n(.*?)(?=\n##\s|\Z)",
        r"##\s+9[^\n]*\n(.*?)(?=\n##\s|\Z)",
    ):
        m = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="verify-security-test-plan")
    with timer(out):
        phase_num = _phase_number(args.phase)
        stp_path = _find_stp_file()

        # ── Missing file check ──────────────────────────────────────────
        if stp_path is None:
            if phase_num < _CUTOVER_PHASE:
                # Advisory skip — no file yet, not yet mandatory
                emit_and_exit(out)
            else:
                out.add(Evidence(
                    type="stp_missing",
                    message=t("stp.missing.message"),
                    fix_hint=t("stp.missing.fix_hint"),
                ))
                emit_and_exit(out)

        text = stp_path.read_text(encoding="utf-8", errors="replace")
        sections = _split_sections(text)

        # ── §1 Risk Classification ──────────────────────────────────────
        s1 = sections.get(1, "")
        risk_raw = _backtick_value(_field_line(s1, "Risk profile") or s1)
        risk_profile: str | None = None
        if risk_raw:
            risk_profile = risk_raw.lower().strip("|").strip()
            # Handle template placeholder `{CRITICAL|MODERATE|LOW}`
            if "|" in risk_profile or risk_profile.startswith("{"):
                risk_profile = None

        if not risk_profile or risk_profile not in RISK_PROFILE_VALUES:
            out.add(Evidence(
                type="stp_schema_invalid",
                message=t(
                    "stp.schema_invalid.message",
                    section="§1 Risk Classification",
                    field="risk_profile",
                    got=risk_raw or "(empty)",
                    allowed=", ".join(sorted(RISK_PROFILE_VALUES)),
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))

        # ── §2 DAST ─────────────────────────────────────────────────────
        s2 = sections.get(2, "")
        dast_raw = _backtick_value(_field_line(s2, "Tool") or s2)
        dast_tool: str | None = None
        if dast_raw:
            dast_tool = dast_raw.lower().strip("|").strip()
            if "|" in dast_tool or dast_tool.startswith("{"):
                dast_tool = None

        if not dast_tool or dast_tool not in DAST_TOOL_VALUES:
            out.add(Evidence(
                type="stp_schema_invalid",
                message=t(
                    "stp.schema_invalid.message",
                    section="§2 DAST",
                    field="dast_tool",
                    got=dast_raw or "(empty)",
                    allowed=", ".join(sorted(DAST_TOOL_VALUES)),
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))

        # payload_profile required (must not be template placeholder)
        payload_raw = _backtick_value(_field_line(s2, "Payload profile") or "")
        if not payload_raw or payload_raw.startswith("{"):
            out.add(Evidence(
                type="stp_schema_invalid",
                message=t(
                    "stp.schema_invalid.message",
                    section="§2 DAST",
                    field="payload_profile",
                    got=payload_raw or "(empty)",
                    allowed="owasp-top10-2021, custom, minimal",
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))

        # ── §3 SAST ──────────────────────────────────────────────────────
        s3 = sections.get(3, "")
        if not _has_bullet_items(s3):
            out.add(Evidence(
                type="stp_schema_invalid",
                message=t(
                    "stp.schema_invalid.message",
                    section="§3 Static Analysis (SAST)",
                    field="sast_tools",
                    got="(empty)",
                    allowed="at least 1 tool listed as bullet item",
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))

        # ── §4 Pen-Test Strategy ─────────────────────────────────────────
        s4 = sections.get(4, "")
        approach_raw = _backtick_value(_field_line(s4, "Approach") or s4)
        pentest_approach: str | None = None
        if approach_raw:
            pentest_approach = approach_raw.lower().strip("|").strip()
            if "|" in pentest_approach or pentest_approach.startswith("{"):
                pentest_approach = None

        if not pentest_approach or pentest_approach not in PENTEST_APPROACH_VALUES:
            out.add(Evidence(
                type="stp_schema_invalid",
                message=t(
                    "stp.schema_invalid.message",
                    section="§4 Pen-Test Strategy",
                    field="approach",
                    got=approach_raw or "(empty)",
                    allowed=", ".join(sorted(PENTEST_APPROACH_VALUES)),
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))

        # last_test_date: must be filled OR contain "pending"
        last_date_raw = _field_line(s4, "Last test date") or ""
        last_date_placeholder = (
            not last_date_raw
            or last_date_raw.strip("{}").startswith("{")
            or (
                "pending" not in last_date_raw.lower()
                and re.match(r"^\{.*\}$", last_date_raw.strip())
            )
        )
        if last_date_placeholder and last_date_raw and "pending" not in last_date_raw.lower():
            # Only warn — date might be legitimately unfilled for new projects
            out.warn(Evidence(
                type="stp_last_test_date_empty",
                message=t(
                    "stp.schema_invalid.message",
                    section="§4 Pen-Test Strategy",
                    field="last_test_date",
                    got=last_date_raw or "(empty)",
                    allowed='actual date or "pending milestone M1 completion"',
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))

        # ── §5 Bug Bounty ────────────────────────────────────────────────
        s5 = sections.get(5, "")
        if pentest_approach and pentest_approach != "none":
            # §5 required — platform and scope must be non-placeholder
            platform_raw = _backtick_value(_field_line(s5, "Platform") or s5)
            platform_ok = bool(
                platform_raw and not platform_raw.startswith("{")
            )
            scope_raw = _field_line(s5, "Scope") or ""
            scope_ok = bool(scope_raw and not scope_raw.startswith("{"))
            if not platform_ok or not scope_ok:
                out.add(Evidence(
                    type="stp_schema_invalid",
                    message=t(
                        "stp.schema_invalid.message",
                        section="§5 Bug Bounty",
                        field="platform/scope",
                        got=f"platform={platform_raw!r} scope={scope_raw!r}",
                        allowed="filled platform (HackerOne|Bugcrowd|self-hosted|none) + scope",
                    ),
                    fix_hint=t("stp.schema_invalid.fix_hint"),
                ))

        # ── §6 Compliance Framework ──────────────────────────────────────
        s6 = sections.get(6, "")
        framework_raw = _backtick_value(_field_line(s6, "Framework") or s6)
        framework: str | None = None
        if framework_raw:
            framework = framework_raw.lower().strip("|").strip()
            if "|" in framework or framework.startswith("{"):
                framework = None

        if not framework or framework not in COMPLIANCE_FRAMEWORK_VALUES:
            out.add(Evidence(
                type="stp_schema_invalid",
                message=t(
                    "stp.schema_invalid.message",
                    section="§6 Compliance Framework",
                    field="framework",
                    got=framework_raw or "(empty)",
                    allowed=", ".join(sorted(COMPLIANCE_FRAMEWORK_VALUES)),
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))
        elif framework != "none" and not _has_bullet_items(s6):
            out.add(Evidence(
                type="stp_schema_invalid",
                message=t(
                    "stp.schema_invalid.message",
                    section="§6 Compliance Framework",
                    field="control_list",
                    got="(empty)",
                    allowed=f"at least 1 control line for framework={framework_raw}",
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))

        # ── §7 Incident Response ─────────────────────────────────────────
        s7 = sections.get(7, "")
        ir_contact = _field_line(s7, "IR team contact") or ""
        escalation = _field_line(s7, "Escalation path") or ""
        disclosure = _field_line(s7, "Public disclosure policy") or ""

        missing_s7 = []
        if not ir_contact or ir_contact.startswith("{"):
            missing_s7.append("IR team contact")
        if not escalation or escalation.startswith("{"):
            missing_s7.append("Escalation path")
        if not disclosure or disclosure.startswith("{"):
            missing_s7.append("Public disclosure policy")

        if missing_s7:
            out.warn(Evidence(
                type="stp_ir_fields_empty",
                message=t(
                    "stp.schema_invalid.message",
                    section="§7 Incident Response",
                    field=", ".join(missing_s7),
                    got="(empty or template placeholder)",
                    allowed="filled contact / escalation path / disclosure policy",
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))

        # ── §8 Acceptable Residual Risk ──────────────────────────────────
        s8 = sections.get(8, "")
        threshold_line = _field_line(s8, "Threshold") or ""
        has_severity_tiers = _has_bullet_items(s8)

        if (not threshold_line or threshold_line.startswith("{")) and not has_severity_tiers:
            out.warn(Evidence(
                type="stp_threshold_empty",
                message=t(
                    "stp.schema_invalid.message",
                    section="§8 Acceptable Residual Risk",
                    field="threshold",
                    got="(empty)",
                    allowed="Threshold field or severity tier bullet list",
                ),
                fix_hint=t("stp.schema_invalid.fix_hint"),
            ))

        # ── Cross-check: critical risk + DAST=None → HARD BLOCK ─────────
        if (
            risk_profile == "critical"
            and dast_tool == "none"
        ):
            out.add(Evidence(
                type="stp_critical_dast_none",
                message=t("stp.critical_dast_none.message"),
                actual=f"risk_profile=critical, dast_tool=None",
                fix_hint=t("stp.critical_dast_none.fix_hint"),
            ))

        # ── Cross-check: FOUNDATION §9.5 GDPR vs §6 framework ───────────
        foundation_path = REPO_ROOT / ".vg" / "FOUNDATION.md"
        if not foundation_path.exists():
            foundation_path = REPO_ROOT / ".planning" / "FOUNDATION.md"

        if foundation_path.exists() and framework is not None:
            foundation_s9 = _parse_foundation_section9(foundation_path)
            if (
                re.search(r"\bGDPR\b", foundation_s9, re.IGNORECASE)
                and framework == "none"
            ):
                out.warn(Evidence(
                    type="stp_consistency_mismatch",
                    message=t("stp.consistency_mismatch.message",
                              found_in="FOUNDATION §9.5",
                              term="GDPR",
                              section="§6 Compliance Framework",
                              value="none"),
                    fix_hint=t("stp.consistency_mismatch.fix_hint"),
                ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
