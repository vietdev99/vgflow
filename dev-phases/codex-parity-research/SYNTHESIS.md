# Codex CLI Parity — Cross-Agent Synthesis & Plan

**Date:** 2026-04-27
**Sources:** `CODEBASE-INVENTORY.md` (Explore agent) + `CODEX-CAPABILITY-RESEARCH.md` (general-purpose with WebSearch).

---

## 1. Cross-agent reconciliation

Two agents researched in parallel, with different scopes. They disagreed on several points; here's the resolution.

| Topic | Agent 1 (codebase) said | Agent 2 (web research) found | Reality |
|---|---|---|---|
| Sub-agent spawn primitive | "Codex exec spawns fresh processes; no native equivalent" | `spawn_agent` tool (built-in `default`/`worker`/`explorer`, max_threads=6) + custom TOML agents + recursive `codex exec` officially endorsed (issue #8962) | **Codex HAS native sub-agent**. Agent 1 missed this. |
| Wave parallelism (build) | "CRITICAL BLOCKER, ~2h refactor" | `spawn_agent` natural-language fan-out + `spawn_agents_on_csv` for batch | **Already supported.** Either bash `&` wrapping OR native spawn_agent. Effort drops to <1h. |
| Review Haiku → Playwright MCP | "CRITICAL BLOCKER, no MCP access in subagent" | Codex has `mcp_servers.<id>` config; tool_timeout_sec configurable; subagents share parent's MCP connections | **MCP IS available.** Just configure `~/.codex/config.toml mcp_servers`. Agent 1's claim is wrong. |
| Model tier mapping | Adapter says opus→gpt-5, sonnet→gpt-4o, haiku→gpt-4o-mini | 2026-04 reality: opus→gpt-5.5 ($5/$30), sonnet→gpt-5.4-mini ($0.75/$4.50), haiku→gpt-5-nano ($0.05/$0.40) or gpt-5.4-nano | **Adapter outdated.** `scripts/generate-codex-skills.sh:110` needs update. |
| Skill format | "Adapter is documentation, not transpiler" | "Claude skill format identical to Codex skill format" — robert-glaser.de | **Both correct.** Format is identical; existing adapter prepends 150-line guide because AI needs to know how to translate Agent() calls at runtime. |
| Hard showstoppers | "Wave parallelism + MCP gap" | "None — only 3 soft bugs (#16548 model param, #15451 schema-with-MCP, #14343 resume schema)" | **No hard blockers.** Agent 1 over-classified soft issues as critical. |

**Net effect:** Roadmap shrinks from ~13 hours to **~6-8 hours**. The "structural rewrite" Agent 1 estimated was actually a config + model-name update.

---

## 2. Revised gap analysis

### 2.1 Real blockers (priority order)

1. **Adapter model mapping outdated** (5 min fix) — `scripts/generate-codex-skills.sh:110` has 2024-era model names. Update to 2026 GPT-5.x tier.

2. **Custom agent TOMLs missing** (30 min) — Codex's most reliable model-control path is `~/.codex/agents/vgflow-{role}.toml`. None exist. Need 3-4 baseline TOMLs.

3. **MCP server config not documented for Codex** (45 min) — Codex needs `~/.codex/config.toml [mcp_servers.playwright]` block to reach Playwright. VGFlow doesn't ship this config or document it.

4. **`codex_spawn` shell helper missing** (45 min) — Agent 2 recommends a thin wrapper around `codex exec` with timeout, model selection, error handling, JSON parsing. Reusable across all skills. Currently every skill would have to invent its own subprocess management.

5. **Skill bodies still call `Agent(...)` directly** (3-4 hours total) — 28 occurrences across 9 skills. Adapter prelude documents how to translate but each skill needs runtime AI to apply it. Better: pre-rewrite the skill body to use a `vg_spawn` shell function that works in BOTH Claude (delegates to Task) AND Codex (delegates to codex exec). That way the same SKILL.md works in both environments.

6. **Soft-blocker bug workarounds** (30 min) — Document in adapter:
   - `spawn_agent` ignores model param → use TOML pinning, not inline (#16548)
   - `--output-schema` + MCP active → silent fail (#15451) → either disable MCP for structured runs OR parse text
   - `codex exec resume` doesn't accept `--output-schema` (#14343) → use fresh `exec` for structured flows

### 2.2 What's actually fine as-is

- 46 codex-skills exist (98% coverage). Generation pipeline works.
- CrossAI infrastructure (`crossai-invoke.md`) already uses `codex exec` correctly.
- Skill format compatibility is real (per robert-glaser.de proof).
- `/vg:init` and `/vg:accept` need zero changes.

---

## 3. Codex model tier mapping (definitive, April 2026)

| VGFlow role | Claude tier | Codex tier | Per-1M cost (input/output) | Context | Notes |
|---|---|---|---|---|---|
| Scope orchestrator, planner | Opus 4.7 | **gpt-5.5** | $5.00 / $30.00 | 1,050,000 | Released Apr 23, 2026. API key auth live since Apr 24. |
| Executor wave, code review | Sonnet 4.6 | **gpt-5.4-mini** | $0.75 / $4.50 | ~400K | Comparable cost-perf to Sonnet. |
| UI-MAP scanner, classification, narration | Haiku 4.5 | **gpt-5-nano** | $0.05 / $0.40 | 400K | 4× cheaper than 5.4-nano. Acceptable for classification. Use 5.4-nano if quality matters. |
| Adversarial / cross-AI peer | Different model | **gpt-5.3-codex** | $1.75 / $14.00 | — | Codex-tuned distribution; useful contrarian viewpoint. |

Batch tier = 50% off. Priority = 2.5× standard for guaranteed throughput.

---

## 4. Architecture: hybrid wrapper pattern

```
VGFlow CLI invocation (Claude OR Codex)
    ↓
SKILL.md (vendor-agnostic body)
    ↓
vg_spawn helper function (in commands/vg/_shared/lib/spawn.sh)
    ├── If $VG_HARNESS == "claude": output Agent(...) JSON for Task tool
    └── If $VG_HARNESS == "codex":  invoke codex exec --model X --output-last-message Y
            ├── For 1-3 children: bash & + wait (reliable model control)
            └── For 5+ parallel: prompt-driven spawn_agent (lower latency)
```

**Why one helper instead of two skill copies:** Maintenance. Currently every skill change requires regenerating Codex variant via `generate-codex-skills.sh`. With shared `vg_spawn`, both harnesses read the same SKILL.md and the helper does environment detection.

---

## 5. Phased roadmap (revised: ~6-8 hours total)

### Phase 18.0 — Foundation (1.5 hours)

- 18.0.1 (5 min): Update `scripts/generate-codex-skills.sh:110` model mapping → GPT-5.x tier names
- 18.0.2 (30 min): Write 3 baseline agent TOMLs:
  - `templates/codex-agents/vgflow-orchestrator.toml` (gpt-5.5, workspace-write)
  - `templates/codex-agents/vgflow-executor.toml` (gpt-5.4-mini, workspace-write)
  - `templates/codex-agents/vgflow-classifier.toml` (gpt-5-nano, read-only)
- 18.0.3 (45 min): Build `commands/vg/_shared/lib/spawn.sh` — environment-detecting wrapper. Same call site whether Claude or Codex.
- 18.0.4 (30 min): Write `~/.codex/config.toml` template documenting MCP servers (playwright, penboard, pencil, mem0).

### Phase 18.1 — Cross-AI parity audit (1 hour)

- 18.1.1: Verify `crossai-invoke.md` works end-to-end with current `codex exec` (already does per Agent 1 research; just confirm).
- 18.1.2: Add Codex peer to `crossai_clis` config in `vg.config.template.md` so new projects get it OOB.
- 18.1.3: Smoke test cross-AI invoke from a fixture phase.

### Phase 18.2 — Skill body rewrites for shared spawn (3-4 hours)

For each of 9 skills with `Agent(...)` calls, replace inline Agent block with `vg_spawn` helper call. Order:
1. `/vg:project` (1 spawn — easiest)
2. `/vg:test` (2 spawns — straightforward)
3. `/vg:scope` (2-3 spawns + fd-3 prompt workaround needed)
4. `/vg:blueprint` (3 spawns — context pre-assembly)
5. `/vg:build` (5+ spawns — wave parallelism, biggest single change)
6. `/vg:review` (8+ spawns — Haiku scanner refactor; verify MCP access works)

After each, run existing tests + add Codex-specific smoke test.

### Phase 18.3 — Documentation + dogfood (1 hour)

- 18.3.1: Update `scripts/generate-codex-skills.sh` adapter prelude to reference new `vg_spawn` helper and current model tier names.
- 18.3.2: Document Codex install path in README + AGENTS.md.
- 18.3.3: Run full pipeline (project → init → scope → blueprint → build → test → review → accept) end-to-end with `codex exec` on a fixture phase. Note any gaps.

### Out of scope for Phase 18

- Recursive sub-agent depth >1 (Codex default `max_depth = 1`). VGFlow currently doesn't need this.
- `--output-schema` + MCP simultaneous use (#15451 unresolved). Document workaround; defer until OpenAI fixes upstream.
- Codex App (remote project) gpt-5.5 issue (#19370). VGFlow runs locally; not affected.

---

## 6. Showstopper / risk register

### Hard blockers — none.

### Soft risks (workarounds documented)

| Risk | Severity | Mitigation |
|---|---|---|
| `spawn_agent` ignores inline model param (#16548) | Medium | Lock model in agent TOML; never pass inline |
| `--output-schema` dropped silent when MCP active (#15451) | Medium | Disable MCP for structured-output runs OR use plain text + parse |
| `codex exec resume` doesn't support `--output-schema` (#14343) | Low | Fresh exec for structured flows; lose memory |
| gpt-5.5 not yet rolled out to all regions | Low | Have `gpt-5.4` fallback in agent TOML |
| Higher token cost (1.3-1.8× Claude per OpenAI docs) | Low | Plan + budget; use cheap tiers (5-nano) where possible |
| `max_depth = 1` default | Low | Raise in config.toml only if VGFlow truly needs nested spawn |

### Operational caveats

- Recursive `codex exec` inherits parent sandbox — design sandbox modes per-skill.
- No hard `codex exec` timeout — wrap with shell `timeout`.
- gpt-5.5 launched Apr 23 with ChatGPT-only auth; API key auth shipped Apr 24, 2026. Should work today (2026-04-27) but verify in target region.

---

## 7. Recommended decision

Given that:
- No hard showstoppers exist
- Estimated effort dropped from 13h → 6-8h after agent reconciliation
- Foundation work (1.5h) is independent low-risk; can ship as Phase 18.0 alone
- Phase 18.2 (skill rewrites) is the largest chunk and benefits from staged shipping per skill

**Recommend lock Phase 18 as 4 sub-phases (18.0, 18.1, 18.2, 18.3) with 18.2 broken into per-skill atomic commits.** Total ~6-8h dev + 1h dogfood = single workday.

Trigger condition: user confirmation. After confirmation, do `/gsd-plan-phase 18` to produce concrete BLUEPRINT + atomic task breakdown.

---

## 8. Open questions for user before lock

1. **Model tier defaults:** Current proposal uses gpt-5-nano for scanner ($0.05/$0.40, 4× cheaper than 5.4-nano but older training). Acceptable, or prefer 5.4-nano for quality?

2. **Custom TOML location:** Project-scoped `.codex/agents/` (per-project) or user-global `~/.codex/agents/` (shared across all VGFlow projects)? Both supported.

3. **Adapter strategy:** Pre-rewrite skill bodies to use `vg_spawn` (more invasive, cleaner long-term) OR keep current adapter-prelude docs + improve inline guidance (less code change, more runtime burden on AI)?

4. **gpt-5.5 fallback:** If gpt-5.5 unavailable in user's region, fall back to gpt-5.4 (slightly weaker reasoning) or gpt-5.3-codex (codex-tuned, different distribution)?

5. **Phase 18 trigger:** Ship Phase 18.0 foundation first as v2.11.2 patch (low risk, useful standalone), then Phase 18.1-18.3 as v2.12.0? OR ship all 4 sub-phases as single v2.12.0 release?
