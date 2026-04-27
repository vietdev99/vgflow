---
name: vg-crossai
description: Shared CrossAI engine for VG pipeline — spawns configured CLI agents (0-N from vg.config.md) for parallel review, verification, and test execution
user-invocable: false
---

# VG CrossAI Engine

Shared engine called internally by `/vg:*` commands. This skill is NOT invoked directly by the user — it provides the cross-AI orchestration layer that other VG commands delegate to when they need multi-CLI verification, review, or test execution.

The engine spawns 3 external CLI agents in parallel, collects their outputs, builds consensus, and returns structured XML results to the calling skill.

<modes>

## Modes

### `review-light`
- **Called by:** /rtb:discuss, /rtb:plan, /rtb:test-specs
- **Statefulness:** Stateless
- **Purpose:** Quick review of artifacts (plans, specs, discussion summaries). Each CLI gets the artifact text and a focused prompt. Results are collected and merged into a single consensus. No files are persisted beyond /tmp.

### `total-check`
- **Called by:** /rtb:crossai-check
- **Statefulness:** Stateless
- **Purpose:** Full quality gate. Reads the entire `.vg/phases/{X}/` directory — all plans, specs, context, and code references. Each CLI performs a comprehensive audit covering correctness, completeness, consistency, and architectural alignment. This is the heaviest mode and should only be triggered explicitly.

### `execute-verify`
- **Called by:** /rtb:execute after each wave
- **Statefulness:** Session-based — writes to `crossai/execute-verify-{wave}.xml`
- **Purpose:** Verifies code produced by each execution wave. Each CLI reviews the diff, checks against the plan, and flags deviations. Results accumulate across waves so the final report shows the full execution trajectory.

### `test-generate`
- **Called by:** /rtb:sandbox-test step 6
- **Statefulness:** Session-based — generates Playwright E2E test code from specs
- **Purpose:** Each CLI independently generates Playwright test code from TEST-SPEC.md. The engine then cross-references the 3 outputs, picks the best implementation per test case, and merges into a final test suite. Disputed approaches are flagged for human review.

### `test-run`
- **Called by:** /rtb:sandbox-test step 7
- **Statefulness:** Session-based — accumulates results across fix loops
- **Purpose:** Runs generated E2E tests on VPS, collects pass/fail results. On failure, each CLI proposes a fix. The engine picks the consensus fix and applies it. Results accumulate across fix loop iterations (max 3) so the final report shows the full fix history.

</modes>

<xml_output_format>

## XML Output Format

All modes produce output conforming to this schema:

```xml
<crossai_review>
  <meta>
    <mode>{mode}</mode>
    <phase>{phase_number}</phase>
    <timestamp>{ISO-8601}</timestamp>
    <session_dir>{path to crossai/ folder if session-based, "none" if stateless}</session_dir>
  </meta>
  <results>
    <cli source="codex" model="configured">
      <verdict>pass|flag|block</verdict>
      <score>{1-10}</score>
      <findings>
        <finding severity="critical|major|minor">
          <description>{what's wrong}</description>
          <location>{file:line or artifact:section}</location>
          <suggestion>{how to fix}</suggestion>
        </finding>
      </findings>
    </cli>
    <cli source="gemini" model="pro-high-3.1">
      <verdict>pass|flag|block</verdict>
      <score>{1-10}</score>
      <findings>
        <finding severity="critical|major|minor">
          <description>{what's wrong}</description>
          <location>{file:line or artifact:section}</location>
          <suggestion>{how to fix}</suggestion>
        </finding>
      </findings>
    </cli>
    <cli source="claude" model="sonnet-4.6">
      <verdict>pass|flag|block</verdict>
      <score>{1-10}</score>
      <findings>
        <finding severity="critical|major|minor">
          <description>{what's wrong}</description>
          <location>{file:line or artifact:section}</location>
          <suggestion>{how to fix}</suggestion>
        </finding>
      </findings>
    </cli>
  </results>
  <consensus>
    <overall_verdict>pass|flag|block</overall_verdict>
    <average_score>{float}</average_score>
    <agreed_findings><!-- findings where 2+ CLIs agree --></agreed_findings>
    <disputed_findings><!-- findings where CLIs disagree — escalate to major --></disputed_findings>
    <auto_fixed><fix description="{what}" file="{path}" /></auto_fixed>
    <needs_human><issue description="{what}" severity="{level}" cli_sources="{who flagged}" /></needs_human>
  </consensus>
</crossai_review>
```

</xml_output_format>

<spawn_commands>

## Spawn Commands

Verified CLI commands for spawning each agent. Tested 2026-04-10 (codex 0.118.0, gemini 0.36.0, claude 2.1.98).

### Individual CLI Commands

**Codex (configured model):**
```bash
codex exec "$(cat {context_file})" > {output_path} 2>&1 &
```

**Gemini (Pro High 3.1):**
```bash
cat {context_file} | gemini -m gemini-2.5-pro -p "{prompt}" --yolo > {output_path} 2>&1 &
```

**Claude (Sonnet 4.6):**
```bash
cat {context_file} | claude --model sonnet -p "{prompt}" > {output_path} 2>&1 &
```

### Parallel Spawn Pattern

```bash
# Prepare context file
CONTEXT_FILE="/tmp/vg-crossai-${PHASE}-${MODE}-context.md"
OUTPUT_DIR="/tmp/vg-crossai-${PHASE}-${MODE}"
mkdir -p "$OUTPUT_DIR"

# Spawn all 3 CLIs in parallel
codex exec "$(cat $CONTEXT_FILE)" > "$OUTPUT_DIR/codex.out" 2>&1 &
PID_CODEX=$!

cat "$CONTEXT_FILE" | gemini -m gemini-2.5-pro -p "$PROMPT" --yolo > "$OUTPUT_DIR/gemini.out" 2>&1 &
PID_GEMINI=$!

cat "$CONTEXT_FILE" | claude --model sonnet -p "$PROMPT" > "$OUTPUT_DIR/claude.out" 2>&1 &
PID_CLAUDE=$!

# Wait for all to complete
wait $PID_CODEX $PID_GEMINI $PID_CLAUDE

# Collect results
echo "Codex exit: $?"
cat "$OUTPUT_DIR/codex.out"
cat "$OUTPUT_DIR/gemini.out"
cat "$OUTPUT_DIR/claude.out"
```

</spawn_commands>

<severity_routing>

## Severity Routing

### Severity Levels

| Severity | Action | Where Logged |
|----------|--------|-------------|
| **minor** | Auto-fix immediately, no user intervention | `<auto_fixed>` in consensus |
| **major** | Block progress, show to user, ask: fix / defer / re-discuss | `<needs_human>` in consensus |
| **critical** | Hard block, user MUST resolve before proceeding | `<needs_human>` with severity="critical" |

### Consensus Rules

- **2/3 CLIs agree** → use that severity level
- **3-way split** (all different) → escalate to **major**
- **Any single CLI says critical** → treat as **critical** regardless of other CLIs
- **All 3 say pass** → pass with no findings
- **Disputed findings** (CLIs disagree on existence or severity) → escalate to **major**, log in `<disputed_findings>`

</severity_routing>

<context_management>

## Context Management

### Stateless Modes (review-light, total-check)

- Write context to `/tmp/vg-crossai-{phase}-{mode}.md`
- Write CLI outputs to `/tmp/vg-crossai-{phase}-{mode}/`
- Parse outputs, build consensus XML, return to calling skill
- Clean up all `/tmp/vg-crossai-*` files after consensus is built
- No persistent artifacts — the calling skill decides what to save

### Session-Based Modes (execute-verify, test-generate, test-run)

- Write context and outputs to `.vg/phases/{X}/crossai/`
- File naming:
  - `execute-verify-{wave}.xml` — one file per execution wave
  - `test-generate.xml` — merged test suite with per-CLI attribution
  - `test-run-{iteration}.xml` — one file per fix loop iteration
- Keep all files for the next iteration (accumulated state)
- At session end, generate `CROSSAI-REPORT.md` summarizing:
  - Total findings across all iterations
  - Auto-fixed vs human-resolved breakdown
  - Final consensus verdict and score
  - Timeline of iterations with key events

</context_management>
