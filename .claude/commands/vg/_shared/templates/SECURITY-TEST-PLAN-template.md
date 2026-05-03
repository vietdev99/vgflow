# Security Test Plan — {PROJECT_NAME}

Generated: {ISO_TIMESTAMP}
FOUNDATION §9 reference: {FOUNDATION_PATH}
Last updated: {ISO_TIMESTAMP}

---

## 1. Risk Classification

**Risk profile:** `{CRITICAL|MODERATE|LOW}`

**Justification:**
{Why this level — prose reasoning citing data sensitivity / auth model / user base}

**Implications:**
- DAST severity: High finding = {BLOCK|WARN|advisory}
- Pen-test frequency: {annual|quarterly|continuous|none}
- Incident response SLA: {critical=1hr / moderate=24hr / low=72hr}

---

## 2. DAST (Dynamic Application Security Testing)

**Tool:** `{ZAP|Nuclei|Custom|None}`
**Payload profile:** `{owasp-top10-2021|custom|minimal}`
**Scan timeout:** `{seconds}`
**Scan frequency:** every `/vg:test` step 5h

{If None: reason read-only project / no HTTP endpoints}

---

## 3. Static Analysis (SAST)

Beyond VG's built-in validators (verify-goal-security / verify-security-baseline):
- `{tool_name}` for `{language/framework}` — e.g., Semgrep for TypeScript, Bandit for Python
- Check frequency: {on-commit via pre-commit | weekly CI | quarterly audit}

---

## 4. Pen-Test Strategy

**Approach:** `{external-vendor-annual | internal-team-quarterly | bug-bounty-continuous | none}`
**Scope:** {endpoint list / role list / dashboard areas covered}
**Vendor contact:** {name + email if external}
**Last test date:** {or "pending milestone M1 completion"}
**Next scheduled:** {date or trigger}

---

## 5. Bug Bounty (if applicable)

**Platform:** `{HackerOne|Bugcrowd|self-hosted|none}`
**Scope:** {in-scope assets}
**Out of scope:** {exclusions — DoS, staff accounts, 3rd-party deps}
**Reward tier:**
- Critical: ${amount range}
- High: ${amount range}
- Medium: ${amount range}
- Low: ${amount range}
**Disclosure timeline:** {30/60/90 days standard}

---

## 6. Compliance Framework Mapping

**Framework:** `{SOC2-Type-II|ISO-27001|PCI-DSS-L1|PCI-DSS-L2|PCI-DSS-L3|PCI-DSS-L4|HIPAA|GDPR|none}`

**Control list:**
{Map relevant controls to phases + validators. Example:}
- CC6.1 (Logical access) → verify-authz-declared + FOUNDATION §9.5 session/identity
- CC7.2 (System monitoring) → FOUNDATION §9.5 audit log events
- A.12.4 (Logging/monitoring) → FOUNDATION §9.5 + deploy gate logs

---

## 7. Incident Response

**IR team contact:** {name/email/pager}
**Escalation path:** {L1 → L2 → CTO within Xhrs}
**Public disclosure policy:** {immediate|7-day|30-day after fix}
**Post-mortem SLA:** {days to write post-mortem after incident closure}

---

## 8. Acceptable Residual Risk

**Threshold:** `{severity + max days}`

Examples:
- Critical severity: 0 days acceptable — must block ship
- High severity: 7 days acceptable with compensating control
- Medium severity: 30 days acceptable with scheduled fix
- Low severity: 90 days acceptable backlog

**Debt register integration:** security debt appended to `.vg/override-debt/register.jsonl` via `/vg:override-resolve`
