# CrossAI Invocation (Shared Reference)

Referenced by discuss.md, plan.md, crossai-check.md, test-specs.md.
For full XML schema and mode details, see `.claude/skills/vg-crossai/SKILL.md`.

## Prerequisites

The calling command must prepare:
1. `$CONTEXT_FILE` — path to context file with prompt + artifacts
2. `$OUTPUT_DIR` — path to save CLI results (e.g., `${PHASE_DIR}/crossai/`)
3. `$LABEL` — descriptive label (e.g., `discuss-review`, `plan-review`, `total-check`)

## Infrastructure brief auto-enrich (v1.14.4+)

**Problem:** CrossAI CLIs spawn fresh — không có context về project infrastructure (MCP servers, Playwright lock manager, parallel capability, deploy topology). Thiếu = concern sai (vd: "Playwright không verify được 2 DSP instance trong 1 run" khi thực tế có 5 Playwright servers + lock manager).

**Fix:** Trước dispatch, auto-prepend `.vg/INFRASTRUCTURE.md` (nếu tồn tại) vào `$CONTEXT_FILE`. One-time write, reused across all CrossAI calls (blueprint/review/test/accept).

```bash
INFRA_BRIEF="${PLANNING_DIR:-.vg}/INFRASTRUCTURE.md"
if [ -f "$INFRA_BRIEF" ] && [ -f "$CONTEXT_FILE" ]; then
  # Check if not already prepended (idempotent)
  if ! head -5 "$CONTEXT_FILE" | grep -q "^# Infrastructure — "; then
    ENRICHED_CTX=$(mktemp "${VG_TMP:-/tmp}/crossai-ctx-enriched-XXXXXX.md")
    {
      echo "# Infrastructure brief (auto-injected)"
      echo ""
      echo "> CrossAI reviewers: đọc block này TRƯỚC KHI raise concerns về test-harness/parallel/infra. Project có sẵn resources documented dưới đây."
      echo ""
      cat "$INFRA_BRIEF"
      echo ""
      echo "---"
      echo ""
      echo "# Main context (original)"
      echo ""
      cat "$CONTEXT_FILE"
    } > "$ENRICHED_CTX"
    CONTEXT_FILE="$ENRICHED_CTX"
    echo "✓ CrossAI context enriched với INFRASTRUCTURE.md ($(wc -l < "$INFRA_BRIEF") lines infra brief)"
  fi
fi
```

**Placement:** Run BEFORE "Load Config" section. Works cho ALL label values (blueprint-review/review-check/test-check/accept-review).

## Load Config

Read `.claude/commands/vg/_shared/config-loader.md` if not already loaded.
Read `config.crossai_clis` — this is the list of configured CLIs.

**If `config.crossai_clis` is empty → skip invocation entirely. Return immediately with no results.**

## Adaptive Spawn Strategy

The number and identity of CLIs is config-driven. Strategy adapts to CLI count:

| CLI Count | Strategy |
|-----------|----------|
| 0 | Skip — no CLIs configured, return immediately |
| 1 | Single — run the one CLI, use its result directly (no consensus needed) |
| 2 | Fast-fail always — run both; if they agree → done; if disagree → flag for user |
| 3+ | Depends on `$LABEL` (see below) |

### For 3+ CLIs — Strategy by Label

| Label | Strategy | Rationale |
|-------|----------|-----------|
| `total-check` | Full (all CLIs always) | Final quality gate — no shortcuts |
| `discuss-review`, `plan-review`, `spec-review` | Fast-fail (first 2 CLIs) | Light reviews — 80% of time 2 CLIs agree |

### Spawn Execution

```bash
mkdir -p "$OUTPUT_DIR"

# Read CLIs from config
# config.crossai_clis = [
#   { name: "codex", command: "codex exec \"{prompt}\"", label: "Codex configured model" },
#   { name: "gemini", command: "cat \"{context}\" | gemini -m gemini-2.5-pro -p \"{prompt}\" --yolo", label: "Gemini Pro High 3.1" },
#   { name: "claude", command: "cat \"{context}\" | claude --model sonnet -p \"{prompt}\"", label: "Claude Sonnet 4.6" }
# ]

PROMPT="Review artifacts and output crossai_review XML per format specified"

# For each CLI in the spawn set:
#   1. Substitute {prompt} → $PROMPT and {context} → $CONTEXT_FILE in cli.command
#   2. Redirect output to "$OUTPUT_DIR/result-${cli.name}.xml"
#   3. Run as background process, capture PID

# Example for a 3-CLI config:
CROSSAI_TIMEOUT=120  # seconds — kill CLI if it hangs

declare -A CLI_STATUS  # name -> "ok|timeout|malformed|crash"

for cli in "${CROSSAI_CLIS[@]}"; do
  CMD=$(echo "${cli.command}" | sed "s|{prompt}|${PROMPT}|g" | sed "s|{context}|${CONTEXT_FILE}|g")
  # Run with explicit exit-code capture via wrapper file
  (
    timeout ${CROSSAI_TIMEOUT} bash -c "$CMD" > "$OUTPUT_DIR/result-${cli.name}.xml" 2>&1
    echo "$?" > "$OUTPUT_DIR/result-${cli.name}.exit"
  ) &
  PIDS+=($!)
done

wait "${PIDS[@]}"

# ⛔ HARD GATE (tightened 2026-04-17): distinguish timeout from empty.
# Previously both collapsed into "skip silently" — timeouts were treated as implicit agreement.
for cli in "${CROSSAI_CLIS[@]}"; do
  RESULT_FILE="$OUTPUT_DIR/result-${cli.name}.xml"
  EXIT_FILE="$OUTPUT_DIR/result-${cli.name}.exit"
  EXIT_CODE=$(cat "$EXIT_FILE" 2>/dev/null || echo "999")

  if [ "$EXIT_CODE" = "124" ]; then
    # GNU timeout signals exit 124 on timeout hit
    echo "⚠ ${cli.name} TIMEOUT after ${CROSSAI_TIMEOUT}s — marking as inconclusive (NOT skipped)."
    CLI_STATUS[${cli.name}]="timeout"
    mv "$RESULT_FILE" "$RESULT_FILE.timeout" 2>/dev/null || true
  elif [ ! -s "$RESULT_FILE" ]; then
    echo "⚠ ${cli.name} CRASH (empty output, exit=${EXIT_CODE}) — marking as inconclusive."
    CLI_STATUS[${cli.name}]="crash"
    rm -f "$RESULT_FILE"
  elif ! grep -q '<verdict>' "$RESULT_FILE" 2>/dev/null; then
    echo "⚠ ${cli.name} MALFORMED (no <verdict> tag, exit=${EXIT_CODE}) — marking as inconclusive."
    CLI_STATUS[${cli.name}]="malformed"
    mv "$RESULT_FILE" "$RESULT_FILE.malformed"
  else
    CLI_STATUS[${cli.name}]="ok"
  fi
done

# Count successful vs inconclusive
OK_COUNT=0
INCONCLUSIVE_COUNT=0
for status in "${CLI_STATUS[@]}"; do
  [ "$status" = "ok" ] && OK_COUNT=$((OK_COUNT + 1))
  [ "$status" != "ok" ] && INCONCLUSIVE_COUNT=$((INCONCLUSIVE_COUNT + 1))
done

# HARD RULE: if ALL CLIs inconclusive → verdict = INCONCLUSIVE (blocks pipeline unless --allow-crossai-inconclusive)
TOTAL_CLIS=${#CROSSAI_CLIS[@]}
if [ "$OK_COUNT" -eq 0 ] && [ "$TOTAL_CLIS" -gt 0 ]; then
  echo "⛔ All ${TOTAL_CLIS} CrossAI CLIs returned inconclusive (timeout/crash/malformed)."
  echo "   Cannot treat silence as consensus."
  CROSSAI_VERDICT="inconclusive"
  # Caller must decide to block or proceed with override
fi
```

### Fast-Fail Logic (for 2+ CLIs in fast-fail mode)

```bash
# After first 2 CLIs complete:
CLI1_VERDICT=$(sed -n 's/.*<verdict>\([^<]*\)<.*/\1/p' "$OUTPUT_DIR/result-${CLI1_NAME}.xml" 2>/dev/null)
CLI2_VERDICT=$(sed -n 's/.*<verdict>\([^<]*\)<.*/\1/p' "$OUTPUT_DIR/result-${CLI2_NAME}.xml" 2>/dev/null)

# Guard: empty verdicts = timeout/crash, NOT agreement
if [ -z "$CLI1_VERDICT" ] && [ -z "$CLI2_VERDICT" ]; then
  echo "⚠ All CLIs timed out or returned empty. CrossAI check INCONCLUSIVE — proceeding with warning."
  CROSSAI_VERDICT="inconclusive"
elif [ -z "$CLI1_VERDICT" ] || [ -z "$CLI2_VERDICT" ]; then
  CROSSAI_VERDICT="${CLI1_VERDICT:-$CLI2_VERDICT}"
  echo "⚠ One CLI empty. Using single verdict: $CROSSAI_VERDICT"
elif [[ "$CLI1_VERDICT" == "$CLI2_VERDICT" ]]; then
  # Agreement — skip remaining CLIs, build consensus from 2
  echo "Fast-fail: ${CLI1_NAME}+${CLI2_NAME} agree ($CLI1_VERDICT). Skipping remaining."
else
  # Disagreement — spawn next CLI as tiebreaker
  echo "Disagreement: ${CLI1_NAME}=$CLI1_VERDICT, ${CLI2_NAME}=$CLI2_VERDICT. Spawning tiebreaker."
  # Run CLI 3 (or flag for user if only 2 CLIs configured)
fi
```

After CLIs finish: verify each result file exists and is non-empty. Minimum requirement:
- 1 CLI configured → 1 result required
- 2 CLIs configured → 2 results required
- 3+ CLIs configured → minimum 2 results required

## Build Consensus

Read the result files. Parse `<verdict>`, `<score>`, `<findings>` from each.
**Only count CLIs where `CLI_STATUS[name] == "ok"` (tightened 2026-04-17).** Inconclusive CLIs do NOT vote.

**Severity rules (tightened 2026-04-17 — 3-way majority with flag fallback):**
- 1 CLI ok → use its severity directly
- 2 CLIs ok & agree → use agreed severity
- 2 CLIs ok & disagree → escalate to higher of the two
- 3+ CLIs ok & majority (≥ ⌈N/2⌉+1 same) → use majority severity
- 3+ CLIs ok & no majority (3-way split) → escalate to **major** (NOT the highest — prevents single alarmist CLI from forcing critical)

**Finding rules:**
- 2+ CLIs report same issue → **agreed finding**, use highest severity among those reporting
- Only 1 CLI reports → **disputed finding**, severity held at what that CLI said (NOT auto-escalated to major — wastes user attention on noise)
- Single CLI mode → all findings are **agreed** (nothing to dispute)

**Verdict rules (tightened 2026-04-17 — majority-based, safe fallback):**
- All ok CLIs agree → use that verdict
- Mixed verdicts:
  - Any **block** from ≥2 CLIs → **block**
  - Single **block** + others pass/flag → **flag** (safe middle ground, not full block — 1 alarmist ≠ real block)
  - 2+ **flag** → **flag**
  - 2+ **pass**, 1 **flag** → **pass** (with notes)
- Average score (across ok CLIs) < 6.0 → override to **flag** (not **block** — score is advisory signal, not hard fail)
- If consensus remains indeterminate after above rules → **flag** (safe default — forces user review)
- Caller (blueprint/review/test) interprets **flag** verdict per its own gate policy (usually: surface to user, don't auto-block unless critical gate).

## Save Consensus

Write consensus XML to `$OUTPUT_DIR/$LABEL.xml`. Format per vg-crossai SKILL.md.

## Emit verdict telemetry (v2.5 anti-forge — 2026-04-23)

**MANDATORY** — after CROSSAI_VERDICT is finalized, emit `crossai.verdict` event
to telemetry so the runtime_contract can verify CrossAI actually ran (not just
marker touched). Without this emit, /vg:blueprint + /vg:review contracts will
BLOCK at run-complete with "missing crossai.verdict" evidence.

```bash
# Emit verdict event — pairs with must_write crossai/result-*.xml files
# to prove CrossAI invocation actually happened (no silent skip).
if [ -n "${CROSSAI_VERDICT:-}" ]; then
  ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
    "crossai.verdict" \
    --payload "$(${PYTHON_BIN:-python3} -c "
import json
print(json.dumps({
    'verdict': '${CROSSAI_VERDICT}',
    'ok_count': int('${OK_COUNT:-0}'),
    'total_clis': int('${TOTAL_CLIS:-0}'),
    'label': '${LABEL:-crossai}',
    'phase': '${PHASE_NUMBER:-unknown}',
}))
")" 2>/dev/null || true
fi
```

## Cleanup

```bash
rm -f "$CONTEXT_FILE"
```

Keep CLI result files in `$OUTPUT_DIR/` for audit trail.
  

---

## Output contract for PLAN/CONTEXT enrichment (Phase 16 D-05)

When cross-AI peer (Codex / Gemini) enriches `PLAN.md` or `CONTEXT.md`,
output MUST follow these rules so the enrichment value SURVIVES the
pipeline through R4 budget caps without silent truncation, AND so the
`verify-crossai-output.py` validator (P16 D-06) passes.

### Rules

1. **DO NOT inline prose blocks > 30 lines into a `<task>` body.**
   Long prose grows R4 budget pressure and gets truncated at the
   executor stage (Phase 15 W3 deferred + Phase 17 polish surfaced this).
   Instead:
   a. Append a new decision block to `CONTEXT.md` (e.g.,
      `### P{phase}.D-99: <title>`).
   b. Reference it from the task via
      `<context-refs>P{phase}.D-99</context-refs>`.

2. **Edge cases → frontmatter `edge_cases:` array**, not body bullets:
   ```yaml
   edge_cases:
     - "New edge case discovered by cross-AI"
   ```

3. **Decision rationale → CONTEXT.md decision body**, not task body
   comment.

4. **Format flag**: cross-AI invoker MUST set `cross_ai_enriched: true`
   in CONTEXT.md frontmatter when enrichment changes any task body.
   Triggers Phase 16 D-04 R4 conditional caps (cap bumps) so enriched
   content isn't silently truncated downstream.

### Validator

`scripts/validators/verify-crossai-output.py` runs AFTER `/vg:scope
--crossai` or `/vg:blueprint --crossai` apply changes:

- `git diff <base> -- PLAN.md CONTEXT.md` → captures enrichment delta.
- Per task: count added body lines (`+` lines inside `<task>` body,
  excluding frontmatter changes).
- BLOCK if any task body grew > 30 prose lines AND no corresponding
  `<context-refs>` ID added.
- WARN if `cross_ai_enriched: true` flag missing from CONTEXT.md
  frontmatter when any change made.
- Override flag: `--skip-crossai-output` (logs override-debt as
  `kind=crossai-output-relaxed`).
