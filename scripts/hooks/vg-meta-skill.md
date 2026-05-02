<EXTREMELY-IMPORTANT>
You have entered a VGFlow workflow session.

VGFlow is a deterministic harness. Steps are not suggestions. They are
contracts validated by hooks. You CANNOT skip a step by claiming it is
"obvious" or "already done" — every step has a marker file and an event
record that the Stop hook verifies.

If a tool call is blocked by PreToolUse hook, read the stderr message,
fulfill the missing prerequisite, then retry. Do not work around the gate.
</EXTREMELY-IMPORTANT>

## Red Flags (you have used these before — they will not work)

| Thought | Reality |
|---|---|
| "I already understand the structure, no need to read references" | References contain step-specific instructions absent from entry |
| "Subagent overkill for this small step" | Heavy step has empirical 96.5% skip rate without subagent |
| "TodoWrite is just UI, the contract is in events" | Hook checks TodoWrite payload against contract checksum |
| "I can mark step done now and finish content later" | Stop hook reads must_write content_min_bytes; placeholder fails |
| "The block was a one-off, retrying should work" | Each block emits vg.block.fired; Stop hook blocks if unhandled |
| "I'll just retry, no need to tell the user" | Layer 5 rule: narrate in session language using template, never retry silently |
| "I'll write the evidence file directly" | Protected paths blocked by PreToolUse on Write — use vg-orchestrator-emit-evidence-signed.py |

## Open diagnostic threads (Layer 4 mechanism)

If this injected context contains "OPEN DIAGNOSTICS for current run", you
have unresolved blocks from earlier in this run (possibly across context
compactions). For each open diagnostic, you MUST:

1. Read the cause + required fix from the original block message (still in
   events.db, query: `vg-orchestrator query-events --event-type vg.block.fired`)
2. Apply the fix
3. Narrate to user in session language using the template from the original block
4. Bash: `vg-orchestrator emit-event vg.block.handled --gate <gate_id> --resolution "<summary>"`

You CANNOT do other work until all open diagnostics are closed. Stop hook
will refuse run-complete if any vg.block.fired is unpaired with vg.block.handled.

## Pipeline commands governed by VGFlow

project, roadmap, specs, scope, blueprint, build, review, test, accept

When the user invokes `/vg:<cmd>`, follow the slim entry SKILL.md exactly.
Read references when instructed. Spawn subagents (using tool name `Agent`,
NOT `Task`) when instructed.

## Subagent spawn narration (MANDATORY)

For EVERY `Agent(subagent_type=...)` call, emit a colored-tag narration
BEFORE the spawn AND AFTER its return. Uses bash helper that outputs ANSI
escape codes — Claude Code chat renders as green/cyan/red pill.

Pattern:
```bash
bash scripts/vg-narrate-spawn.sh <subagent-name> spawning ["<short context>"]
```
Then call:
```
Agent(subagent_type="<subagent-name>", prompt=<...>)
```
On return:
```bash
bash scripts/vg-narrate-spawn.sh <subagent-name> returned ["<result summary>"]
```
On failure (subagent error JSON or empty output):
```bash
bash scripts/vg-narrate-spawn.sh <subagent-name> failed "<one-line cause>"
```

State → background color:
- `spawning` → 🟢 green pill — about to spawn
- `returned` → 🔵 cyan pill — completed successfully
- `failed` → 🔴 red pill — error/timeout/refused

WHY: makes subagent transitions visually distinct in chat — user can
glance-scan run progress without parsing prose. GSD-style chip UX.

DO NOT skip narration to "save bash calls" — UX consistency matters more
than 1 bash call savings. Hook does not enforce this convention; it is
operator courtesy.

## Blueprint artifact convention (R2 — downstream consumption contract)

Blueprint writes 3-layer artifacts: per-task/endpoint/goal split (Layer 1)
+ index files (Layer 2) + flat concat (Layer 3, legacy compat).

**Downstream commands (build, test, review, accept, roam) MUST prefer
`vg-load` over flat read.** Direct `cat $PHASE_DIR/{PLAN,API-CONTRACTS,
TEST-GOALS}.md` is forbidden in AI-context paths (executor capsules,
agent prompts, codegen inputs) because the flat file enters AI context
as a 30-100KB+ blob and triggers skim. Use:

  vg-load --phase N --artifact plan --task NN
  vg-load --phase N --artifact contracts --endpoint <slug>
  vg-load --phase N --artifact goals --goal G-NN

Deterministic transforms (grep validators, mtime checks, surface scans)
MAY keep flat reads — they don't enter AI context. Per-command audit
docs under `docs/audits/` are the canonical KEEP-FLAT classification
(e.g., `docs/audits/2026-05-04-build-flat-vs-split.md`).

Threshold: flat artifact > 30 KB without split subdir triggers a WARN
(advisory, not block) via `scripts/validators/verify-blueprint-split-size.py`.
30 KB ≈ 7K tokens — empirical AI-skim boundary.

Backward compat: `vg-load --full` falls back to flat read for legacy
phases that pre-date the per-task split.
