# Shared UX Baseline (R1a+) — applies to ALL VG flows

This doc defines 3 cross-flow UX requirements added 2026-05-03 from R1a
blueprint pilot retro. Every spec/plan in `docs/superpowers/specs/` and
`docs/superpowers/plans/` MUST honor these when implemented.

Source decisions: blueprint dogfood revealed (1) AI lướt due to monolithic
artifact context overload, (2) subagent spawn UX was plain text vs GSD's
chip-style, (3) hook stderr was 20-30 lines dominating chat frame.

---

## Requirement 1 — Per-task / per-unit artifact split

**Problem**: monolithic artifacts (PLAN.md 1000+ lines, API-CONTRACTS 1600+
lines, TEST-GOALS 800+ lines) overflow consumer context budget. Build wave
2 only needs tasks 6-10 (~250 lines) but loads full PLAN (1000) → 75%
context wasted on irrelevant tasks → AI lướt do ngợp.

**Pattern**: 3-layer artifact format.

| Layer | Purpose | Example paths |
|---|---|---|
| 1. Per-unit split | Primary load target — small files | `PLAN/task-NN.md`, `API-CONTRACTS/{method}-{slug}.md`, `TEST-GOALS/G-NN.md` |
| 2. Index | Slim TOC + wave map + bindings | `PLAN/index.md`, `API-CONTRACTS/index.md`, `TEST-GOALS/index.md` |
| 3. Flat concat | Legacy compat for grep validators | `PLAN.md`, `API-CONTRACTS.md`, `TEST-GOALS.md` |

**Generator rules**:
- Subagent that writes monolithic artifact MUST also write per-unit + index.
- Concat = `cat index.md` + each per-unit file (preserves vg-binding comments).

**Consumer rules**:
- Use `scripts/vg-load.sh` for partial loads — do NOT enumerate sub-files manually.
  ```
  vg-load --phase N --artifact <plan|contracts|goals> [--task NN | --wave N | --endpoint X | --resource X | --goal G-NN | --priority P | --decision D | --full | --list | --index]
  ```
- For full sweeps (review/accept), use `--full` (= read flat concat).
- For wave-scoped (build), use `--wave N`.
- For task-scoped (build executor), use `--task NN`.

**Runtime contract**:
- entry SKILL.md `must_write` lists Layer 1 globs (`glob_min_count: 1`) + Layer 2 indexes + Layer 3 flat concat.
- Stop hook verifies all 3 layers exist.

**Apply to**: blueprint (DONE R1a), build (R2 — needs split for BUILD-LOG, WAVE-RESULT, etc.), test (R2 — TEST-RESULTS per goal), review (R3 — RUNTIME-MAP per surface), accept (R4 — UAT checklist per goal), scope (R3.5 — DECISION per round), project (R4 — FOUNDATION per section).

---

## Requirement 2 — Subagent spawn narration (green-tag chip)

**Problem**: `Agent(subagent_type=...)` calls were plain text. User couldn't
glance-scan run progress to see which subagent active.

**Pattern**: every `Agent()` call wrapped with `vg-narrate-spawn` bash
helper (ANSI-colored pill output). 3 states with bg color:
- `spawning` → 🟢 green pill
- `returned` → 🔵 cyan pill
- `failed`   → 🔴 red pill

**AI workflow** (per vg-meta-skill.md MANDATORY section):
```bash
bash scripts/vg-narrate-spawn.sh <subagent-name> spawning "<short context>"
```
```
Agent(subagent_type="<subagent-name>", prompt=<...>)
```
```bash
bash scripts/vg-narrate-spawn.sh <subagent-name> returned "<result summary>"
# OR on failure:
bash scripts/vg-narrate-spawn.sh <subagent-name> failed "<one-line cause>"
```

**Apply to**: every spawn site in every flow. Examples:
- blueprint: vg-blueprint-planner, vg-blueprint-contracts (DONE)
- build: vg-build-executor (per task), vg-reflector
- review: vg-haiku-scanner, vg-design-fidelity-guard, vg-design-gap-hunter, vg-reflector
- test: vg-haiku-scanner, flow-runner, sandbox-test, vg-crossai
- accept: AskUser (no spawn — different UX)

**No hook enforcement** — operator courtesy convention. Skipping = ugly UX
but no block. Flow specs MUST include narrate-spawn calls in every
post-spawn / pre-spawn step's bash example.

---

## Requirement 3 — Compact hook stderr output

**Problem**: hook block stderr was 20-30 lines (heredoc with diagnostic +
narration template + retry instructions). Long output dominated chat,
hurt operator situational awareness.

**Pattern**:
- **Success path**: 0 stderr (silent — hook fires invisibly when permitted).
- **Block path**: 3 lines max stderr:
  1. `⛔ {gate_id}: {one-line cause}`
  2. `→ Read .vg/blocks/{run_id}/{gate_id}.md for fix`
  3. `→ After fix: vg-orchestrator emit-event vg.block.handled --gate {gate_id}`

Full diagnostic (cause / required fix / narration template / after-fix
command) → `.vg/blocks/{run_id}/{gate_id}.md` (file). AI reads on demand.

**Hook implementation pattern** (template):
```bash
emit_block() {
  local cause="$1"
  local gate_id="<MyGate-Name>"
  local run_id="<extract from .vg/active-runs/${session}.json>"
  local block_file=".vg/blocks/${run_id}/${gate_id}.md"

  mkdir -p "$(dirname "$block_file")"
  cat > "$block_file" <<EOF
# Block diagnostic — ${gate_id}
## Cause
${cause}
## Required fix
- ...
## Narration template
[VG diagnostic] ...
## After fix
\`\`\`
vg-orchestrator emit-event vg.block.handled --gate ${gate_id} --resolution "..."
\`\`\`
EOF

  printf "⛔ %s: %s\n→ Read %s for fix\n→ After fix: vg-orchestrator emit-event vg.block.handled --gate %s\n" \
    "$gate_id" "$cause" "$block_file" "$gate_id" >&2

  vg-orchestrator emit-event vg.block.fired --gate "$gate_id" --cause "$cause" >/dev/null 2>&1 || true
  exit 2
}
```

**Apply to**: every NEW hook script. Existing R1a hooks already migrated
(2026-05-03 commit 118dc25): vg-pre-tool-use-bash, vg-pre-tool-use-write,
vg-pre-tool-use-agent, vg-stop. Future hooks (R2 build-time, R3 review
spawn-count, etc.) MUST follow this pattern from day-1.

---

## Spec authoring checklist

When writing a new flow spec (R1b/c/d, R2, R3, R3.5, R4, R5), VERIFY:
- [ ] Per-task split? Subagents that produce monolithic artifacts also write
      Layer 1 (per-unit) + Layer 2 (index). Entry runtime_contract.must_write
      includes glob_min_count.
- [ ] Consumer load uses `vg-load.sh`? (or documents why full read needed)
- [ ] Subagent spawn narration in every spawn site bash example?
- [ ] Hook stderr ≤3 lines on block; full diagnostic to file?

This list MUST appear in every R1b+ spec's "Operational invariants" section.
