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
2. Call `TodoWrite` with one todo entry per `items[]` row across all checklists.
   Each todo's `content` field = the item ID (e.g. `0a_env_mode_gate`).
   The PostToolUse-TodoWrite hook signs `.tasklist-projected.evidence.json`.
3. Run:
   ```bash
   python3 .claude/scripts/vg-orchestrator tasklist-projected --adapter claude
   ```
   This validates that the most recent TodoWrite payload matches the contract checksum
   AND writes `.vg/runs/${RUN_ID}/.tasklist-projected.evidence.json`. CLI emit of the
   `*.native_tasklist_projected` event is rejected by the orchestrator (sole-owner rule).

After both succeed, subsequent `step-active` calls pass the PreToolUse-bash hook.

## 2-layer hierarchy required (Task 44b enforcement)

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

## Tasklist lifecycle contract

Every command's tasklist follows the same lifecycle (canonical here so every
slim entry's Tasklist policy block can reference this ref instead of repeating
the prose — moved out of emit-tasklist.py stdout per Bug F 2026-05-04 token
audit):

- **`replace-on-start`** — the FIRST native projection MUST replace any stale
  task list from a previous workflow. Never append current items onto a
  previous run's list. Example: if `/vg:build 4.1` left a tasklist visible
  and operator now invokes `/vg:review 4.1`, review's first TodoWrite call
  must REPLACE (not append to) the build tasklist.

- **`close-on-complete`** — before reporting success, mark all checklist
  items completed. Then either clear the native list (if the runtime exposes
  a clear API) OR replace it with one completed sentinel item:
  `<command> phase ${PHASE_NUMBER} complete`. Sentinel ensures the
  user/operator can confirm the run terminated cleanly and didn't get
  stuck mid-step.

- **`payload-ordering`** (Bug D2 2026-05-04) — Claude Code TodoWrite UI
  renders todos in payload-array order, NOT auto-sorted by status. On every
  TodoWrite call REORDER `todos[]` so the active group header + its
  `in_progress` sub-step appear FIRST, remaining pending items next,
  completed items LAST. Hierarchy is preserved (each group header still
  precedes its own ↳ sub-steps). This keeps the operator's eye on
  "what's running now" instead of forcing them to scroll through completed
  groups.

Slim entries reference this ref via `Read _shared/lib/tasklist-projection-
instruction.md and follow it exactly.` — so any slim entry that uses
TodoWrite inherits this lifecycle contract automatically. Authoring a new
slim entry: add the same one-line reference inside the Tasklist policy
section. No need to repeat the lifecycle prose inline.
