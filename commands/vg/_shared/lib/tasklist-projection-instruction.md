# Tasklist projection instruction (shared reference)

Slim entries (build/test/review/accept/scope) MUST embed this block as
the FIRST imperative after `vg-orchestrator run-start` and BEFORE any
`vg-orchestrator step-active` call. The PreToolUse-bash hook BLOCKs all
step-active calls until evidence file exists; running step-active first
will trigger the block, which AI agents have historically resolved
without actually projecting (15+ such bypasses recorded in PV3 events.db).

## Embed this block verbatim:

```bash
# BEFORE any step-active — project the tasklist contract to the native UI.
# The PreToolUse-bash hook will BLOCK step-active calls until evidence exists.

CONTRACT_PATH=".vg/runs/${RUN_ID}/tasklist-contract.json"
if [ ! -f "$CONTRACT_PATH" ]; then
  echo "⛔ tasklist-contract.json missing — orchestrator should have written it during run-start" >&2
  exit 1
fi
```

Then **the AI agent MUST** (this is the part the hook enforces):

1. Read `${CONTRACT_PATH}` and parse `checklists[]`.
2. Project the contract to the runtime-native task UI.
   - Lifecycle: `replace-on-start`; `close-on-complete`.
   - **B77 v4.63.9 — REPLACE semantics (HARD-GATE):** every `TodoWrite` call
     REPLACES the entire prior list in one shot. Pass EXACTLY the
     `projection_items[]` from this contract — **no items from previous
     waves/commands, no accumulated history.** PostToolUse hook now writes
     `accumulation_suspected: true` when `todos[]` exceeds 1.5× contract
     size; PreToolUse-bash BLOCKs the next `step-active` until you
     re-project clean. The user-visible UI carrying 500+ stale items from
     prior runs is the symptom this gate prevents.
   - Claude uses `TodoWrite` with the full two-layer hierarchy.
   - Codex uses a compact plan window, not the full hierarchy: at most 6
     visible rows, active group/step first, next 2-3 pending steps, completed
     groups collapsed, and one `+N pending` row. The full hierarchy remains in
     `tasklist-contract.json`; do not paste all 40+ review items into Codex
     `update_plan`.
3. Run:
   ```bash
   python3 .claude/scripts/vg-orchestrator tasklist-projected --adapter auto
   ```
   This validates/binds the native projection to the contract checksum and writes
   `.vg/runs/${RUN_ID}/.tasklist-projected.evidence.json`. CLI emit of the
   `*.native_tasklist_projected` event is rejected by the orchestrator (sole-owner rule).

After both succeed, subsequent `step-active` calls pass the PreToolUse-bash hook.

## Claude 2-layer hierarchy required (Task 44b enforcement)

The TodoWrite payload MUST contain BOTH layers:

1. **Group headers** — one todo per checklist group (e.g.
   `review_preflight`, `build_execute`). Match by `id` OR `title`.
2. **Sub-items** — at least one `↳`-prefixed child todo per group,
   immediately following the group header.

Example (5 groups → 5 group headers + ≥1 ↳ sub-item per group):

```
[ ] review_preflight
  ↳ 0a_env_mode_gate: pick env from DEPLOY-STATE
  ↳ create_task_tracker: emit-tasklist + tasklist-projected
[ ] review_be
  ↳ phase1_code_scan: ripgrep + ripple analysis
[ ] review_discovery
  ↳ phase2_browser_discovery: organic Playwright sweep
  ↳ phase2_5_recursive_lens_probe: lens dispatcher
...
```

The PostToolUse hook walks todos in order and counts ↳ sub-items per
group. Any group with zero ↳ children → evidence is signed with
`depth_valid=false`. The PreToolUse hook then BLOCKs every subsequent
`step-active` with cause `tasklist depth=1 (flat); minimum required is
2-layer (group + ↳ sub-items)`.

Sub-item prefix is `↳` (Unicode U+21B3). Plain `-` / `*` / 2-space
indent will NOT satisfy the depth check.

## Why this is mandatory

- Native task UI is the user's primary signal of progress. Markdown tables
  in chat are NOT a substitute — sếp Dũng cannot see which step is in flight.
- Reordering: place this block IMMEDIATELY after `run-start` so the AI cannot
  "forget" or skip past it on the way to step-active.
- Hook enforcement: PreToolUse-bash blocks `step-active` if evidence missing.
  Bypassing the block (emitting `vg.block.handled` without resolution) leaves
  evidence still missing — next step-active blocks again. Telemetry event
  `<command>.tasklist_projection_skipped` (warn-tier) records each bypass
  attempt for `/vg:gate-stats` analysis.

## Post-AskUserQuestion sync (RULE — v2.51.12+)

When the AI asks the user via `AskUserQuestion` (or the Codex equivalent
main-thread Q&A) and the answer **branches a step, scopes the work, or
adds/removes items in the active phase**, the AI MUST call `TaskUpdate`
(or `TodoWrite` on legacy runtime) to reflect the chosen branch BEFORE
running the next bash/edit. Pattern:

- Keep the active group header.
- Edit the in-flight step's `↳` sub-item to mention the chosen branch
  (e.g. `↳ 0a_env_mode_gate: pick env from DEPLOY-STATE → user chose sandbox`).
- Append new `↳` sub-items if the answer expands scope (e.g. user typed
  Other / custom branch text and the AI now plans 3 follow-up sub-tasks).
- Mark `completed` if the answer closes the step.

Hook enforcement (advisory): PostToolUse-AskUserQuestion (`vg-post-tool-use-askuserquestion.sh`)
emits a `hookSpecificOutput.additionalContext` reminder after every answer
when an active VG run + tasklist contract exist. The reminder is non-blocking —
it surfaces the rule to the AI in the tool result. Skipping the sync still
costs operator visibility; downstream `tasklist-projected --adapter auto`
re-checks evidence on subsequent step transitions and may BLOCK if the
projected hierarchy drifts from the contract.

Why interactive answers historically drift: pre-v2.51.12, no PostToolUse
hook fired on `AskUserQuestion`, so the AI had no harness signal to update
the task UI after a custom-text answer. AI received the answer, made a
decision, ran the next bash — and the task UI silently stayed on the old
branch. Bug class user-reported (sếp Dũng), 2026-05-08.
