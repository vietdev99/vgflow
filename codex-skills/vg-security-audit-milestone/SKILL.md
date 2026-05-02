---
name: "vg-security-audit-milestone"
description: "Cross-phase security audit for current milestone — correlate threats, apply decay, surface composite risks, generate audit report"
metadata:
  short-description: "Cross-phase security audit for current milestone — correlate threats, apply decay, surface composite risks, generate audit report"
---

<codex_skill_adapter>
## Codex runtime notes

This skill body is generated from VGFlow's canonical source. Claude Code and
Codex use the same workflow contracts, but their orchestration primitives differ.

### Tool mapping

| Claude Code concept | Codex-compatible pattern | Notes |
|---|---|---|
| AskUserQuestion | Ask concise questions in the main Codex thread | Codex does not expose the same structured prompt tool inside generated skills. Persist answers where the skill requires it; prefer Codex-native options such as `codex-inline` when the source prompt distinguishes providers. |
| Agent(...) / Task | Prefer `commands/vg/_shared/lib/codex-spawn.sh` or native Codex subagents | Use `codex exec` when exact model, timeout, output file, or schema control matters. |
| TaskCreate / TaskUpdate / TodoWrite | Native Codex tasklist/plan projection + orchestrator step markers | Use `tasklist-contract.json` as source of truth. After projecting, emit `vg-orchestrator tasklist-projected --adapter codex`; if no native task UI is exposed, use `--adapter fallback` and `run-status --pretty`. |
| Playwright MCP | Main Codex orchestrator MCP tools, or smoke-tested subagents | If an MCP-using subagent cannot access tools in a target environment, fall back to orchestrator-driven/inline scanner flow. |
| Graphify MCP | Python/CLI graphify calls | VGFlow's build/review paths already use deterministic scripts where possible. |

<codex_runtime_contract>
### Provider/runtime parity contract

This generated skill must preserve the source command's artifacts, gates,
telemetry events, and step ordering on both Claude and Codex. Do not remove,
skip, or weaken a source workflow step because a Claude-only primitive appears
in the body below.

#### Provider mapping

| Source pattern | Claude path | Codex path |
|---|---|---|
| Planner/research/checker Agent | Use the source `Agent(...)` call and configured model tier | Use native Codex subagents only if the local Codex version has been smoke-tested; otherwise write the child prompt to a temp file and call `commands/vg/_shared/lib/codex-spawn.sh --tier planner` |
| Build executor Agent | Use the source executor `Agent(...)` call | Use `codex-spawn.sh --tier executor --sandbox workspace-write` with explicit file ownership and expected artifact output |
| Adversarial/CrossAI reviewer | Use configured external CLIs and consensus validators | Use configured `codex exec`/Gemini/Claude commands from `.claude/vg.config.md`; fail if required CLI output is missing or unparsable |
| Haiku scanner / Playwright / Maestro / MCP-heavy work | Use Claude subagents where the source command requires them | Keep MCP-heavy work in the main Codex orchestrator unless child MCP access was smoke-tested; scanner work may run inline/sequential instead of parallel, but must write the same scan artifacts and events |
| Reflection / learning | Use `vg-reflector` workflow | Use the Codex `vg-reflector` adapter or `codex-spawn.sh --tier scanner`; candidates still require the same user gate |

### Codex hook parity

Claude Code has a project-local hook substrate; Codex skills do not receive
Claude `UserPromptSubmit`, `Stop`, or `PostToolUse` hooks automatically.
Therefore Codex must execute the lifecycle explicitly through the same
orchestrator that writes `.vg/events.db`:

| Claude hook | What it does on Claude | Codex obligation |
|---|---|---|
| `UserPromptSubmit` -> `vg-entry-hook.py` | Pre-seeds `vg-orchestrator run-start` and `.vg/.session-context.json` before the skill loads | Treat the command body's explicit `vg-orchestrator run-start` as mandatory; if missing or failing, BLOCK before doing work |
| `Stop` -> `vg-verify-claim.py` | Runs `vg-orchestrator run-complete` and blocks false done claims | Run the command body's terminal `vg-orchestrator run-complete` before claiming completion; if it returns non-zero, fix evidence and retry |
| `PostToolUse` edit -> `vg-edit-warn.py` | Warns that command/skill edits require session reload | After editing VG workflow files on Codex, tell the user the current session may still use cached skill text |
| `PostToolUse` Bash -> `vg-step-tracker.py` | Tracks marker commands and emits `hook.step_active` telemetry | Do not rely on the hook; call explicit `vg-orchestrator mark-step` lines in the skill and preserve marker/telemetry events |

Codex hook parity is evidence-based: `.vg/events.db`, step markers,
`must_emit_telemetry`, and `run-complete` output are authoritative. A Codex
run is not complete just because the model says it is complete.

Before executing command bash blocks from a Codex skill, export
`VG_RUNTIME=codex`. This is an adapter signal, not a source replacement:
Claude/unknown runtime keeps the canonical `AskUserQuestion` + Haiku path,
while Codex maps only the incompatible orchestration primitives to
Codex-native choices such as `codex-inline`.

### Codex spawn precedence

When the source workflow below says `Agent(...)` or "spawn", Codex MUST
apply this table instead of treating the Claude syntax as executable:

| Source spawn site | Codex action | Tier/model env | Sandbox | Required evidence |
|---|---|---|---|---|
| `/vg:build` wave executor, `model="${MODEL_EXECUTOR}"` | Write one prompt file per task, run `codex-spawn.sh --tier executor`; parallelize independent tasks with background processes and `wait`, serialize dependency groups | `VG_CODEX_MODEL_EXECUTOR`; leave unset to use Codex config default. Set this to the user's strongest coding model when they want Sonnet-class build quality. | `workspace-write` | child output, stdout/stderr logs, changed files, verification commands, task-fidelity prompt evidence |
| `/vg:blueprint`, `/vg:scope`, planner/checker agents | Run `codex-spawn.sh --tier planner` or inline in the main orchestrator if the step needs interactive user answers | `VG_CODEX_MODEL_PLANNER` | `workspace-write` for artifact-writing planners, `read-only` for pure checks | requested artifacts or JSON verdict |
| `/vg:review` navigator/scanner, `Agent(model="haiku")` | Use `--scanner=codex-inline` by default. Do NOT ask to spawn Haiku or blindly spawn `codex exec` for Playwright/Maestro work. Main Codex orchestrator owns MCP/browser/device actions. Use `codex-spawn.sh --tier scanner --sandbox read-only` only for non-MCP classification over captured snapshots/artifacts. | `VG_CODEX_MODEL_SCANNER`; set this to a cheap/fast model for review map/scanner work | `read-only` unless explicitly generating scan files from supplied evidence | same `scan-*.json`, `RUNTIME-MAP.json`, `GOAL-COVERAGE-MATRIX.md`, and `review.haiku_scanner_spawned` telemetry event semantics |
| `/vg:review` fix agents and `/vg:test` codegen agents | Use `codex-spawn.sh --tier executor` because they edit code/tests | `VG_CODEX_MODEL_EXECUTOR` or explicit `--model` if the command selected a configured fix model | `workspace-write` | changed files, tests run, unresolved risks |
| Rationalization guard, reflector, gap hunters | Use `codex-spawn.sh --tier scanner` for read-only classification, or `--tier adversarial` for independent challenge/review | `VG_CODEX_MODEL_SCANNER` or `VG_CODEX_MODEL_ADVERSARIAL` | `read-only` by default | compact JSON/markdown verdict; fail closed on empty/unparseable output |

If a source sentence says "MUST spawn Haiku" and the step needs MCP/browser
tools, Codex interprets that as "MUST run the scanner protocol and emit the
same artifacts/events"; it does not require a child process unless child MCP
access was smoke-tested in the current environment.

#### Non-negotiable guarantees

- Never skip source workflow gates, validators, telemetry events, or must-write artifacts.
- If Codex cannot emulate a Claude primitive safely, BLOCK instead of silently degrading.
- UI/UX, security, and business-flow checks remain artifact/gate driven: follow the source command's DESIGN/UI-MAP/TEST-GOALS/security validator requirements exactly.
- A slower Codex inline path is acceptable; a weaker path that omits evidence is not.
</codex_runtime_contract>

### Model tier mapping

Model mapping is tier-based, not vendor-name-based.

VGFlow keeps tier names in `.claude/vg.config.md`; Codex subprocesses use
the user's Codex config model by default. Pin a tier only after smoke-testing
that model in the target account, via `VG_CODEX_MODEL_PLANNER`,
`VG_CODEX_MODEL_EXECUTOR`, `VG_CODEX_MODEL_SCANNER`, or
`VG_CODEX_MODEL_ADVERSARIAL`:

| VG tier | Claude-style role | Codex default | Fallback |
|---|---|---|---|
| planner | Opus-class planning/reasoning | Codex config default | Set `VG_CODEX_MODEL_PLANNER` only after smoke-testing |
| executor | Sonnet-class coding/review | Codex config default | Set `VG_CODEX_MODEL_EXECUTOR` only after smoke-testing |
| scanner | Haiku-class scan/classify | Codex config default | Set `VG_CODEX_MODEL_SCANNER` only after smoke-testing |
| adversarial | independent reviewer | Codex config default | Set `VG_CODEX_MODEL_ADVERSARIAL` only after smoke-testing |

### Spawn helper

For subprocess-based children, use:

```bash
bash .claude/commands/vg/_shared/lib/codex-spawn.sh \
  --tier executor \
  --prompt-file "$PROMPT_FILE" \
  --out "$OUT_FILE" \
  --timeout 900 \
  --sandbox workspace-write
```

The helper wraps `codex exec`, writes the final message to `--out`, captures
stdout/stderr beside it, and fails loudly on timeout or empty output.

### Known Codex caveats to design around

- Do not trust inline model selection for native subagents unless verified in the current Codex version; use TOML-pinned agents or `codex exec --model`.
- Do not combine structured `--output-schema` with MCP-heavy runs until the target Codex version is smoke-tested. Prefer plain text + post-parse for MCP flows.
- Recursive `codex exec` runs inherit sandbox constraints. Use the least sandbox that still allows the child to write expected artifacts.

### Support-skill MCP pattern

Pattern A: INLINE ORCHESTRATOR. For MCP-heavy support skills such as
`vg-haiku-scanner`, Codex keeps Playwright/Maestro actions in the main
orchestrator and only delegates read-only classification after snapshots are
captured. This preserves MCP access and avoids false confidence from a child
process that cannot see browser tools.

## Invocation

Invoke this skill as `$vg-security-audit-milestone`. Treat all user text after the skill name as arguments.
</codex_skill_adapter>



<objective>
Cross-phase security correlation that per-phase `/vg:secure-phase` cannot catch.

Three operations:
1. **Decay**: auto-escalate unresolved OPEN threats, auto-archive old MITIGATED
2. **Correlate**: apply `config.security.composite_rules` to detect threats spanning multiple phases (e.g., broken-auth + broken-access = critical composite)
3. **Report**: generate `${PLANNING_DIR}/security-audit-{date}.md` with trends, open counts, composite risks

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

Write `${PLANNING_DIR}/security-audit-${today}.md`:

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

Attach to `${PLANNING_DIR}/milestones/${milestone}/` if milestone dir exists, else to `${PLANNING_DIR}/` root.
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
    echo "   See: ${PLANNING_DIR}/SECURITY-REGISTER.md"
    exit 1
  fi
fi
```
</step>

<step name="5_pentest_checklist">
## Step 5 — Generate Pen-Test Checklist (v2.5 Phase I)

If `.vg/SECURITY-TEST-PLAN.md` present (Phase D v2.5 artifact), generate a HUMAN-curated pen-test checklist aggregating:
- All HTTP endpoints from phase API-CONTRACTS grouped by auth model
- OPEN threats carry-over from phase SECURITY-REGISTER files
- Risk-profile-aware priority test vectors (critical → chain attacks; low → hygiene only)
- Compliance control mapping based on framework declared in SECURITY-TEST-PLAN §6

Output: `.vg/milestones/{milestone}/SECURITY-PENTEST-CHECKLIST.md` — artifact for external/internal pentesters.

VG does NOT run pentests. It curates + formats info so humans can pentest effectively.

```bash
# Optional via flag --pentest-checklist, or auto when SECURITY-TEST-PLAN.md exists
STP_FILE="${PLANNING_DIR:-.vg}/SECURITY-TEST-PLAN.md"
MILESTONE_ID="${MILESTONE_ID:-}"

# Resolve milestone from arg or STATE.md
if [ -z "$MILESTONE_ID" ] && [[ "$ARGUMENTS" =~ --milestone=([A-Za-z0-9.-]+) ]]; then
  MILESTONE_ID="${BASH_REMATCH[1]}"
fi
if [ -z "$MILESTONE_ID" ] && [ -f "${PLANNING_DIR:-.vg}/STATE.md" ]; then
  MILESTONE_ID=$(grep -oE "current_milestone:\s*\S+" "${PLANNING_DIR:-.vg}/STATE.md" 2>/dev/null | awk '{print $2}')
fi
MILESTONE_ID="${MILESTONE_ID:-M1}"

SHOULD_GEN=false
[[ "$ARGUMENTS" =~ --pentest-checklist ]] && SHOULD_GEN=true
[ -f "$STP_FILE" ] && SHOULD_GEN=true

if [ "$SHOULD_GEN" = "true" ]; then
  if [ ! -f "$STP_FILE" ]; then
    echo "⚠ Pentest checklist requested via --pentest-checklist but SECURITY-TEST-PLAN.md missing."
    echo "  Run /vg:project --update to populate Round 8 (Phase D), then retry."
  else
    echo ""
    echo "━━━ Step 5 — Pen-Test Checklist Generation (Phase I v2.5) ━━━"
    ${PYTHON_BIN:-python3} .claude/scripts/generate-pentest-checklist.py \
      --milestone "$MILESTONE_ID"
    GEN_RC=$?
    if [ "$GEN_RC" -eq 0 ]; then
      echo "  ✓ Checklist ready for pentester hand-off"
      echo "    Location: ${PLANNING_DIR:-.vg}/milestones/${MILESTONE_ID}/SECURITY-PENTEST-CHECKLIST.md"
    elif [ "$GEN_RC" -eq 2 ]; then
      echo "  (milestone ${MILESTONE_ID} has no phases yet — skipped)"
    else
      echo "  ⚠ Checklist generation failed (rc=${GEN_RC}) — see stderr above"
    fi
  fi
fi
```
</step>

<step name="6_strix_advisory">
## Step 6 — Strix Scan Advisory (v2.32.0, optional plugin)

If `vg.config.md → security.strix_advisor.enabled` is true (default), generate
a `STRIX-ADVISORY.md` recommending the user run [usestrix/strix](https://github.com/usestrix/strix)
— an autonomous AI pentest agent — against the milestone's accumulated attack
surface.

**VG does NOT run Strix.** Step 5 outputs a checklist for human pentesters;
Step 6 outputs an analogous advisory for AI pentesters. Both are curation, not
execution. Strix needs Docker + a separate LLM API key + a reachable target
URL — all user-side concerns intentionally kept outside VG's dependency
surface.

The advisor:
- Aggregates `adversarial_scope.threats` declarations from each phase's
  TEST-GOALS.md (v2.21.0 declarative threat schema).
- Aggregates HTTP endpoints from API-CONTRACTS.md grouped by auth model.
- Emits `STRIX-ADVISORY.md` (markdown) + `strix-scope.json` (machine-readable
  for Strix `--scope-file`).
- Provides ready-to-copy `docker run ghcr.io/usestrix/strix:latest …`
  invocation tailored to the declared threats.

```bash
ADV_ENABLED=$(vg_config_get "security.strix_advisor.enabled" "true" 2>/dev/null || echo "true")

if [ "$ADV_ENABLED" = "true" ]; then
  echo ""
  echo "━━━ Step 6 — Strix Scan Advisory (v2.32.0 plugin) ━━━"

  STRIX_SCRIPT=".claude/scripts/generate-strix-advisory.py"
  if [ ! -f "$STRIX_SCRIPT" ]; then
    echo "  ⚠ Strix advisor script missing at $STRIX_SCRIPT — skipping."
  else
    ADV_TARGET=$(vg_config_get "security.strix_advisor.target_url" "" 2>/dev/null || echo "")
    ADV_ARGS=( "--milestone" "${MILESTONE_ID}" )
    [ -n "$ADV_TARGET" ] && ADV_ARGS+=( "--target-url" "$ADV_TARGET" )

    ${PYTHON_BIN:-python3} "$STRIX_SCRIPT" "${ADV_ARGS[@]}"
    ADV_RC=$?
    if [ "$ADV_RC" -eq 0 ]; then
      echo "  ✓ Strix advisory ready at .vg/milestones/${MILESTONE_ID}/STRIX-ADVISORY.md"
      echo "    Disable: set security.strix_advisor.enabled: false in vg.config.md"
    elif [ "$ADV_RC" -eq 1 ]; then
      echo "  (no phases resolved for ${MILESTONE_ID} — advisory skipped)"
    else
      echo "  ⚠ Advisory generation failed (rc=${ADV_RC}) — see stderr above"
    fi
  fi
else
  echo "(strix_advisor disabled in vg.config.md — skipping Step 6)"
fi
```
</step>

</process>

<success_criteria>
- Decay policy applied (escalate stale OPEN, archive old MITIGATED)
- Composite threats computed per config.security.composite_rules
- `${PLANNING_DIR}/security-audit-{date}.md` written with exec summary + trends
- Telemetry events emitted for escalations + composites
- Milestone complete gate: blocks if critical OPEN threats exist
- Zero register corruption on failure (atomic writes via temp file + rename)
</success_criteria>
