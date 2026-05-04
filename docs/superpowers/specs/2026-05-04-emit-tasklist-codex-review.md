# Codex Review: emit-tasklist balanced output

Verdict: GO. Ship balanced format; do not revert.

Information tradeoff: sufficient. Header gives command/phase/profile/mode/counts. Group lines preserve CHECKLIST_DEFS order and each group's step IDs, so AI can infer coarse execution order plus active step inventory. The `↳` hint is not needed in stdout because tasklist contract still contains step titles with `↳`, and shared projection instruction enforces two-layer TodoWrite behavior. Dropping lifecycle prose is safe because `commands/vg/_shared/lib/tasklist-projection-instruction.md` remains authoritative and slim entries reference it; stdout should be run visibility, not full policy.

Edge cases: no blocker. Static parse found 9 commands, 49 groups, 0 empty wanted lists. `_build_checklists()` skips groups with no active items, so mode-filtered flows avoid blank groups. `--mode delta` prints `Mode delta` and active groups only: preflight, complete, phaseP_delta. Long-line risk is readability only: review sample is 7 lines, max 325 chars; terminal/chat wrap does not lose IDs. If this grows past ~500 chars, add soft wrapping/indent continuation, not verbose per-item enumeration.

Anthropic fit: matches progressive disclosure best practice from [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills): expose enough upfront for routing/selection, keep deeper procedure in referenced files loaded only when needed. This output gives the operational skeleton while policy remains in the shared instruction.

Risk: low. Main residual risk is agents that rely only on stdout and never read contract/shared instruction; hook enforcement mitigates. Ship with one follow-up: add regression covering sample line-count range, no empty group lines, mode label, and full active-step coverage.
