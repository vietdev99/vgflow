# VGFlow → Codex CLI Parity — Handoff Brief

**Audience:** Codex CLI (GPT-5.x) reading this fresh, no prior conversation context.
**Repo:** `D:\Workspace\Messi\Code\vgflow-repo` (Windows 10, bash via Git Bash)
**Origin remote:** `https://github.com/vietdev99/vgflow.git`
**Current state:** v2.11.1 just shipped (Phase 16 hot-fix). Test count: 218 passed, 1 skipped.
**Date:** 2026-04-27

---

## 1. What VGFlow is (60-second context)

VGFlow is a workflow-orchestration tool that ships as **shared skills/commands** for AI coding CLIs. It's meant to be invoked from inside an AI session via `/vg:foo` slash commands. The full pipeline is:

```
/vg:project → /vg:init → /vg:scope → /vg:blueprint → /vg:build → /vg:test → /vg:review → /vg:accept
```

Source of truth lives in `commands/vg/*.md` (Claude Code skill bodies). A generator script (`scripts/generate-codex-skills.sh`) regenerates `codex-skills/vg-{name}/SKILL.md` files from the same source — these are the variants that get installed under `~/.codex/skills/` for Codex CLI.

The build process spawns parallel sub-agents per task wave. Sub-agent spawning in Claude Code uses the `Task` tool primitive (called `Agent(...)` in skill bodies). VGFlow has 28 such spawn calls across 9 skills.

**The problem:** when a user runs `/vg:foo` from Codex CLI instead of Claude Code, the spawn semantics differ enough that several skills don't work end-to-end.

---

## 2. The question we asked (and what we want from you, Codex)

The user asked us to research:

> "Nâng cấp để codex cli cũng chạy được đầy đủ như claude. Codex khác về cách spawn agent — research xem các model nào tương ứng với haiku, sonnet của codex. Sửa flow để khi tôi chạy với codex, codex có thể spawn sub agent để làm các flow mà codex đang chưa hỗ trợ. Đồng thời kiểm tra review/test/accept của codex đã được đầy đủ như claude làm chưa. Đây là 1 plan lớn, phải nghiên cứu nghiêm chỉnh. Hiện tại thì từ khâu project, init, scope, blueprint... đều đang chưa được thể hiện với codex, kiểm tra xem còn workflow nào chưa có, thì tìm cách merge để codex cli chạy được hết."

Translation of intent:
1. Make Codex CLI run the FULL VGFlow pipeline (currently broken for several skills).
2. Map Codex models to Haiku/Sonnet/Opus tiers.
3. Add sub-agent spawning capability where flows currently lack it on Codex.
4. Verify review/test/accept work as fully on Codex as on Claude.
5. Inventory all `/vg:*` commands and find a merge path so Codex runs them all.

**What we want from you (Codex):**
- Read this file end-to-end before doing anything.
- **Answer the 5 questions in §6** — these are blocked-on-user decisions, but we want your read on them too as a sanity check.
- **If you disagree with any finding in §3-§5**, surface that disagreement explicitly. The Claude-driven research may have blind spots about Codex's actual capabilities.
- **Optionally**: produce a counter-plan or refined Phase 18 atomic task breakdown, if our roadmap is suboptimal.

Do NOT start implementing yet. This is a planning handoff. The user will lock the plan after seeing your response.

---

## 3. What two parallel research agents found (consolidated)

Two Claude sub-agents researched in parallel:
- **Agent 1 (codebase Explore):** inventoried `commands/vg/` vs `codex-skills/`, grep'd Agent() spawn dependencies, classified blockers. Output: `dev-phases/codex-parity-research/CODEBASE-INVENTORY.md`.
- **Agent 2 (web research general-purpose):** researched Codex CLI multi-agent primitives, GPT-5.x model tier pricing, community patterns. Used WebSearch + WebFetch. Output: `dev-phases/codex-parity-research/CODEX-CAPABILITY-RESEARCH.md`.

The two agents disagreed on key points. **Resolution table:**

| Topic | Agent 1 said | Agent 2 found | Resolved truth |
|---|---|---|---|
| Sub-agent spawn primitive | "Codex exec spawns fresh processes; no native equivalent to Claude's Task" | `spawn_agent` tool (built-in `default`/`worker`/`explorer`, max_threads=6) + custom TOML agents at `~/.codex/agents/<name>.toml` + recursive `codex exec` officially endorsed by OpenAI maintainer on issue [#8962](https://github.com/openai/codex/issues/8962) (closed) | **Codex HAS native sub-agent.** Agent 1 was wrong. |
| Build wave parallelism (BLOCKER claim) | "CRITICAL BLOCKER, ~2h refactor — Claude harness spawns 5+ in 1 message; Codex needs bash subprocess management" | `spawn_agent` natural-language prompt fans out (max_threads=6 default); `spawn_agents_on_csv` for batch. Bash `&` + `wait` also works for recursive `codex exec`. | **Already supported.** Effort drops to <1h. |
| Review Haiku → Playwright MCP (BLOCKER claim) | "CRITICAL BLOCKER, 4h — codex exec subagent has no MCP access; Haiku scanners that call Playwright break" | Codex has `mcp_servers.<id>` config in `~/.codex/config.toml`. `tool_timeout_sec`, `startup_timeout_sec` configurable. Subagents share parent's MCP server connections. | **MCP IS available** — just configure `~/.codex/config.toml` properly. Agent 1's claim is wrong. |
| Adapter model mapping (in `scripts/generate-codex-skills.sh:110`) | "Maps opus→gpt-5, sonnet→gpt-4o, haiku→gpt-4o-mini" (verified by grep) | 2026-04 reality: opus→gpt-5.5 ($5/$30), sonnet→gpt-5.4-mini ($0.75/$4.50), haiku→gpt-5-nano ($0.05/$0.40) or gpt-5.4-nano ($0.20/$1.25) | **Adapter is outdated.** `scripts/generate-codex-skills.sh:110` needs update. |
| Skill format compatibility | "Adapter is documentation, not transpiler — AI must apply patterns at runtime" | "Claude skill format identical to Codex skill format" — confirmed by [robert-glaser.de blog post](https://www.robert-glaser.de/claude-skills-in-codex-cli/) | **Both correct.** Format identical; existing 150-line adapter prepended because the AI running the skill needs to know how to translate `Agent()` calls at runtime since the skill body itself uses Claude syntax. |
| Hard showstoppers | "2 critical blockers: build parallelism + review MCP" | "None — only 3 soft bugs with workarounds: #16548, #15451, #14343" | **No hard showstoppers.** Agent 1 over-classified config gaps as blockers. |
| Total estimated effort | "~13 hours roadmap (4 phases)" | "Hybrid wrapper + custom agents architecture; per-skill mapping table" | **Revised: ~6-8 hours** after reconciliation. |

---

## 4. Codex CLI capabilities (verified facts)

These are the facts Agent 2 verified against official docs + GitHub issues + community blog posts. Codex (you), please flag any of these that are wrong as of your knowledge cutoff.

### 4.1 Sub-agent primitives — TWO layers

**Layer A: `spawn_agent` natural-language tool** (default-on, GA since Mar 2026)
- Triggered by prompt instruction, not direct host call: "Spawn one agent per point, wait for all of them, summarize."
- Built-in roles: `default`, `worker`, `explorer`. Custom override by name.
- Concurrency: `agents.max_threads = 6` default. Parent waits for all results.
- Other tools: `send_input`, `resume_agent`, `wait_agent`, `close_agent`, experimental `spawn_agents_on_csv`.

**Layer B: Custom agent TOMLs** (`~/.codex/agents/<name>.toml` or project-scoped `.codex/agents/`):
```toml
name = "vgflow-planner"
description = "VGFlow planner — produces PLAN.md from CONTEXT.md + SPECS.md."
model = "gpt-5.5"
model_reasoning_effort = "high"
sandbox_mode = "workspace-write"
developer_instructions = """
... full planner instructions ...
"""
```
Optional fields inherit from parent session if omitted. **This is the most reliable model-control path** because it sidesteps issue #16548 (model param ignored by `spawn_agent`).

**Layer C: Recursive `codex exec`** — bash-wrap pattern, officially endorsed:
```bash
codex exec --model gpt-5.4-mini "review this diff: $(git diff main)" \
  --output-last-message /tmp/review.md
```
Caveats: parent's sandbox policy applies; need `--full-auto` or `workspace-write` in parent for the recursive call to write files.

### 4.2 Headless mode for automation

`codex exec "<prompt>"`:
- Streams progress to **stderr**.
- Prints **only the final agent message to stdout**.
- Stdin pipe-able as additional context.
- `-o /path` or `--output-last-message` writes final message to file.
- `--output-schema schema.json` constrains output to JSON schema (BUT see #15451 below).
- `CODEX_API_KEY` env var supported here (not in interactive TUI).

### 4.3 GPT-5.x model tier (verified pricing as of 2026-04-27)

| Model | Input/1M | Cached/1M | Output/1M | Context | VGFlow tier |
|---|---|---|---|---|---|
| **gpt-5.5** (released Apr 23, 2026) | $5.00 | $0.50 | $30.00 | 1,050,000 | Opus → planner orchestrator |
| **gpt-5.5-pro** | $30.00 | — | $180.00 | 1M+ | Premium reasoning |
| **gpt-5.4** | $2.50 | $0.25 | $15.00 | ~400K | (Opus fallback) |
| **gpt-5.4-mini** | $0.75 | $0.075 | $4.50 | — | Sonnet → executor |
| **gpt-5.4-nano** | $0.20 | $0.02 | $1.25 | — | Haiku → scanner (quality) |
| **gpt-5.3-codex** | $1.75 | $0.175 | $14.00 | — | Adversarial peer |
| **gpt-5-nano** | $0.05 | — | $0.40 | 400K | Haiku → scanner (cheapest) |

Batch tier = 50% off. Priority tier = 2.5× standard.

**gpt-5.5 auth:** Released Apr 23, 2026 with ChatGPT-only auth. **Apr 24, 2026** OpenAI shipped Responses-API + Chat-Completions-API access for gpt-5.5 with standard `OPENAI_API_KEY`. Should work today (2026-04-27). Issue [#19370](https://github.com/openai/codex/issues/19370) tracks regions where rollout is incomplete.

### 4.4 Skill format (verified IDENTICAL to Claude)

```yaml
---
name: skill-identifier
description: One-sentence summary used for invocation triggering.
---

# Skill body markdown
```

Optional: `allowed-tools` field, `agents/openai.yaml` for UI metadata.

Discovery: Codex requires enumerator script + `AGENTS.md` instruction. Claude auto-loads from skills/ dir.

### 4.5 Soft-blocker bugs (workarounds documented)

| GitHub issue | Status | Impact on VGFlow | Workaround |
|---|---|---|---|
| [#16548](https://github.com/openai/codex/issues/16548) | OPEN | `spawn_agent` ignores requested model param → silent cost escalation (child runs as gpt-5.4 instead of gpt-5.4-mini) | Lock model in agent TOML, NEVER inline in spawn prompt |
| [#15451](https://github.com/openai/codex/issues/15451) | CLOSED but unresolved | `--output-schema` silently dropped when MCP servers active → garbage JSON output | Tách runs: structured-output runs disable MCP; MCP runs use plain text + parse |
| [#14343](https://github.com/openai/codex/issues/14343) | OPEN | `codex exec resume` doesn't accept `--output-schema` | Use fresh `codex exec` for structured flows; lose conversation memory |
| [#14866](https://github.com/openai/codex/issues/14866) | CLOSED | Subagents stuck "awaiting instruction" without explicit per-agent model | Always declare model explicitly in TOML |

### 4.6 Operational caveats

- **No hard `codex exec` timeout.** Wrap with shell `timeout 300 codex exec ...`.
- **Recursive sandbox inheritance.** Child inherits parent's sandbox. Parent must be `workspace-write` for child to write files.
- **`max_depth = 1` default.** Raise in `~/.codex/config.toml` if VGFlow needs nested spawn (currently doesn't).
- **Token cost ~1.3-1.8× Claude** (OpenAI documents this explicitly: "subagent workflows consume more tokens than comparable single-agent runs").

---

## 5. Current VGFlow state — Codex parity matrix

Verified by `grep -nE "Agent\(" commands/vg/*.md`:

| Command | Codex skill exists? | `Agent(...)` spawn count | Status |
|---|---|---|---|
| `/vg:project` | ✓ vg-project | 1× (adversarial challenger, Haiku) | NEEDS ADAPTER |
| `/vg:init` | (redirect, no skill) | 0 | READY |
| `/vg:scope` | ✓ vg-scope | 2-3× (challenger + dimension expander, Opus) | NEEDS ADAPTER + fd-3 prompt workaround |
| `/vg:blueprint` | ✓ vg-blueprint | 3× (planner, test-goal generator, reflector, Opus) | NEEDS ADAPTER |
| `/vg:build` | ✓ vg-build | 5-20× (parallel wave executors, Sonnet) | NEEDS WAVE LOOP REWRITE (but not as bad as Agent 1 said) |
| `/vg:review` | ✓ vg-review | 8-14× (Haiku scanners w/ Playwright MCP) | NEEDS MCP CONFIG TEMPLATE (NOT a structural rewrite) |
| `/vg:test` | ✓ vg-test | 2-3× (test generator + adversarial, Sonnet) | NEEDS ADAPTER |
| `/vg:accept` | ✓ vg-accept | 0 | READY |

### Files that need touching for Phase 18

- `scripts/generate-codex-skills.sh:110` — model mapping update (5 min)
- `commands/vg/_shared/lib/spawn.sh` — NEW file, environment-detecting spawn helper (45 min)
- `commands/vg/_shared/templates/codex-config.template.toml` — NEW file, MCP server template (30 min)
- `templates/codex-agents/{vgflow-orchestrator,vgflow-executor,vgflow-classifier}.toml` — NEW, baseline TOMLs (30 min)
- 9 `commands/vg/*.md` files — replace `Agent(...)` blocks with `vg_spawn` helper calls (3-4h)

---

## 6. FIVE QUESTIONS — please answer

These need decisions before Phase 18 can be locked. Give your reasoning, not just a choice.

### Q1. Scanner model tier
Two candidates for the Haiku-equivalent (used for UI-MAP scanning, narration formatting, classification):
- **gpt-5-nano** — $0.05 / $0.40 per 1M, 400K context, older training (legacy model)
- **gpt-5.4-nano** — $0.20 / $1.25 per 1M, fresher training

VGFlow scanners do classification + simple text formatting, no complex reasoning. Tradeoff: 4× cost difference vs training freshness. **Which do you recommend, and why?**

### Q2. Custom TOML agent location
Two options:
- **Project-scoped** `.codex/agents/<name>.toml` — checked into VGFlow repo; users get them via `install.sh`
- **User-global** `~/.codex/agents/<name>.toml` — installed once per developer machine; shared across all VGFlow projects

Pros of project-scoped: no per-user setup; reproducible across machines; version-controlled.
Pros of user-global: one config per developer; easier to override locally; doesn't pollute project repos.

**Which do you recommend?**

### Q3. Skill body adapter strategy
Two paths:
- **Pre-rewrite** all 9 skill bodies to use a `vg_spawn` shell helper that detects Claude vs Codex environment and dispatches accordingly. Shared `commands/vg/*.md` works for BOTH harnesses. Burden on dev: 3-4h of rewriting + helper logic.
- **Keep adapter prelude docs** (current state — 150-line `<codex_skill_adapter>` block at top of each Codex skill telling AI how to translate `Agent()` to `codex exec`). Burden on Codex AI: must read adapter every invocation and apply translation correctly each time.

Pre-rewrite is more invasive but eliminates runtime translation burden. Adapter prelude is less code change but relies on AI compliance every time. **Which do you prefer, and why?**

### Q4. gpt-5.5 fallback chain
If user's region/org doesn't have gpt-5.5 yet (issue #19370 covers some cases):
- **Fall back to gpt-5.4** — slightly weaker reasoning, same vendor lineage, 2× cheaper
- **Fall back to gpt-5.3-codex** — codex-tuned, different training distribution, may give different style of answer

For VGFlow's planner role (heavy reasoning, structured output), which fallback makes more sense?

### Q5. Ship strategy
Two release patterns:
- **Phase 18.0 only ships first as v2.11.2 patch** (foundation: model mapping, baseline TOMLs, spawn helper, MCP template — low risk, 1.5h work, useful standalone). Phase 18.1-18.3 ship later as v2.12.0.
- **All 4 sub-phases ship together as v2.12.0** (foundation + cross-AI parity + skill rewrites + dogfood — full parity in one release, 6-8h work).

The first option lets users start using gpt-5.x correctly sooner. The second avoids a "half-Codex-ready" intermediate state. **Which is your preference?**

---

## 7. Proposed Phase 18 roadmap (open to your refinement)

### 18.0 Foundation (1.5h)
- 18.0.1 Update `scripts/generate-codex-skills.sh:110` model mapping → GPT-5.x
- 18.0.2 Write 3 baseline agent TOMLs (orchestrator/executor/classifier)
- 18.0.3 Build `commands/vg/_shared/lib/spawn.sh` — environment-detecting wrapper
- 18.0.4 Write `~/.codex/config.toml` template documenting MCP servers (playwright, penboard, pencil, mem0)

### 18.1 Cross-AI parity audit (1h)
- Verify `crossai-invoke.md` works end-to-end with current `codex exec`
- Add Codex peer to `crossai_clis` in `vg.config.template.md` so new projects get it OOB
- Smoke test cross-AI from a fixture phase

### 18.2 Skill body rewrites (3-4h)
For each of 9 skills with `Agent()` calls, replace inline blocks with `vg_spawn` helper. Order:
1. `/vg:project` (1 spawn — easiest pilot)
2. `/vg:test` (2 spawns — straightforward)
3. `/vg:scope` (2-3 spawns + fd-3 prompt workaround)
4. `/vg:blueprint` (3 spawns — context pre-assembly needed)
5. `/vg:build` (5+ spawns — wave parallelism, biggest single change)
6. `/vg:review` (8+ spawns — Haiku scanner refactor + verify MCP access works in subagent)

After each, run existing tests + add Codex-specific smoke test.

### 18.3 Documentation + dogfood (1h)
- Update `scripts/generate-codex-skills.sh` adapter prelude to reference new `vg_spawn` helper
- Document Codex install path in README + AGENTS.md
- Run full pipeline (project → init → scope → blueprint → build → test → review → accept) end-to-end with `codex exec` on a fixture phase. Note any gaps.

### Out of scope for Phase 18
- Recursive sub-agent depth >1 (Codex default `max_depth = 1`); VGFlow currently doesn't need
- `--output-schema` + MCP simultaneous use (#15451 unresolved); document workaround, defer until OpenAI fixes upstream
- Codex App (remote project) gpt-5.5 issue (#19370); VGFlow runs locally, not affected

**Total: 6-8h. Parallelizable: 18.2 sub-tasks can run independently.**

---

## 8. Source files (for verification)

Read these if you want to verify any claim above:
- `dev-phases/codex-parity-research/CODEBASE-INVENTORY.md` — Agent 1's full inventory (7 sections)
- `dev-phases/codex-parity-research/CODEX-CAPABILITY-RESEARCH.md` — Agent 2's full research (355 lines + sources)
- `dev-phases/codex-parity-research/SYNTHESIS.md` — Cross-agent reconciliation
- `scripts/generate-codex-skills.sh` — current adapter generator (verify line 110 mapping)
- `commands/vg/_shared/crossai-invoke.md` — existing `codex exec` usage pattern
- `commands/vg/_shared/config-loader.md` — `MODEL_PLANNER`/`MODEL_EXECUTOR`/`MODEL_SCANNER` defaults
- `codex-skills/vg-build/SKILL.md` — example of generated Codex skill with adapter prelude
- `commands/vg/build.md` — example of Claude source with `Agent(...)` blocks (lines 1566, 2451, 3300+)

GitHub references (verify status with `gh issue view`):
- [openai/codex#8962](https://github.com/openai/codex/issues/8962) — recursive codex exec officially endorsed (CLOSED)
- [openai/codex#16548](https://github.com/openai/codex/issues/16548) — spawn_agent ignores model (OPEN)
- [openai/codex#15451](https://github.com/openai/codex/issues/15451) — output-schema dropped with MCP (CLOSED but unresolved)
- [openai/codex#14343](https://github.com/openai/codex/issues/14343) — exec resume doesn't accept output-schema (OPEN)
- [openai/codex#14866](https://github.com/openai/codex/issues/14866) — subagents stuck awaiting instruction (CLOSED, workaround-only)
- [openai/codex#19370](https://github.com/openai/codex/issues/19370) — gpt-5.5 not in remote-project Codex App

OpenAI docs:
- [Codex CLI Reference](https://developers.openai.com/codex/cli/reference)
- [Codex Subagents](https://developers.openai.com/codex/subagents)
- [Codex Models](https://developers.openai.com/codex/models)
- [Codex Configuration](https://developers.openai.com/codex/config-reference)
- [Codex Non-interactive Mode](https://developers.openai.com/codex/noninteractive)
- [Codex MCP](https://developers.openai.com/codex/mcp)
- [Codex Skills](https://developers.openai.com/codex/skills)
- [OpenAI Pricing](https://developers.openai.com/api/docs/pricing)

Community references:
- [robert-glaser.de — Claude Skills in Codex CLI](https://www.robert-glaser.de/claude-skills-in-codex-cli/) — confirms format compatibility
- [Simon Willison: Codex subagents announcement](https://simonwillison.net/2026/Mar/16/codex-subagents/)
- [Simon Willison: GPT-5.5 backdoor API](https://simonwillison.net/2026/Apr/23/gpt-5-5/)
- [VoltAgent/awesome-codex-subagents](https://github.com/VoltAgent/awesome-codex-subagents) — 130+ specialized TOML examples

---

## 9. What we want from you (Codex), explicitly

In your response, please cover:

1. **Sanity check on §3-§5.** Are any of our claims wrong as of your knowledge cutoff? Which ones, and what's the corrected version? Especially flag if our model pricing or issue statuses are stale.

2. **Answer the 5 questions in §6.** Give your reasoning, not just a choice. If you'd add or split a question, say so.

3. **Refine the Phase 18 roadmap if you see a better cut.** Maybe 18.2 should split per-skill into sub-phases. Maybe 18.0 should ship even smaller. Your call — show your reasoning.

4. **Identify anything we missed.** Are there VGFlow flows that depend on Claude-specific primitives we didn't catalog (TaskCreate? Plan mode? specific MCP servers?)? Is there a Codex feature we should be using that we didn't mention?

5. **Optional: produce the actual skeleton** for `commands/vg/_shared/lib/spawn.sh` if you're comfortable. Detect `$VG_HARNESS` env var (or fall back to detecting via `which claude` / `which codex`); dispatch to either `Agent(...)` JSON output (for Claude) or `codex exec` invocation (for Codex). Bash, defensively-coded, with timeout.

6. **Surface any Codex-specific gotchas** you anticipate from your own experience that aren't in the soft-blocker list. We want surprise-free Phase 18 execution.

---

## 10. Constraints

- **Don't write code yet.** Decisions first. Implementation is a separate session.
- **Stay vendor-neutral in skill bodies.** The same `commands/vg/*.md` should work in both Claude and Codex environments (Phase 18 goal). Don't propose Codex-only or Claude-only divergent skill bodies.
- **No breaking changes to v2.11.1 surface.** Existing Claude users must continue to work. Codex parity is additive.
- **Keep `vg.config.md` as the single source of model-tier config.** Don't introduce a separate `vg.codex.config.md`.
- **Adversarial / cross-AI peer reviews continue working.** `crossai-invoke.md` already uses `codex exec`; don't break that path.

---

## End of brief

When ready to respond, structure your reply as:
1. **Findings to correct** (if any) — bulleted, each with corrected version + source
2. **Q1-Q5 answers** — each in 2-4 sentences with reasoning
3. **Phase 18 roadmap refinement** — diff or full rewrite, your choice
4. **Things we missed** — bulleted
5. **Optional: spawn.sh skeleton** — code block

Length budget: 1500-2500 words. Be direct, skeptical, specific. Cite sources for any factual claim that contradicts what we wrote here.
