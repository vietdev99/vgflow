---
name: vg:progress
description: Show detailed pipeline progress across all phases — artifact status, current step, next action
argument-hint: "[phase] [--all]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
---

<objective>
Show detailed progress dashboard for the VG pipeline. Without arguments, shows current phase + overview of all phases. With a phase argument, shows deep detail for that phase.

Pipeline steps: specs → scope → blueprint → build → review → test → accept
</objective>

<process>

<step name="0_load_config">
Read .claude/commands/vg/_shared/config-loader.md first.
</step>

<step name="0b_version_banner">
Show VG version + update availability. Daily cache to avoid hammering GitHub API (60/hr unauth quota).

```bash
VGFLOW_VERSION=$(cat .claude/VGFLOW-VERSION 2>/dev/null | tr -d '[:space:]' || echo "unknown")
CACHE_DIR=".cache"
CACHE_FILE="${CACHE_DIR}/vgflow-latest-check.json"
mkdir -p "$CACHE_DIR" 2>/dev/null || true

# Refresh cache if older than 1 day (or missing). Don't fail banner on network error.
if [ ! -f "$CACHE_FILE" ] || [ -n "$(find "$CACHE_FILE" -mtime +1 2>/dev/null)" ]; then
  if [ -f ".claude/scripts/vg_update.py" ]; then
    timeout 3 python3 .claude/scripts/vg_update.py check --repo "vietdev99/vgflow" > "$CACHE_FILE" 2>/dev/null || true
  fi
fi

LATEST=$(grep -oE 'latest=[^ ]+' "$CACHE_FILE" 2>/dev/null | cut -d= -f2)

if [ -n "$LATEST" ] && [ "$LATEST" != "unknown" ] && [ "$LATEST" != "$VGFLOW_VERSION" ]; then
  echo "VG v${VGFLOW_VERSION} (latest v${LATEST} available — run /vg:update)"
else
  echo "VG v${VGFLOW_VERSION}"
fi
echo ""
```

Gracefully degrades: no VGFLOW-VERSION → "VG vunknown"; offline → no update hint (cached or nothing).
</step>

<step name="1_scan_phases">
**Deterministic scan via script — DO NOT self-scan.**

LLM self-scanning across many phases is error-prone (hallucinated counts, missed
verdict formats). Progress uses a Python script as the single source of truth.

```bash
SCAN_JSON=$(${PYTHON_BIN} "${REPO_ROOT}/.claude/scripts/vg-progress.py" \
  --planning "${PLANNING_DIR}" --output json 2>&1)

if [ $? -ne 0 ]; then
  echo "⛔ vg-progress.py failed. Falling back to artifact check — results may be stale."
fi
```

The script returns JSON:
```json
{
  "current_phase_from_state": "07.8",
  "phase_count": 33,
  "phases": [
    {
      "phase": "07.7",
      "name": "07.7-inventory-floor-pricing-engine",
      "label": "DONE",
      "done_count": 7,
      "total_steps": 7,
      "current_step": null,
      "next_command": "—",
      "steps": {
        "specs": {"status": "done", "icon": "✅", "source": "artifact"},
        "scope": {"status": "done", "icon": "✅", "source": "artifact"},
        "blueprint": {"status": "done", "icon": "✅", "source": "artifact"},
        "build": {"status": "done", "icon": "✅", "source": "artifact"},
        "review": {"status": "done", "icon": "✅", "source": "artifact"},
        "test": {"status": "done", "icon": "✅", "source": "artifact"},
        "accept": {"status": "done", "icon": "✅", "source": "artifact"}
      },
      "content": {
        "sandbox": "PASSED",
        "uat": "ACCEPTED",
        "matrix": {"ready": 36, "blocked": 0, "unreachable": 0, "gate": "PASS"}
      },
      "artifacts": {...},
      "pipeline_state": null
    }
  ]
}
```

Key fields to render in Step 3:
- `label` — overall status (DONE | BLOCKED | IN_PROGRESS | NOT_STARTED)
- `done_count/total_steps` — "6/7" in header
- `steps[*].icon` — pipeline string
- `next_command` — exact command to suggest (already includes phase number)
- `content.sandbox`, `content.uat`, `content.matrix` — for detail view

**Detection rules the script enforces** (so renderer trusts them):
1. **PIPELINE-STATE.json** is authoritative — script reads it first, falls back to artifacts only if missing.
2. **UAT verdict** parsing handles all seen formats: `**Verdict:** ACCEPTED`,
   `## Verdict: PASSED`, `status: complete`, YAML frontmatter prioritized over
   per-test `status:` lines deeper in file.
3. **Monotonic invariant** — if step N is done, all steps < N are promoted to
   done with `source: "inferred"`. Prevents false BLOCKED when review matrix
   has an unusual format but UAT has already accepted the phase.
4. **Matrix gate** — `Ready: X | Blocked: Y | Unreachable: Z` parsed deterministically.
   FAIL only when Blocked+Unreachable > 0 AND UAT hasn't accepted downstream.
</step>

<step name="2_identify_current">
**Determine active phase:**

Read `${PLANNING_DIR}/STATE.md` (if exists) for `current_phase`.
If STATE.md missing → active phase = first phase with step < 7.
If all phases done → show milestone completion.
</step>

<step name="3_display_overview">
**Display multi-phase dashboard — one pipeline block per phase.**

For EACH phase in ${PHASES_DIR} (sorted numerically), render this block:

```
────────────────────────────────────────────────────────────────
Phase {N}: {name}   [{step}/7]   {status_label}

Pipeline: {s0} specs → {s1} scope → {s2} blueprint → {s3} build → {s4} review → {s5} test → {s6} accept

Next: {next_command_or_dash}
────────────────────────────────────────────────────────────────
```

**IMPORTANT — use the inline format above, NOT a separate "Status:" row.**

Why: status icons on their own line don't align with step names (different widths: "specs"=5 chars, "blueprint"=9 chars, "test"=4 chars). Inline format puts each icon directly next to its step name — no alignment issues.

Example rendered output:
```
Pipeline: ✅ specs → ✅ scope → ✅ blueprint → ✅ build → 🔄 review → ⬜ test → ⬜ accept
```

**Status icon per step (computed from artifacts):**

| Step | Icon logic |
|------|-----------|
| 0 (specs)     | ✅ if SPECS.md exists, else ⬜ |
| 1 (scope)     | ✅ if CONTEXT.md exists, else ⬜ (🔄 if SPECS exists but no CONTEXT = currently here) |
| 2 (blueprint) | ✅ if PLAN*.md + API-CONTRACTS.md exist, 🔄 if partial, ⬜ if none |
| 3 (build)     | ✅ if SUMMARY*.md exists, ⬜ otherwise |
| 4 (review)    | ✅ if RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX gate=PASS, 🔄 if RUNTIME exists but gate BLOCK, ❌ if gate=FAILED, ⬜ if no RUNTIME-MAP |
| 5 (test)      | ✅ if *-SANDBOX-TEST.md exists + verdict=PASSED, 🔄 if GAPS_FOUND, ❌ if FAILED, ⬜ if missing |
| 6 (accept)    | ✅ if *-UAT.md exists + verdict=ACCEPTED, ⬜ otherwise |

**In-progress detection (🔄):** the FIRST step that isn't ✅ and has partial work = currently active step for that phase. Exactly one step per phase can be 🔄.

**status_label:**
- `✅ DONE` if all 7 steps ✅
- `🔄 IN PROGRESS` if any 🔄
- `⏸ NOT STARTED` if step 0 is ⬜
- `❌ BLOCKED` if any ❌

**next_command:** use Step 5 mapping table (what command moves phase forward). `—` if DONE.

**Rendering rules:**
- Print blocks TOP-DOWN in phase-number order
- Do NOT collapse into a single table — each phase gets its own visual block so user can scan progress at a glance
- Include ALL phases from ROADMAP.md, even ones with step 0/7 (shows upcoming work)
</step>

<step name="4_display_detail">
**Show artifact detail — ONLY if `$ARGUMENTS` contains a specific phase number.**

Without a phase argument: Step 3's per-phase blocks are enough. Skip this step entirely.
With a phase argument: print this extra block AFTER the phase's overview block.

For the requested phase, show artifact detail:

```
### Phase {N}: {name}

Pipeline: ✅ specs → ✅ scope → ✅ blueprint → ✅ build → 🔄 review → ⬜ test → ⬜ accept

#### Artifacts
| Step | Artifact | Status | Detail |
|------|----------|--------|--------|
| 0 | SPECS.md | ✅ | Created |
| 1 | CONTEXT.md | ✅ | {N} decisions (D-01..D-{N}) |
| 2 | PLAN*.md | ✅ | {N} plans |
| 2 | API-CONTRACTS.md | ✅ | {N} endpoints |
| 2 | TEST-GOALS.md | ✅ | {N} goals ({critical}/{important}/{nice}) |
| 3 | SUMMARY*.md | ✅ | {N} summaries |
| 4 | RUNTIME-MAP.json | 🔄 | {N} views, {M} elements, {coverage}% |
| 4 | GOAL-COVERAGE-MATRIX.md | 🔄 | {ready}/{total} goals ready |
| 4 | scan-*.json | — | {N} Haiku scan results |
| 4 | probe-*.json | — | {N} probe results |
| 5 | SANDBOX-TEST.md | ⬜ | Not started |
| 6 | UAT.md | ⬜ | Not started |

#### CrossAI
- Results: {N} XML files in crossai/
- Latest: {filename} ({date})

#### Git Activity
- Recent commits: `git log --oneline -5 -- {phase_dir}`
- Files changed: `git diff --stat HEAD~10 -- apps/ packages/ | head -5`
```

**Status icons:**
- ✅ = complete (artifact exists and valid)
- 🔄 = in progress (artifact exists but phase not done)
- ⬜ = not started
- ❌ = failed/blocked
</step>

<step name="5_suggest_next">
**Suggest next action — ALWAYS use /vg:* commands. NEVER suggest /gsd-* or /gsd:* commands.**

**Step-to-command mapping (MANDATORY):**

| Current step (missing artifact) | Command to suggest |
|---|---|
| 0 (no SPECS.md) | `/vg:specs {phase}` |
| 1 (no CONTEXT.md) | `/vg:scope {phase}` |
| 2 (no PLAN*.md or API-CONTRACTS.md) | `/vg:blueprint {phase}` |
| 3 (no SUMMARY*.md) | `/vg:build {phase}` |
| 3b (SUMMARY exists, goals UNREACHABLE after review) | `/vg:build {phase} --gaps-only` |
| 4 (no RUNTIME-MAP.json) | `/vg:review {phase}` |
| 4b (gate BLOCK, goals failed) | `/vg:next {phase}` — auto-classifies UNREACHABLE vs BLOCKED |
| 5 (no SANDBOX-TEST.md) | `/vg:test {phase}` |
| 5b (test found gaps, need deeper UAT) | `/vg:test {phase}` or `/vg:accept {phase}` |
| 6 (no UAT.md or UAT incomplete) | `/vg:accept {phase}` |
| 7 (UAT complete, next phase exists) | `/vg:scope {next_phase}` after `/vg:specs {next_phase}` |
| 7 (all phases done) | `/vg:project --milestone` (milestone wrap-up — VG-native) |

**Output format:**

```
#### What's Next

▶ `{command from table above}` — {one-line description tied to actual phase state}

Also available:
  - `/vg:phase {phase} --from={step}` — run remaining pipeline
  - `/vg:next` — auto-advance (runs immediately, handles BLOCK/UNREACHABLE routing)
  - `/vg:progress {phase}` — detail for specific phase
```

**Forbidden suggestions (common AI mistake — do NOT emit these):**
- ❌ `/gsd-plan-phase` → use `/vg:blueprint` instead
- ❌ `/gsd-verify-work` → use `/vg:test` or `/vg:accept` instead
- ❌ `/gsd-discuss-phase` → use `/vg:scope` instead
- ❌ `/gsd-execute-phase` → use `/vg:build` instead

If `$ARGUMENTS` contains a specific phase, show detail for that phase only.
If `$ARGUMENTS` contains `--all`, show detail for ALL phases (not just active).
</step>

</process>

<success_criteria>
- All phase directories scanned
- Artifact status accurately detected
- Progress bar visually clear
- Active phase identified
- Next action suggested (not auto-invoked)
- Works with both VG and cross-referenced RTB phases
</success_criteria>
