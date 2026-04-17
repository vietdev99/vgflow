---
name: "vg-security-audit-milestone"
description: "Cross-phase security audit for current milestone — correlate threats, apply decay, surface composite risks, generate audit report"
metadata:
  short-description: "Cross-phase security audit for current milestone — correlate threats, apply decay, surface composite risks, generate audit report"
---

<codex_skill_adapter>
## Codex ⇆ Claude Code tool mapping

This skill was originally designed for Claude Code. When running in Codex CLI:

| Claude tool | Codex equivalent |
|------|------------------|
| AskUserQuestion | request_user_input (free-form text, or number-prefix choices) |
| Task (agent spawn) | Use `codex exec --model <model>` subprocess with isolated prompt |
| TaskCreate/TaskUpdate | N/A — use inline markdown headers and status narration |
| WebFetch | `curl -sfL` or `gh api` for GitHub URLs |
| Bash/Read/Write/Edit/Glob/Grep | Same — Codex supports these natively |

## Invocation

This skill is invoked by mentioning `$vg-security-audit-milestone`. Treat all user text after `$vg-security-audit-milestone` as arguments.

If argument-hint in source frontmatter is not empty and user provides no args, ask once via request_user_input before proceeding.
</codex_skill_adapter>


<objective>
Cross-phase security correlation that per-phase `/vg:secure-phase` cannot catch.

Three operations:
1. **Decay**: auto-escalate unresolved OPEN threats, auto-archive old MITIGATED
2. **Correlate**: apply `config.security.composite_rules` to detect threats spanning multiple phases (e.g., broken-auth + broken-access = critical composite)
3. **Report**: generate `.planning/security-audit-{date}.md` with trends, open counts, composite risks

Run before milestone completion OR on-demand for periodic security posture review.
</objective>

<process>

<step name="0_config">
Source `_shared/config-loader.md` + `_shared/security-register.md` + `_shared/telemetry.md`.

Read:
- `CONFIG_SECURITY_REGISTER_PATH`
- `CONFIG_SECURITY_COMPOSITE_RULES` (yaml list)
- `CONFIG_SECURITY_DECAY_POLICY_*`
- `CONFIG_PATHS_PLANNING_DIR`

Parse args:
- `--dry-run` — don't modify register, just report what would change
- `--since=<ISO>` — limit analysis window
- `--threshold=<severity>` — only report threats at this severity or higher

If register missing:
```
echo "No SECURITY-REGISTER.md yet. Run /vg:secure-phase on at least one phase first."
exit 0
```
</step>

<step name="1_apply_decay">

```bash
if [ "$ARG_DRY_RUN" = "true" ]; then
  echo "━━━ Decay preview (dry-run) ━━━"
  # Parse register, show what WOULD change without writing
  # (helper returns list of pending transitions)
else
  echo "━━━ Applying decay policy ━━━"
  apply_decay_policy
fi
```

Decay rules (from helper):
- `MITIGATED + age ≥ archive_days` → ARCHIVED
- `OPEN/IN_PROGRESS + severity ≥ high + age ≥ escalate_days` → severity +1 tier

Emit telemetry event per transition:
```bash
emit_telemetry "debt_escalated" "$phase" "security-audit-milestone" \
  "{\"threat_id\":\"$tid\",\"severity\":\"$new_sev\",\"age_days\":$age}"
```
</step>

<step name="2_correlate_composite">

Composite correlation: threats spanning ≥ N phases matching specific taxonomy patterns combine into single higher-severity composite.

```bash
${PYTHON_BIN:-python3} - <<'PY'
import re, yaml, json, sys
from pathlib import Path

register = Path("${CONFIG_SECURITY_REGISTER_PATH}")
config_rules = yaml.safe_load("""
${CONFIG_SECURITY_COMPOSITE_RULES_YAML}
""") or []

text = register.read_text(encoding='utf-8')
# Parse Threats table → list of dicts
rows = []
row_re = re.compile(r'^\| (SEC-\d+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|', re.M)
for m in row_re.finditer(text):
  rows.append({
    "id": m.group(1),
    "severity": m.group(2).strip(),
    "phases": [p.strip() for p in m.group(3).split(",")],
    "taxonomy": [t.strip() for t in m.group(4).split(",")],
    "title": m.group(5).strip(),
    "status": m.group(6).strip(),
  })

# Parse existing Composite table
comp_existing = set()
comp_re = re.compile(r'^\| (COMP-\d+) \|', re.M)
for m in comp_re.finditer(text):
  comp_existing.add(m.group(1))

# Apply rules
new_composites = []
for rule in config_rules:
  patterns = set(rule.get("patterns", []))
  phases_min = rule.get("phases_min", 2)
  # Find OPEN threats matching ALL rule patterns across DIFFERENT phases
  matching = [r for r in rows if r["status"] in ("OPEN","IN_PROGRESS") and any(p in tax for p in patterns for tax in r["taxonomy"])]
  if not matching: continue
  phases_set = set()
  for r in matching: phases_set.update(r["phases"])
  if len(phases_set) >= phases_min:
    comp_id = f"COMP-{len(comp_existing)+len(new_composites)+1:03d}"
    new_composites.append({
      "id": comp_id,
      "components": [r["id"] for r in matching],
      "phases": sorted(phases_set),
      "severity": rule["resulting_severity"],
      "rule": rule["name"],
    })

# Write to register (append to Composite section)
if new_composites and "${ARG_DRY_RUN}" != "true":
  lines = text.splitlines()
  for i, line in enumerate(lines):
    if line.strip().startswith("| Composite ID"):
      # Skip header row + separator
      insert_at = i + 2
      for comp in new_composites:
        row = f"| {comp['id']} | {', '.join(comp['components'])} | {', '.join(comp['phases'])} | {comp['severity']} | {comp['rule']} |"
        lines.insert(insert_at, row)
        insert_at += 1
      break
  register.write_text("\n".join(lines) + "\n", encoding='utf-8')

print(json.dumps({"new_composites": new_composites, "existing_count": len(comp_existing)}))
PY
```

For each new composite, emit telemetry `security_cross_phase_threat`.
</step>

<step name="3_generate_audit_report">

Write `.planning/security-audit-${today}.md`:

```markdown
# Security Milestone Audit — ${milestone_id}
Date: {today}
Dry-run: {true|false}

## Executive Summary

- Total threats tracked: {total}
- OPEN: {open_count} ({critical_open}⚡ critical, {high_open} high)
- MITIGATED: {mitigated}
- ARCHIVED: {archived}
- Composite threats: {composite_count} (new this run: {new_comp})

## Decay Transitions This Run

| Threat ID | Transition | Reason |
|-----------|------------|--------|
| SEC-012 | high → critical | unresolved 35d |
| SEC-005 | MITIGATED → ARCHIVED | mitigated 92d ago |

## New Composite Threats

| Composite | Components | Phases | Combined Severity | Rule |
|-----------|-----------|--------|-------------------|------|
| COMP-003 | SEC-002, SEC-014 | 5, 7.8, 7.12 | critical | info-disclosure-chain |

## Open Critical (action required)

{per-threat block: ID, title, phases, evidence needed, suggested mitigation}

## Taxonomy Distribution

{count per STRIDE category} / {count per OWASP Top 10 category}

## Trend (last 4 audits)

| Date | Total | Open | Critical | Composites |
|------|-------|------|----------|------------|
| ... |

## Recommendations

- {if composite emerged}: "Prioritize fixing {composite_id} — touches phases {phases}. Fix components {components}."
- {if escalated}: "{N} threats auto-escalated. Review SECURITY-REGISTER.md decay log."
- {if open critical ≥ 3}: "Milestone cannot complete per config. Run /vg:secure-phase on affected phases."
```

Attach to `.planning/milestones/${milestone}/` if milestone dir exists, else to `.planning/` root.
</step>

<step name="4_milestone_complete_gate">

If called from `/vg:complete-milestone` flow (via `--milestone-gate`):
- Count open critical threats
- If `config.security.milestone_audit.required_before_milestone_complete == true`:
  - `open_critical > 0` → BLOCK milestone complete
  - Else → PASS

```bash
if [[ "$ARGUMENTS" =~ --milestone-gate ]]; then
  open_crit=$(count threats where status IN (OPEN, IN_PROGRESS) AND severity == "critical")
  if [ "$open_crit" -gt 0 ]; then
    echo "⛔ Milestone gate: ${open_crit} critical threats OPEN. Cannot archive milestone."
    echo "   See: .planning/SECURITY-REGISTER.md"
    exit 1
  fi
fi
```
</step>

</process>

<success_criteria>
- Decay policy applied (escalate stale OPEN, archive old MITIGATED)
- Composite threats computed per config.security.composite_rules
- `.planning/security-audit-{date}.md` written with exec summary + trends
- Telemetry events emitted for escalations + composites
- Milestone complete gate: blocks if critical OPEN threats exist
- Zero register corruption on failure (atomic writes via temp file + rename)
</success_criteria>
