# VG Token Audit Findings (2026-05-04)

**Trigger:** sếp Dũng dogfood `/vg:build 4.2 + /vg:accept 4.1` token spike.

**Auditors:** Claude Explore agent + Codex CLI gpt-5.5 (cross-AI verification).

**Status:** Findings recorded. Implementation tracked in plans below.

---

## Root cause of the original spike (events.db evidence)

The build/accept token spike sếp observed was **NOT** caused by ref size — it was caused by retry loops:

- `/vg:accept 4.1` ran **4 times in session** with 2× `run.blocked` + 2× `run.aborted`. Block reason: 14 markers + 3 telemetry events missing — exactly the Bug D pattern (`accept.tasklist_shown`, `accept.native_tasklist_projected`, `accept.completed` all = 0).
- `/vg:build 4.2` ran **3 times in session**, all aborted with cross-run conflict ("stale vg:accept 4.1 session >30min").
- Each attempt = main agent re-loads slim entry + preflight + gates.md + validator outputs.
- **~7 attempts × ~3-5K tokens/attempt ≈ 25-35K tokens wasted in retry loop.**

**The Bug D fix** (commits `87530d3`, `abc27cc`) **directly addresses this** — universal Stop-hook gate prevents the "miss telemetry → block → retry" cycle.

Subsequent sessions should not hit this spike pattern.

---

## Auditor agreement on structural hotspots (independent of retry loop)

| # | Hotspot | Claude rank | Codex rank | Verdict |
|---|---|---|---|---|
| 1 | `waves-overview.md` (1364 lines, multiplied per-wave) | Tier 1 | Priority 1 | **Both confirm** |
| 2 | `post-execution-overview.md` (1023 lines) | Tier 1 | Hotspot 4 | **Both confirm** |
| 3 | Slim-entry boilerplate (Red Flags + HARD-GATE per cmd) | Tier 2 | #7 (low-med) | One-time cost, not spike source |
| 4 | Hook stderr verbosity (mid-flow context, block messages) | Tier 2 | #6 (med) | **Both confirm** |
| 5 | `accept/gates.md` (641 lines) | Tier 1 | (not flagged) | Codex doesn't agree — F3-r2 design note explicitly keeps it monolithic to avoid duplicate `block-resolver/override-debt/rationalization-guard` sourcing across 5 split files. **Skip.** |

## Auditor disagreement (Codex finding only)

### Codex Priority 1 — Per-task capsule double-load (HIGH severity)

**Path:** `commands/vg/_shared/build/waves-overview.md:392` (Step 7: Materialize per-task capsules)
**Multiplier:** task count per wave × wave count. Phase 4.2 = 26 tasks → 26× per build.

**Mechanism:**
1. Main agent runs `pre-executor-check.py --capsule-out` → writes JSON capsule to `${PHASE_DIR}/.task-capsules/task-${N}.capsule.json` on disk.
2. Main agent then **parses the capsule JSON via 8 Python one-liners** (lines 422-432) into bash variables: `$TASK_CONTEXT`, `$CONTRACT_CONTEXT`, `$GOALS_CONTEXT`, `$TASK_CONTEXT_CAPSULE` (= `json.dumps(...)` literal expansion), `$TASK_SIBLINGS`, `$TASK_CALLERS`, `$DESIGN_CONTEXT`, `$BUILD_CONFIG`.
3. These bash vars get substituted into the Agent() prompt template (`waves-delegation.md`) — the **literal capsule content flows through main-agent context** even though the prompt also has `@${capsule_path}` path-reference for the subagent.
4. Subagent then reads `@${capsule_path}` from disk → re-loads same content from disk to its own context.

**Total cost:** main agent literal capsule materialization + render + persist + subagent disk re-read = same content traverses agent context twice per task.

**Estimated savings:** 5-10K tokens per build (varies by task count). Codex assessment: **HIGH**.

**Proposed fix:**
- Prompt template carries only `${capsule_path}` + `${capsule_sha256}` (compact, ~100 chars).
- Drop the bash-var-substitution Python one-liners (lines 422-432). Subagent reads `@${capsule_path}` directly via Claude Code's `@` include semantics — content stays out of main agent context.
- vg-agent-spawn-guard.py validates `capsule_path` exists on disk + sha256 matches manifest, instead of validating literal JSON in prompt.
- Side benefit: smaller prompt envelope helps subagent context budget too.

**Implementation tracking:** see `docs/superpowers/plans/2026-05-04-vg-capsule-injection-fix.md` (TBD).

---

### Codex Priority 3 — Workflow context per-task duplication (MED-HIGH)

**Path:** `commands/vg/_shared/build/waves-delegation.md:197-218` + `scripts/generate_wave_context.py:124`
**Multiplier:** workflow-bound task count per wave.

**Mechanism:** Same `WORKFLOW-SPECS/WF-NN.md` content (~500 tokens/file) embedded in every workflow-bound task's prompt via `${WORKFLOW_SLICE_BLOCK}` substitution. Phases with 5 workflow tasks sharing 1 workflow spec inject the same content 5×.

**Estimated savings:** 300-500 tokens per workflow-heavy phase. Codex assessment: **MED-HIGH**.

**Proposed fix:**
- Move workflow context load to `commands/vg/_shared/build/context.md` (STEP 2, runs once before waves).
- Emit `wave-${N}-workflow-context.json` per wave (pre-computed, cached).
- Delegation template references the per-wave file via `@${wave_workflow_context_path}`, not per-task substitution.
- Subagent reads wave-level summary, not full workflow spec, unless its `state_after` mismatches wave summary (rare).

**Implementation tracking:** see `docs/superpowers/plans/2026-05-04-vg-workflow-context-dedup.md` (TBD).

---

### Codex Priority 5 — Accept UAT batching + hook reminder suppression (HIGH)

**Path:** `commands/vg/_shared/accept/uat/interactive.md:4` + `scripts/hooks/vg-user-prompt-submit.sh:38`
**Multiplier:** AskUserQuestion turn count (50+ per accept run).

**Mechanism:** Each user reply to AskUserQuestion fires `vg-user-prompt-submit.sh` which injects `<vg-flow-context>` reminder via stderr (re-injected as system-reminder to AI). 50 turns × 17-line reminder = ~850 lines of repeated prose injected per accept session. Reminder is identical when state hasn't changed.

**Proposed fix:**
- Suppress reminder injection when `tasklist_projected_at` mtime hasn't changed since last reminder.
- Batch UAT questions by section (6 sections, batch all questions per section into single AskUserQuestion call where possible).

**Implementation tracking:** see `docs/superpowers/plans/2026-05-04-vg-accept-uat-batching.md` (TBD).

---

### Codex Hotspot 6 — Agent guard verbosity (MED)

**Path:** `scripts/vg-agent-spawn-guard.py:145` + `scripts/hooks/vg-pre-tool-use-bash.sh:329`

**Mechanism:** When Agent() spawn blocked, `permissionDecisionReason` = full prose explanation (gate id + cause + fix instructions + recovery options). Re-injected to model context. ~500 tokens per blocked spawn.

**Proposed fix:** permission reason = gate id + one-line cause + block-file path. Full prose lives in block-file; model reads it only if user asks.

---

## Priority order (combined Claude + Codex)

| # | Action | Combined ROI | Status |
|---|---|---|---|
| 0 | **R3 review slim** (`review.md` 7803→500 lines) | save ~25-30K/review session | **In progress** — implementer subagent running |
| 1 | **Remove literal capsule injection** (Codex P1) | save ~5-10K/build (× task count) | Spec needed |
| 2 | Split `waves-overview.md` (1364→3 refs) | save ~900/wave | R2-style split |
| 3 | **Workflow context dedup** (Codex P3) | save ~300-500/workflow phase | Spec needed |
| 4 | Split `post-execution-overview.md` (1023→4 refs) | save ~600/build | R2-style split |
| 5 | **Accept UAT batching + reminder suppression** (Codex P5) | save ~2-3K/accept | Spec needed |
| 6 | Compact Agent guard reasons (Codex P6) | save ~500/blocked-spawn | Trivial fix |

## What we are NOT going to do

- **Split `accept/gates.md`** — F3-r2 design note explicitly keeps it monolithic to avoid duplicating `block-resolver.sh / override-debt.sh / rationalization-guard.sh` sourcing across 5 files. Codex agrees by not flagging it. Skip.
- **Remove flat reads** — `vg-load` migration is already complete in build/accept paths (per audit doc `docs/audits/2026-05-04-build-flat-vs-split.md` line 783). Both auditors confirm.
- **Reduce slim-entry boilerplate** — one-time cost per session, not a spike source. Both auditors agree it's low priority.

---

## Audit metadata

- Claude Explore agent transcript: subagent ID `ad8cb4c50b56201aa` (completed 2026-05-04)
- Codex audit transcript: `/tmp/codex-token-audit-stdout-v3.log`
- Codex authentication issue: 9Router proxy required `cx/` model name prefix (e.g., `cx/gpt-5.5` not `gpt-5.5`); pip CLI default routed to openai → 404. Fixed by using `--model cx/gpt-5.5`.
