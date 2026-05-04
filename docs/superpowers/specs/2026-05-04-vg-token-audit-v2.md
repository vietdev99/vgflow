# VG Token Audit v2 — Bug D3 + remaining hotspots

**Trigger:** Sếp Dũng dogfood `/vg:build 4.2 + /vg:accept 4.1` minutes after Bug D fix shipped → token spike STILL persisted.

**Auditors:** Claude (Bash + Read investigation) + Codex CLI gpt-5.5 (cross-AI; v4 timed out, v5 partial result).

**Headline finding:** Bug D fix (universal Stop-hook gate) trị retry loop. But the orchestrator was ALSO printing a ~285-token compact taskboard to stdout on every `step-active` AND `mark-step` call, returned to AI as Bash response. With 100-200 step transitions/session, that's 28-57K tokens/session of pure redundant re-rendering.

---

## ROOT CAUSE — Bug D3 (FIXED in commit 7688736)

### Evidence chain

1. events.db query (PrintwayV3, 1-hour window post-Bug-D-fix):
   ```
   step.marked: 85
   step.active: 44
   hook.step_active: 31
   ```
   = 160 step transitions in 1 hour for a single accept run.

2. `.claude/scripts/vg-orchestrator/__main__.py` `_render_taskboard(compact=True)` output measured:
   - 14-16 lines per call
   - 285 tokens (cl100k tokenizer)
   - Same content rendered every step transition (just one different "active" step indicator)

3. Both `cmd_step_active` (line 1131) and `cmd_mark_step` (line 1488) called `_render_taskboard` and `print(pretty)`.

### Math

- 100 step transitions × 285 tokens = 28,500 tokens/session
- 200 step transitions × 285 tokens = 57,000 tokens/session
- Build + accept combined session ≈ 50-100K tokens of taskboard noise
- Plus prompt cache invalidation: every taskboard re-render is unique (different "active" step) → busts cache window

### Fix

Removed taskboard render from `cmd_step_active` and `cmd_mark_step`. Kept single-line acks:
```
active: 6b_security_baseline
marked: accept/6b_security_baseline
```

Taskboard remains available on explicit demand via `vg-orchestrator run-status --pretty`. AI already has TodoWrite UI for live progress (Bug D2 payload-ordering rule).

### Validation

- 57/57 tasklist tests pass (no regression)
- Mirrored to `scripts/vg-orchestrator/__main__.py` source copy
- Synced to PV3 mirror

---

## Remaining hotspots (ranked by ROI)

### Priority 1 — R3 review slim refactor (IN PROGRESS)

- `commands/vg/review.md` = 7803 lines, biggest slim entry by far
- R3 plan at `docs/superpowers/plans/2026-05-03-vg-r3-review-pilot.md`
- Implementer subagent has committed Tasks 8-13 (11/14 refs done)
- Remaining: Tasks 14-17 (delta-mode, profile-shortcuts, crossai, close), Task 18 (subagent SKILL), Task 19 (slim entry replacement)
- **Estimated savings: 25-30K tokens per review session** (one-time per session, but every review session)

### Priority 2 — Capsule double-load (Codex P1, deferred)

- `commands/vg/_shared/build/waves-overview.md:392` materializes capsule + 8 Python one-liners parse JSON into bash vars + substitute into prompt template
- Subagent then re-reads same capsule via `@${capsule_path}`
- 26-task phase = 26x cost
- Fix: drop bash-var-substitution; keep only `@${capsule_path}` reference + sha256 validator
- **Estimated savings: 5-10K tokens per build** (multiplied by task count)

### Priority 3 — emit-tasklist.py output (LOW priority)

- `scripts/emit-tasklist.py` lines 544-565 print ~95 lines per call:
  - 75 projection-item lines (`[ ] {title}`)
  - 9 lines of marker prose template
  - 5 separator bars
- Called once per session start
- **Estimated savings: ~280 tokens per session** (one-time, low impact)
- Fix: drop projection-item list from stdout (AI reads tasklist-contract.json from disk anyway). Keep summary line + contract path.

### Priority 4 — Workflow context per-task duplication (Codex P3, deferred)

- `commands/vg/_shared/build/waves-delegation.md:197-218` injects same workflow spec into every workflow-bound task prompt
- Phase with 5 workflow tasks sharing 1 workflow spec = 5× injection
- Fix: emit `wave-${N}-workflow-context.json` once per wave, reference per-task
- **Estimated savings: 300-500 tokens per workflow-heavy phase**

### Priority 5 — Accept UAT batching (Codex P5, deferred)

- 50+ AskUserQuestion turns × 17-line `<vg-flow-context>` reminder per turn
- Fix: suppress reminder when state unchanged; batch UAT questions per section
- **Estimated savings: 2-3K tokens per accept session**

### Priority 6 — specs.md slim pilot

- `commands/vg/specs.md` = 596 lines (mainline pipeline gate, 1st step of every phase)
- After R3 review done, this is the only mainline command remaining unslimmed
- **Estimated savings: ~2K tokens per /vg:specs invocation** (rare per phase, but baseline reduction)

---

## What we ARE NOT going to fix

| Issue | Why skip |
|---|---|
| Slim-entry boilerplate (Red Flags + HARD-GATE per cmd) | One-time cost per session; both auditors confirm low priority |
| `accept/gates.md` (641 lines) | F3-r2 design intentionally monolithic to avoid duplicate sourcing across 5 split files |
| Flat reads of PLAN.md / API-CONTRACTS.md / TEST-GOALS.md | Already migrated to vg-load via per-task partial loader |
| Hook stderr verbosity | Hook is silent on success path (3 stderr emitters total in 676-line hook); only fires on block |
| validator subprocess noise | Validators write JSON to .tmp/ files, NOT inject into AI context unless user explicitly cats file |

---

## Anthropic best practices applicable

Per [Best practices for Claude Code](https://www.anthropic.com/engineering/claude-code-best-practices) + [Equipping agents with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills):

1. ✅ **Modular skills with reference files** — VG already follows this pattern (slim entry + `_shared/<cmd>/*.md` refs). R3 brings review to compliance.
2. ✅ **Progressive disclosure** — slim entries show metadata; refs loaded on demand. Pattern correct.
3. ✅ **Mutually exclusive paths in separate refs** — different profiles → different verdict refs. R3 enforces this for review's 4 profile branches.
4. ⚠️ **Prompt caching** ([5-min TTL docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)) — VG doesn't currently use cache breakpoints. Stable refs (HARD-GATE blocks, language policy) would benefit but requires harness-level integration. Out of scope for current session.
5. ⚠️ **Place stable content first** — VG currently puts dynamic content (CONTEXT.md, TodoWrite state) early. Could reorder for cache hit but again harness-wide change.

---

## Audit metadata

- Bug D3 fix commit: `7688736` (vgflow-bugfix), `c797168f`-equivalent (PV3 mirror)
- R3 review slim progress: 11/14 refs (Tasks 8-13 committed in commits 28104cd, 3fecaca, df9da67, 1491034, 755deae, c4a76c6)
- Codex v4 audit: stuck 10+ min, killed
- Codex v5 audit: 4-min timeout, partial — file-read only, no synthesis
- Claude self-audit + Bug D3 fix: 5-7 min from problem identification to commit + push

## Total token savings shipped today

| Bug | Saving |
|---|---|
| D — Bug D retry-loop fix | 25-35K tokens (one-off when accept fails) |
| D2 — payload ordering | UX (no token cost change) |
| D3 — taskboard render | **28-57K tokens per session** (recurring) |
| **Total** | **~55-90K tokens per build+accept session** |

R3 review slim, when complete, will add another ~25-30K savings per review session (one-time per review run).

Capsule injection fix (Codex P1, deferred) will add ~5-10K savings per build session.
