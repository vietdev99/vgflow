# Holistic Socratic Audit — VGFlow v4.16.0
**Date:** 2026-05-13  
**Method:** Grep + Read (Codex consult failed: 401 Unauthorized — fallback audit)  
**Scope:** New gaps only — batches 1–13 + #185 + H13 excluded  
**Findings:** 12 new gaps

---

## Finding 1: `/vg:complete-milestone` Security Audit Step Is Print-Only — Not Executed

**Socratic question:** 2 (Execution) + 5 (Wrong wording)  
**File:line:** `commands/vg/complete-milestone.md:92–113`  
**Purpose claim:** Objective states: "Security audit — invokes `/vg:security-audit-milestone --milestone-gate` so decay + composite + Strix-advisory steps run with the milestone gate active."  
**Actual execution:**
```bash
${PYTHON_BIN:-python3} -c "
# Invoke via the standard slash command surface so all hooks/telemetry fire
print('  (delegating to /vg:security-audit-milestone --milestone-gate)')
" || true
echo "  Run: /vg:security-audit-milestone $AUDIT_ARGS"
```
The Python one-liner only **prints** the delegation message. It does not call `subprocess.run`, does not spawn any process, and does not actually invoke the security audit. The `echo "Run: ..."` line is advisory text, not execution. If the audit check is critical for milestone gate integrity, this step is silently a no-op.  
**Gap:** Prose says "invokes". Code only echoes. Security audit is never actually run during `complete-milestone` execution — human must manually run it after reading the echo.  
**Severity:** high  
**Proposed fix:** `commands/vg/complete-milestone.md` step `3_security_audit`: replace the Python print-only block with an actual invocation. Since slash commands cannot be spawned from bash directly, either (a) call the underlying Python script directly (`scripts/generate-strix-advisory.py --milestone-gate`) or (b) add an AI instruction block outside the `<step>` bash that reads `_shared` security audit refs, similar to how `build.md` delegates to wave refs.

---

## Finding 2: `/vg:complete-milestone` Has No `must_touch_markers` + No `run-start` → Stop Hook Bypassed

**Socratic question:** 4 (Skipped)  
**File:line:** `commands/vg/complete-milestone.md:1–14` (frontmatter), `scripts/hooks/vg-stop.sh:14–20`  
**Purpose claim:** Runtime contract verifies milestone close integrity via Stop hook. All major commands use `run-start` + `must_touch_markers` so the Stop hook can verify completion.  
**Actual execution:** `complete-milestone.md` frontmatter has `must_emit_telemetry` but **zero** `must_touch_markers` and **no** `vg-orchestrator run-start` call in any step. Stop hook line 14–20: `if [ ! -f "$run_file" ]; then ... exit 0`. Because run-start is never called, there is no `active-runs/{session}.json` file, so Stop hook exits immediately after the dream reminder — no contract validation, no marker check, no state-machine ordering check.  
**Gap:** A 6-step critical command (gate check, security audit, summary, archive, state advance, commit) is entirely invisible to the Stop hook. Any step can be silently skipped with zero enforcement.  
**Severity:** high  
**Proposed fix:** Add to `complete-milestone.md` step `1_telemetry_started`:
```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start vg:complete-milestone \
  "milestone-level" "${ARGUMENTS}" || true
```
And add `must_touch_markers: [0_args, 1_telemetry_started, 2_gate_check, 3_security_audit, 4_milestone_summary, 5_archive_phases, 6_finalize_state, 7_atomic_commit]` to the frontmatter runtime_contract. Each `<step>` block needs a `touch .vg/active-runs/.markers/<step>.done` line.

---

## Finding 3: Two PostToolUse Hook Scripts Exist but Are NOT Wired in `settings.json`

**Socratic question:** 4 (Skipped) + 6 (Redundancy in opposite direction — present but dead)  
**File:line:** `.claude/scripts/hooks/vg-post-tool-use-agent.sh` (exists), `.claude/scripts/hooks/vg-post-tool-use-askuserquestion.sh` (exists), `.claude/settings.json:3–12` (wires only `TodoWrite|TaskCreate|TaskUpdate`)  
**Purpose claim:**  
- `vg-post-tool-use-agent.sh`: "Issue #140 mitigation (git add -N intent-to-add) + v2.61.0 L2 post-wave reminder" — fires after Agent tool to mark new artifacts as git intent-to-add and remind AI to continue remaining steps.  
- `vg-post-tool-use-askuserquestion.sh`: "reminder so AI updates native task UI after user's answer before continuing workflow step."  
**Actual execution:** Both scripts exist and contain meaningful logic. Neither is referenced in `settings.json` PostToolUse hooks. Only `TodoWrite|TaskCreate|TaskUpdate` has a PostToolUse hook wired. The Agent and AskUserQuestion hooks are orphaned — they never fire.  
**Gap:** Issue #140 mitigation (git add -N) is declared but never executes. The L2 post-wave reminder never fires. The TaskUpdate-after-AskUserQuestion reminder never fires. These were presumably wired at some point (or planned to be), but the settings.json was not updated.  
**Severity:** medium  
**Proposed fix:** Add to `.claude/settings.json` PostToolUse array:
```json
{"matcher": "Agent", "hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/vg-run-bash-hook.py\" \"${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/vg-post-tool-use-agent.sh\""}]},
{"matcher": "AskUserQuestion", "hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/vg-run-bash-hook.py\" \"${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/vg-post-tool-use-askuserquestion.sh\""}]}
```

---

## Finding 4: `AskUserQuestion:` Used as Invalid Bash Syntax Inside `\`\`\`bash` Block in `/vg:design-scaffold` and `/vg:design-reverse`

**Socratic question:** 5 (Wrong wording)  
**File:line:** `commands/vg/design-scaffold.md:73`, `commands/vg/design-reverse.md:46`  
**Purpose claim:** Both commands list `AskUserQuestion` in `allowed-tools`. When DESIGN.md is missing (scaffold) or Playwright is missing (reverse), the AI should prompt the user interactively.  
**Actual execution:**
```bash
# design-scaffold.md line 73 — inside ```bash block:
AskUserQuestion: "Continue scaffold without DESIGN.md? [y/N]"
```
This is **invalid bash syntax** — `AskUserQuestion:` is a YAML-style label, not a shell command. When the AI reads this as bash to execute, the shell will fail (or silently interpret it as a no-op label). The AI may or may not recognize this as a tool call directive depending on how the instruction is interpreted.  
**Gap:** `design-scaffold.md` uses `AskUserQuestion:` inside a `\`\`\`bash` fenced block. Compare with `design-scaffold.md` step 6 which uses `\`\`\`` (no language tag) for `SlashCommand:` instructions — those are correctly in plain code blocks for AI directive use. The `AskUserQuestion:` call at line 73 is inside a `\`\`\`bash` block, mixing bash shell syntax with AI tool call directives. This is an inconsistency the AI must guess through.  
**Severity:** medium  
**Proposed fix:** Move the `AskUserQuestion:` line out of the `\`\`\`bash` block — either close the bash fence, insert the `AskUserQuestion:` tool call instruction as plain prose or in a plain `\`\`\`` block, then re-open bash for the `mkdir -p` line. Same fix in `design-reverse.md:46`.

---

## Finding 5: Eight Commands Missing `name:` Field in Frontmatter

**Socratic question:** 5 (Wrong wording) + 4 (Skipped)  
**File:line:** `commands/vg/meta-memory.md`, `commands/vg/lesson.md`, `commands/vg/bug-report.md`, `commands/vg/learn.md`, `commands/vg/design-system.md`, `commands/vg/rule.md`, `commands/vg/migrate-planning-vg.md`, `commands/vg/_review-visual-checks-insert.md`  
**Purpose claim:** Every slash command file should have a `name: vg:<command>` field in frontmatter. This field is used by the harness, sync scripts (`sync-vg-skills.py`), codex mirror generation, and the skill index for routing.  
**Actual execution:** All 8 listed files have `---` frontmatter but no `name:` field. Compare: `debug.md`, `roam.md`, `scope-review.md`, `test-spec.md` all have `name: vg:<x>`. The 8 missing commands are "real" user-facing commands (`/vg:learn`, `/vg:lesson`, `/vg:bug-report`, etc.) that lack canonical identity in their own frontmatter.  
**Gap:** Sync/mirror scripts that read `name:` will silently skip these 8 commands or produce unnamed entries. The codex-skills mirrors for these commands may be missing or stale.  
**Severity:** low  
**Proposed fix:** Add `name: vg:<command>` as first line of frontmatter in each of the 8 files. Example for `meta-memory.md`: insert `name: vg:meta-memory` before `runtime_contract:`.

---

## Finding 6: `/vg:debug` Spec-Gap Branch — `SlashCommand: /vg:amend` Inside `\`\`\`bash` Block

**Socratic question:** 5 (Wrong wording) + 2 (Execution)  
**File:line:** `commands/vg/_shared/debug/preflight.md:139`  
**Purpose claim:** `debug.md` rule 4 states: "Spec gap → auto /vg:amend — if classified as spec gap, auto-trigger `/vg:amend <phase>` (Q5=a)." The success_criteria confirms: "Spec gap → auto-routed to /vg:amend (if detected)."  
**Actual execution:**
```bash
# preflight.md line 139 — inside ```bash block:
# SlashCommand: /vg:amend ${PHASE_NUMBER}
```
The actual file shows:
```bash
- Write DEBUG-LOG note: "Classified as spec gap → auto-triggering /vg:amend"
- `SlashCommand: /vg:amend ${PHASE_NUMBER}` then exit cleanly
```
`SlashCommand:` is a YAML-like directive, not a bash command. However unlike Finding 4, this instance is in a bullet list (prose context, not inside a `\`\`\`bash` fence), so the AI may correctly interpret it as a tool call instruction. But `SlashCommand` is NOT listed in `debug.md`'s `allowed-tools` — the allowed tools are: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion, Task. `SlashCommand` is missing.  
**Gap:** `SlashCommand` not in `debug.md` allowed-tools. AI cannot invoke it. Spec-gap auto-routing to `/vg:amend` will fail silently or block at permission check when the AI attempts the SlashCommand tool call.  
**Severity:** medium  
**Proposed fix:** Add `SlashCommand` to `commands/vg/debug.md` allowed-tools list (alongside existing Task entry).

---

## Finding 7: `generate-deep-test-specs.py` AI Expansion Is Opt-In Manual — "Deepening" Does Not Auto-Invoke

**Socratic question:** 3 (Smoothness) + 2 (Execution)  
**File:line:** `scripts/generate-deep-test-specs.py:395,414`, `commands/vg/test-spec.md:4`  
**Purpose claim:** The script is called "deep test spec" and the `/vg:test-spec` command description says "Post-build deep test-spec authoring." The intent from the audit question is whether it deepens beyond what `generate-lifecycle-specs.py` produces.  
**Actual execution:** `generate-deep-test-specs.py` calls `lifecycle_module.generate(phase_dir)` (which IS `generate-lifecycle-specs.py`) to produce a fresh LIFECYCLE-SPECS.json from phase artifacts. Then `test_spec_ai_expander.py` is loaded. But the actual AI expansion (`expander.apply_expansion`) only runs if `args.ai_response` is provided:
```python
if args.ai_response:
    payload = expander.load_expansion_file(Path(args.ai_response))
    lifecycle, ai_expansion = expander.apply_expansion(lifecycle, payload)
```
Without `--ai-response`, the script produces the same deterministic lifecycle spec + execution plan that `generate-lifecycle-specs.py` alone would produce. The "deep" AI layer is entirely opt-in and requires the user to first generate an AI response file elsewhere, then pass it in.  
**Gap:** The AI expansion that makes "deep" specs actually deep is not auto-invoked. `/vg:test-spec` does prompt the AI to fill in the PROMPT.md and feed back an expansion (2-pass), but only in interactive mode. Non-interactive runs (CI, codex) produce the same output as the base lifecycle generator. The "deepening" claim is correct in interactive use, but the command name and description imply it always deepens.  
**Severity:** low  
**Proposed fix:** Add a note in `test-spec.md` and `generate-deep-test-specs.py` header that AI expansion deepening only activates in interactive mode (with `--ai-response`). Alternatively, add a `--no-ai-expansion` flag for explicit CI mode and make the 2-pass default.

---

## Finding 8: `/vg:meta-memory` — `meta_memory.mode_changed` Telemetry Fires on `status` Query (Semantic Mismatch)

**Socratic question:** 5 (Wrong wording) + 6 (Redundancy)  
**File:line:** `commands/vg/meta-memory.md:3–5` (runtime_contract), `scripts/vg-meta-memory-set.py:106–113`  
**Purpose claim:** `must_emit_telemetry` declares `event_type: "meta_memory.mode_changed"`. The event name implies a mode mutation occurred.  
**Actual execution:** `meta-memory.md` routes `status` → `--mode status` to `vg-meta-memory-set.py`. The script handles `status` as `cmd_status()` (read-only, no write). However the `runtime_contract.must_emit_telemetry` declares `meta_memory.mode_changed` for ALL invocations. If the orchestrator enforces this contract, it will expect a `mode_changed` event even when the user just runs `/vg:meta-memory status` — which reads and prints the current value without changing anything. A read-only query should not emit a "changed" event.  
**Gap:** Telemetry event name `mode_changed` semantically describes a mutation. The contract applies it to status queries too. This either causes spurious "changed" events in the telemetry trail, or causes a contract violation on status queries if the code emits nothing for read-only paths (since `vg-meta-memory-set.py` emits no telemetry at all).  
**Severity:** low  
**Proposed fix:** Split telemetry contract: `meta_memory.mode_changed` only for enable/disable/reflect-only subcommands (add `required_unless_flag` or condition). Add a separate optional `meta_memory.status_queried` for status. Or add `severity: "warn"` to the existing contract entry so status queries aren't failures.

---

## Finding 9: `dev-phases/18`, `19`, `20` — SPECS-Only Stubs with No Implementation or HANDOFF

**Socratic question:** 1 (Purpose) + 2 (Execution)  
**File:line:** `dev-phases/18-build-comprehension-gates-v1/` (BLUEPRINT.md, DECISIONS.md, ROADMAP-ENTRY.md, SPECS.md — no HANDOFF), `dev-phases/19-design-fidelity-95-pct-v1/` (RESEARCH.md, ROADMAP-ENTRY.md, SPECS.md), `dev-phases/20-design-scaffold-greenfield-v1/` (ROADMAP-ENTRY.md, SPECS.md only)  
**Purpose claim:** `dev-phases/` contains development phases that document planned or completed improvements to vgflow itself. Phases with HANDOFF.md are implemented. Phase 15 (design fidelity) and Phase 17 (test session reuse) have HANDOFF.md with implementation notes.  
**Actual execution:** Phases 18, 19, and 20 have only early-planning artifacts (SPECS.md, ROADMAP-ENTRY.md) — no BLUEPRINT.md in 19/20, no HANDOFF.md in any of the three. These are stale planning documents for improvements that were never executed. Phase 20 is specifically "design-scaffold-greenfield-v1" — the feature that was recently shipped as `/vg:design-scaffold`. The dev-phase stub predates or shadows the implementation but has no completed status marker.  
**Gap:** Three dev-phases are frozen in pre-implementation state. They create ambiguity about whether features are shipped (they are, separately) and clutter the dev-phases directory with stale planning artifacts that may mislead future contributors reading the repo history.  
**Severity:** low  
**Proposed fix:** Either (a) add a HANDOFF.md to 18/19/20 with `**Status:** SHIPPED` and a pointer to the CHANGELOG entry, or (b) move them to `dev-phases/archive/`. Phase 20 especially needs a SHIPPED note since `/vg:design-scaffold` exists at v4.16.0.

---

## Finding 10: `/vg:roam` Orphan Versioned Migration Scripts (9 scripts, 0–1 external callers)

**Socratic question:** 4 (Skipped) + 6 (Redundancy)  
**File:line:** `scripts/v272_slim_codex.py`, `scripts/v273_split_update.py`, `scripts/v2_72_split_migrate.py`, `scripts/v2_73_split_deploy.py`, `scripts/v273_t5_slim_codex_deploy.py`, `scripts/v273_t12_slim_codex_update.py`, `scripts/v274_split_scope_review.py`, `scripts/v274_t5_slim_codex_scope_review.py`, `scripts/v275_split_debug.py`, `scripts/v275_split_specs.py`, `scripts/v275_t5_slim_codex_specs.py`, `scripts/v275_t10_slim_codex_debug.py`, `scripts/v272_slim_codex.py` (also as untracked `scripts/v272_slim_codex.py`)  
**Purpose claim:** These are one-shot migration scripts run during specific version upgrades (v2.72–v2.75). After a migration is applied, the script is no longer needed.  
**Actual execution:** 0 external callers for most (self-reference only — each `vN_split_X.py` is referenced by the next `vN+1_split_Y.py` in a chain). None are referenced from commands, tests, CI, or CHANGELOG as "run this to upgrade." The `v272_slim_codex.py` also exists as an untracked file (git status shows `?? scripts/v272_slim_codex.py`) alongside the committed version — suggesting a re-authored copy was left untracked.  
**Gap:** 12+ versioned migration scripts occupy `scripts/` permanently after their one-shot run. The untracked `v272_slim_codex.py` is a stale working copy that was never committed or deleted. These create noise when searching scripts/ for active callers.  
**Severity:** low  
**Proposed fix:** Move all `vN_*` and `vN.M_*` scripts to `scripts/migrations/` or `scripts/archive/` after verifying they have been run. Delete the untracked `scripts/v272_slim_codex.py` (it's already committed as `scripts/v272_slim_codex.py`... or confirm it's a different version and commit/discard accordingly).

---

## Finding 11: `/vg:scope-review` — Incremental Baseline Early-Exit Does NOT Write Updated Baseline Timestamp

**Socratic question:** 2 (Execution) + 3 (Smoothness)  
**File:line:** `commands/vg/_shared/scope-review/preflight.md:167–178`  
**Purpose claim:** "Early-exit optimization: still emit telemetry + skip to baseline rewrite" — the comment says the baseline timestamp should be bumped on early-exit (no-change case).  
**Actual execution:**
```bash
if [ "$CHANGED_COUNT" = "0" ] && [ "$NEW_COUNT" = "0" ] && [ "$REMOVED_COUNT" = "0" ]; then
  echo "✓ No phases changed since ${BASELINE_TS}. Scope-review is already current."
  echo "  Use --full to force rescan."
  type emit_telemetry_v2 >/dev/null 2>&1 && \
    emit_telemetry_v2 "gate_hit" ...
  # Still refresh baseline timestamp, then exit.
  # (baseline hashes unchanged; just bump ts)
  exit 0
fi
```
The comment says "Still refresh baseline timestamp, then exit" but the actual code immediately calls `exit 0` **without** executing any baseline write. The baseline JSON (`${PLANNING_DIR}/.scope-review-baseline.json`) retains the old `ts` from the previous run. On the NEXT scope-review run, the `BASELINE_TS` will still show the stale timestamp, making the "No phases changed since ..." message show an increasingly old date even though scope-review runs successfully.  
**Gap:** The baseline `ts` is documented as "bumped" on early-exit but the code exits before any write occurs. Over multiple no-change runs, the displayed "last checked" timestamp drifts further into the past, potentially causing user confusion about whether scope-review is being checked.  
**Severity:** medium  
**Proposed fix:** Before `exit 0` in the early-exit block, add a baseline timestamp update:
```bash
python3 -c "
import json, datetime
from pathlib import Path
p = Path('${BASELINE_PATH}')
if p.exists():
    d = json.loads(p.read_text())
    d['ts'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2))
"
```

---

## Finding 12: `/vg:roam` Post-Roam Reflector Trigger — `phase.roam_completed` Event Never Emitted by Any Roam Step

**Socratic question:** 4 (Skipped) + 5 (Wrong wording)  
**File:line:** `commands/vg/roam.md:250–265`  
**Purpose claim:** "After `phase.roam_completed` emits, spawn vg-reflector subagent IF `meta_memory_mode != 'disabled'`."  
**Actual execution:** The roam close step (`_shared/roam/close.md`) emits `roam.session.completed` (as declared in `must_emit_telemetry`). The reflector spawn code checks `$EVENT_TYPE = "phase.roam_completed"`. These are two different event names: `roam.session.completed` (what close emits) vs `phase.roam_completed` (what the reflector trigger checks). Neither the roam runtime_contract nor `close.md` declares or emits an event named `phase.roam_completed`.  
```bash
# roam.md line 252-253:
if [ "$META_MEMORY_MODE" != "disabled" ] && [ "$EVENT_TYPE" = "phase.roam_completed" ]; then
  # spawns reflector
fi
```
`$EVENT_TYPE` in this context is never set to `phase.roam_completed` because no step emits it. The reflector spawn block will never execute regardless of `meta_memory_mode` setting.  
**Gap:** Post-roam reflector is entirely dead code. The event name mismatch means meta-memory's highest-signal input (roam findings → reflector) never fires. This also means the `reflection.trigger_requested` telemetry event (line 256) is never emitted.  
**Severity:** high  
**Proposed fix:** In `commands/vg/_shared/roam/close.md`, after emitting `roam.session.completed`, additionally emit `phase.roam_completed`:
```bash
vg-orchestrator emit-event "phase.roam_completed" --actor "roam" --outcome "INFO" \
  --metadata "{\"phase\":\"${PHASE_NUMBER}\"}"
```
Or, simpler: change the reflector trigger condition to check `$EVENT_TYPE = "roam.session.completed"` (match what close.md actually emits).

---

## Summary Table

| # | Title | Severity |
|---|---|---|
| 1 | complete-milestone security audit step is print-only | **high** |
| 2 | complete-milestone has no must_touch_markers + no run-start → Stop hook bypassed | **high** |
| 3 | Two PostToolUse hook scripts exist but not wired in settings.json | **medium** |
| 4 | AskUserQuestion: invalid bash syntax in design-scaffold + design-reverse | **medium** |
| 5 | Eight commands missing name: field in frontmatter | **low** |
| 6 | debug spec-gap branch: SlashCommand not in allowed-tools | **medium** |
| 7 | generate-deep-test-specs AI expansion is opt-in manual, not auto-deepening | **low** |
| 8 | meta-memory: mode_changed telemetry fires on read-only status query | **low** |
| 9 | dev-phases 18/19/20 are stale SPECS-only stubs, never marked SHIPPED | **low** |
| 10 | 12+ versioned migration scripts are orphans in scripts/ (incl. untracked duplicate) | **low** |
| 11 | scope-review incremental early-exit does NOT bump baseline timestamp | **medium** |
| 12 | roam post-roam reflector trigger checks event name that is never emitted | **high** |

---

## Top 5 Priority Recommendations

### P1 — Fix `/vg:complete-milestone` Hook Bypass (Findings 1 + 2)
Two linked issues make the milestone close command unverifiable. Security audit is never invoked (Finding 1) and the Stop hook exits immediately because run-start is missing (Finding 2). This is a critical trust gap: milestones can be "closed" without security audit and without any contract verification. Fix both in the same PR.

### P2 — Wire Orphaned PostToolUse Hooks (Finding 3)
`vg-post-tool-use-agent.sh` (Issue #140 + L2 reminder) and `vg-post-tool-use-askuserquestion.sh` (TaskUpdate reminder) are carefully crafted but never fire. Adding two entries to `settings.json` activates both. Especially `vg-post-tool-use-agent.sh` is high-value: it prevents silent artifact loss via `git add -N` intent-tracking.

### P3 — Fix Roam Post-Roam Reflector Event Name Mismatch (Finding 12)
Meta-memory's highest-signal path (roam findings → reflector candidates) is completely dead due to a single event name mismatch (`roam.session.completed` vs `phase.roam_completed`). One-line fix in `close.md`. Unlocks the full meta-memory feedback loop for all users who have `inject-as-advice` mode enabled.

### P4 — Fix `SlashCommand` Missing from debug Allowed-Tools (Finding 6)
Spec-gap auto-routing to `/vg:amend` is a documented and tested feature of `/vg:debug`. Without `SlashCommand` in the allowed-tools list, the AI will be blocked at permission check when it attempts the tool call. One-line fix in `debug.md` frontmatter.

### P5 — Fix `scope-review` Incremental Baseline Timestamp (Finding 11)
The early-exit path in `scope-review` promises to bump the baseline timestamp but doesn't. After N consecutive no-change runs, the "last checked" timestamp shown to users becomes weeks old despite the tool running correctly. Medium-severity UX issue for teams with large phase counts that rarely change.

---

## Smoothness Verdicts

| Stage | Verdict | Note |
|---|---|---|
| specs → scope | **PASS** | Scope and scope-review flow is clean. Incremental delta scan is well-designed. Minor issue: baseline ts not bumped on no-change exit (Finding 11) causes stale display but no functional breakage. |
| blueprint → build | **NEEDS-WORK** | Design pipeline has `AskUserQuestion:` syntax issue inside bash block (Finding 4) which can cause unpredictable AI behavior in design-scaffold. SlashCommand in step 6 is in a plain code block (OK), but the overall design → extract → blueprint handoff documentation is implicit (design-scaffold says "Next: /vg:blueprint" which skips the explicit design-extract step). |
| build → test | **PASS** | test-spec lane is well-wired with strict runtime_contract, markers, telemetry. The AI expansion opt-in limitation (Finding 7) is a documentation gap not a wiring failure. |
| test → accept | **PASS** | Test → accept flow has strong contract verification. vg:roam post-confirmation gate is well-enforced. The reflector trigger event mismatch (Finding 12) is a meta-memory concern, not a functional gate concern. |
| overall idea → ship autonomous flow | **NEEDS-WORK** | Two critical gaps break the autonomous guarantee: (1) `/vg:complete-milestone` Stop hook bypass means milestone closeout has zero contract enforcement — a ship gate silently has no gates; (2) orphaned PostToolUse hooks mean subagent artifact tracking (Issue #140 intent-to-add) and TaskUpdate-after-decision reminders never fire, reducing autonomous observability. The pipeline is functionally correct for human-supervised use but has enforcement gaps at the autonomous end. |
