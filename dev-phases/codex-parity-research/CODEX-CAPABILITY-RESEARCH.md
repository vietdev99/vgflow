# Codex CLI Capability Research — VGFlow Parity Assessment

**Date:** 2026-04-27
**Codex CLI versions referenced:** 0.122.0 (Apr 20), 0.124.0 (Apr 23), 0.125.0
**Purpose:** Determine whether VGFlow skills built around Claude Code's `Task` sub-agent primitive can be ported to Codex CLI (`codex exec`), and at what cost.

---

## TL;DR (read this first)

| Capability | Claude Code | Codex CLI | Parity? |
|---|---|---|---|
| Sub-agent spawn (isolated context) | `Task` tool | `spawn_agent` tool + `~/.codex/agents/*.toml` | YES (with caveats) |
| Recursive sub-agent | Limited by max_thinking_tokens, no hard cap | `agents.max_depth = 1` default; raise carefully | YES |
| Recursive `codex exec` from inside session | N/A | YES — official OpenAI position | YES |
| Single-prompt-in / single-message-out | `codex_executor()` style | `codex exec "..."` + `--output-last-message` | YES |
| Parent controls child model | `Task(subagent_type=...)` | `model = "..."` in agent TOML | **PARTIALLY BROKEN** (issue #16548) |
| Heavy / Balanced / Cheap model tiers | Opus / Sonnet / Haiku | gpt-5.5 / gpt-5.4-mini / gpt-5.4-nano | YES |
| Skills format (SKILL.md + frontmatter) | `~/.claude/skills/...` | `~/.codex/skills/...` | YES — same format |
| Headless mode for CI | `claude -p "..."` | `codex exec "..."` with `CODEX_API_KEY` | YES |
| Structured JSON output | tool result | `--output-schema schema.json` | YES (broken if MCP active — issue #15451) |

**Bottom line:** Parity is achievable, but two open Codex bugs (model parameter ignored on spawn; `--output-schema` silently dropped when MCP servers active) materially affect VGFlow's planner-spawn and code-reviewer-spawn flows. Workarounds exist but require explicit per-agent TOML files instead of inline model selection.

---

## Question 1: Sub-agent spawn primitive

### 1.1 Direct equivalent — YES, two layers

Codex ships **two** sub-agent primitives:

**Layer A: `spawn_agent` model-callable tool** (default-on, "stable" since GA in Mar 2026)
- Listed alongside `send_input`, `resume_agent`, `wait_agent`, `close_agent`, and the experimental `spawn_agents_on_csv` for batch workloads.
- Triggered by **natural language in the prompt**, not by the host CLI directly. Example prompt that works:
  > "Spawn one agent per point, wait for all of them, and summarize the result for each point. 1. Security 2. Code quality 3. Bugs ..."
- Each subagent runs in its own thread; switch via `/agent` slash command.
- Built-in agent roles: `default`, `worker`, `explorer`. Custom agents override built-ins by name.
- **Concurrency:** `agents.max_threads = 6` default; parent waits for all results then returns consolidated response.

**Layer B: Custom agents via TOML** (`~/.codex/agents/<name>.toml` or project-scoped `.codex/agents/`)
```toml
name = "reviewer"
description = "PR reviewer focused on correctness, security, and missing tests."
model = "gpt-5.4"
model_reasoning_effort = "high"
sandbox_mode = "read-only"
developer_instructions = """Your core instructions here."""
```
Optional fields inherit from parent session when omitted. This is the closest analog to Claude's typed sub-agents — pre-declared, named, model-pinned.

### 1.2 Recursive `codex exec` from inside Codex — YES, officially

GitHub issue [#8962 "Let Codex call Codex recursively"](https://github.com/openai/codex/issues/8962) was **closed** by OpenAI maintainer `etraut-openai` on 2026-01-09 with the answer:

> "You can already run codex recursively. Just tell it to run `codex exec` (non-interactive mode). Using this technique, you can spawn subagents."

This means VGFlow can use the bash-wrapper pattern in addition to (or instead of) `spawn_agent`:
```bash
# inside parent codex session, prompt instructs:
codex exec --model gpt-5.4-mini "review this diff: $(git diff main)" \
  --output-last-message /tmp/review.md
```
**Important caveat:** the parent's sandbox policy applies to the recursive `codex exec` call (it's a shell invocation), so you may need `--full-auto` or `workspace-write` sandbox in the parent. In practice this means recursive `codex exec` only works reliably when the parent agent has shell-write permission.

### 1.3 Single-prompt-in / single-message-out — YES

`codex exec "<prompt>"` is the canonical headless invocation. Behavior:
- Streams progress to **stderr**
- Prints **only the final agent message to stdout**
- Stdin can be piped as additional context (e.g., `git diff | codex exec "review this"`)
- `-o /path/to/file` (or `--output-last-message`) writes the final message to a file
- `--output-schema schema.json` constrains the final output to a JSON schema — useful for VGFlow's structured planner output

`CODEX_API_KEY` is supported **only** in `codex exec` (not in interactive TUI), which is the right authentication path for automation.

### 1.4 Parent controls child model — PARTIALLY BROKEN

This is the most important caveat. Three open/recently-closed Codex issues document model-control reliability problems:

| Issue | Status | What breaks |
|---|---|---|
| [#16548](https://github.com/openai/codex/issues/16548) — `spawn_agent` ignores requested `gpt-5.4-mini` | **OPEN** as of research date | Parent says "use gpt-5.4-mini for child", child still launches as gpt-5.4. Silent cost escalation. |
| [#14866](https://github.com/openai/codex/issues/14866) — Subagents don't follow default GPT-5.4, get stuck "awaiting instruction" | **CLOSED** but workaround-only | Explicit per-agent model declaration in prompt works; default inheritance does not. |
| Changelog entry v0.124.0 (Apr 23) | "prefer inherited spawn agent model" — partial fix | Still does not address #16548. |

**Workaround that works today:** put model selection in the agent TOML file, never rely on inline parameters from the parent prompt:
```toml
# ~/.codex/agents/vgflow-planner.toml
name = "vgflow-planner"
model = "gpt-5.4"           # locked here, not negotiable
model_reasoning_effort = "high"
developer_instructions = "VGFlow planner prompt..."
```
Then parent invokes by **name**, not by inline model: "spawn the vgflow-planner agent for this scope round."

For recursive `codex exec`, the `-m / --model` flag DOES work reliably — it's only the `spawn_agent` tool path that has the bug. So if model control matters, prefer `codex exec` recursion over `spawn_agent`.

### 1.5 Timeout / kill behavior

- `agents.job_max_runtime_seconds` — default per-worker timeout for `spawn_agents_on_csv` jobs; defaults to **1800 sec** if unset
- Per-call `max_runtime_seconds` overrides the default for batch jobs
- For one-off `codex exec`, **no documented hard timeout**; use shell-level `timeout 300 codex exec "..."` to bound it
- `mcp_servers.<id>.tool_timeout_sec` — default 60s per MCP tool call
- `mcp_servers.<id>.startup_timeout_sec` — default 10s
- Background terminal poll window: 300000 ms (5 min) default

**Verdict:** No clean kill-on-timeout for `codex exec` itself. VGFlow needs to wrap with `timeout` or `gtimeout` and handle SIGTERM gracefully.

---

## Question 2: GPT-5.x model tier mapping

### 2.1 Current lineup as of 2026-04-27 (verified against [pricing page](https://developers.openai.com/api/docs/pricing))

| Model | Input/1M | Cached/1M | Output/1M | Context | Max output | Recommended use |
|---|---|---|---|---|---|---|
| **gpt-5.5** (released Apr 23) | $5.00 | $0.50 | $30.00 | 1,050,000 | 128,000 | Heavy reasoning, planner orchestrator |
| **gpt-5.5-pro** | $30.00 | — | $180.00 | 1M+ | — | Extreme-reasoning premium tier |
| **gpt-5.4** (was flagship until Apr 23) | $2.50 | $0.25 | $15.00 | ~400K | — | General execution, balanced |
| **gpt-5.4-mini** | $0.75 | $0.075 | $4.50 | — | — | Subagents, lighter coding, exploration |
| **gpt-5.4-nano** | $0.20 | $0.02 | $1.25 | — | — | High-volume cheap classification |
| **gpt-5.4-pro** | $30.00 | — | $180.00 | — | — | (Same price as 5.5-pro) |
| **gpt-5.3-codex** | $1.75 | $0.175 | $14.00 | — | — | Codex-specific complex SWE |
| **gpt-5-nano** (legacy, still cheapest) | $0.05 | — | $0.40 | 400K | — | UI-MAP scanner equivalent — cheapest production model |

Batch tier = **50% off** standard. Priority = **2.5×** standard for guaranteed throughput.

### 2.2 Mapping to VGFlow's Claude tiers

| VGFlow role | Claude model | **Recommended Codex model** | Rationale |
|---|---|---|---|
| Scope orchestrator, planner | Opus 4.7 | **gpt-5.5** | Frontier; 1M context; structured output; tool calling. **Note:** gpt-5.5 had ChatGPT-only auth at first, but `Apr 24, 2026` API rollout is live — auth via `OPENAI_API_KEY`. |
| Executor wave, general code review | Sonnet 4.6 | **gpt-5.4-mini** | $0.75/$4.50 — comparable cost-perf to Sonnet. |
| UI-MAP scanner, narration formatter, classification | Haiku 4.5 | **gpt-5-nano** ($0.05/$0.40) or **gpt-5.4-nano** ($0.20/$1.25) | gpt-5-nano is 4× cheaper but older; gpt-5.4-nano if quality matters. |
| Adversarial challenge | Different model | **gpt-5.3-codex** | Codex-tuned, different training distribution, useful contrarian. |

### 2.3 Tool calling & structured output per tier

**gpt-5.5:** Full tool support — function calling, web search, file search, image gen, code interpreter, hosted shell, `apply_patch`, skills, computer use, MCP, tool search. Structured outputs supported.

**gpt-5.4 / gpt-5.4-mini / gpt-5.4-nano:** Standard function calling and structured outputs. Some tools (computer use, advanced MCP) gated to flagship tier — verify per case.

**gpt-5-nano:** Function calling supported. Structured outputs supported. Tool ecosystem reduced. Acceptable for VGFlow classification/formatting.

### 2.4 What model the Codex CLI itself supports

`codex --model` (or `-m`) accepts any model name from the pricing/models pages. The recommended default in Codex CLI as of Apr 23 is **gpt-5.5**, with gpt-5.4 as the "if not yet rolled out to your region" fallback. There's no official `--list-models` command; the canonical list is the [Codex models page](https://developers.openai.com/codex/models). In-session model switching is `/model`.

**GPT-5.5 auth note:** As of mid-Apr 2026, the only way to use gpt-5.5 in CLI was ChatGPT OAuth signin (`grep '"auth_mode"' ~/.codex/auth.json` returns "chatgpt"). On **Apr 24, 2026** OpenAI shipped Responses-API and Chat-Completions-API access for gpt-5.5 with standard `OPENAI_API_KEY`. So as of this report's date (2026-04-27), API-key automation works.

---

## Question 3: Codex-specific patterns for multi-step flows

### 3.1 Native patterns the docs and community recommend

1. **`spawn_agent` natural-language orchestration** — best when you want a single Codex session to fan out to many parallel children and synthesize results. Lossy on model control (see #16548). Documented [example](https://developers.openai.com/codex/subagents): "Spawn one agent per point, wait for all of them, and summarize."

2. **Recursive `codex exec`** — bash-wrapping pattern endorsed by OpenAI on issue #8962. Gives you full control over each child's `--model`, `--sandbox`, `--output-schema`, `CODEX_API_KEY`. Cost: cold-start each time (~few seconds extra latency vs. `spawn_agent`).

3. **`spawn_agents_on_csv`** — experimental, designed for "review N items in a CSV" patterns. Each worker calls `report_agent_job_result` exactly once. Output schema enforced. Useful for VGFlow's executor wave if items are well-defined.

4. **Custom agent TOML files in `~/.codex/agents/`** — pre-declare role + model + sandbox + system prompt. Invoke by name. This is the **most reliable** path for parent-controlled model selection (sidesteps #16548 because model is locked at agent definition, not at spawn-time).

5. **`AGENTS.md` walking** — Codex auto-discovers and loads every `AGENTS.md` from repo root to current dir. Use this for project-wide conventions, not for spawn orchestration.

### 3.2 Patterns to AVOID

- **Inline model selection in spawn prompt** ("use gpt-5.4-mini for the children") — broken per #16548.
- **`--json` + `--output-schema` when MCP servers are active** — silently produces malformed output per [#15451](https://github.com/openai/codex/issues/15451). Workaround: disable MCP servers for the structured-output `codex exec` call, or use `--output-last-message` + post-parse plain text.
- **`codex exec resume <id>` with `--output-schema`** — not supported per [#14343](https://github.com/openai/codex/issues/14343). Resume sessions cannot return structured JSON.
- **Premature subagent fan-out for tasks still being iterated** — official best-practice page warns: "Turn a recurring task into an automation before it's reliable manually."

### 3.3 Real-world community examples

- [VoltAgent/awesome-codex-subagents](https://github.com/VoltAgent/awesome-codex-subagents) — 130+ specialized subagent TOML files for download.
- [ComposioHQ/awesome-codex-skills](https://github.com/ComposioHQ/awesome-codex-skills) — curated skill catalog.
- [feiskyer/codex-settings](https://github.com/feiskyer/codex-settings) — production `config.toml` examples.
- [robert-glaser.de blog post](https://www.robert-glaser.de/claude-skills-in-codex-cli/) — confirms Claude skill format is **identical** to Codex skill format; provides Python enumerator script for hot-loading.

---

## Question 4: Codex skill format & best practices

### 4.1 SKILL.md frontmatter — same as Claude

```yaml
---
name: skill-identifier         # required, lowercase-hyphenated, must match folder name
description: One-sentence summary used by Codex to decide when to invoke.  # required
---

# Skill body in markdown
Instructions Codex follows when invoked...
```

Optional fields (not strictly required, but supported):
- `allowed-tools` — restrict tool use within skill
- Per-skill metadata via `agents/openai.yaml` (UI metadata, tool dependencies)

### 4.2 Directory structure

```
~/.codex/skills/<skill-name>/
├── SKILL.md             # required
├── scripts/             # optional helper scripts (deterministic steps)
├── references/          # optional long-form docs (lazy-loaded)
├── assets/              # optional templates, fixtures
└── agents/openai.yaml   # optional UI/dependency metadata
```

System skills ship in `~/.codex/skills/.system/` (`plan` skill, `skill-creator` skill).

### 4.3 Enabling / disabling skills

```toml
# ~/.codex/config.toml
[[skills.config]]
path = "~/.codex/skills/vgflow-scope-round"
enabled = true

[[skills.config]]
path = "~/.codex/skills/some-noisy-skill"
enabled = false   # disable without deleting
```

Restart Codex after install/update to reload metadata.

### 4.4 Can skills call other skills? Can skills spawn agents?

**Officially undocumented.** The skill docs don't explicitly forbid or endorse it. In practice:
- A skill's `scripts/` can invoke `codex exec` recursively (which can in turn invoke other skills via prompt instruction) — this is the bash-wrapper pattern again.
- A skill can instruct the model to "call the X skill next" but Codex's discovery mechanism (system-prompt-driven, not tool-driven) means there's no hard guarantee the model will comply.

**Practical pattern for VGFlow:** treat each VGFlow skill as a leaf operation. For multi-skill orchestration, write a thin bash launcher that calls `codex exec --skill <name>` per phase. This is closer to how `gsd-*` skills already work in this repo.

### 4.5 Differences from Claude skill format

Per [Robert Glaser's writeup](https://www.robert-glaser.de/claude-skills-in-codex-cli/), the formats are deliberately compatible. Two practical differences:
1. **Discovery mechanism:** Claude Code loads all skills at startup. Codex requires an enumerator script (Glaser provides one) plus an `AGENTS.md` instruction telling Codex how to discover.
2. **Per-project enable/disable:** Codex's `[[skills.config]]` gives finer control than Claude's all-or-nothing approach — useful for VGFlow's workspace isolation.

---

## Recommended approach for VGFlow → Codex parity

### Architecture: hybrid wrapper + custom agents

```
VGFlow CLI invocation
    ↓
gsd-* skill (Claude OR Codex — same SKILL.md)
    ↓
For sub-agent spawn:
    ├── Path A (preferred): bash wrapper → codex exec --model gpt-5.X --output-last-message /tmp/result.md
    │   - Reliable model control
    │   - Independent CODEX_API_KEY auth
    │   - Easy to timeout/kill at shell level
    │   - Cost: ~2-3s cold start per spawn
    │
    └── Path B (when low-latency fan-out matters): natural-language spawn_agent in prompt
        - Lower latency for 5+ parallel children
        - Lock model in ~/.codex/agents/vgflow-*.toml (NEVER inline)
        - Accept model-inheritance bugs as known risk
```

### Per-skill mapping

| VGFlow skill | Sub-agent mechanism | Codex model |
|---|---|---|
| Scope round dimension expansion | bash-wrap `codex exec` (5-10 parallel) | gpt-5.5 (orchestrator) → gpt-5.4-mini (children) |
| Planner spawn (1 task per planner) | bash-wrap `codex exec` (parallel by GNU parallel or `&`) | gpt-5.4 each |
| Code reviewer spawn (independent fresh context) | bash-wrap `codex exec --sandbox read-only` | gpt-5.4 or gpt-5.3-codex (adversarial diversity) |
| UI-MAP scanner / narration | inline `codex exec` (no spawn) | gpt-5-nano or gpt-5.4-nano |
| Adversarial challenge | bash-wrap with `gpt-5.3-codex` model | gpt-5.3-codex |

### Implementation steps (concrete, in order)

1. **Add Codex auth** to repo: `CODEX_API_KEY` env var documented in `CLAUDE.md` and any new `AGENTS.md`.
2. **Write 3 baseline agent TOMLs** in `~/.codex/agents/`:
   - `vgflow-orchestrator.toml` — model = gpt-5.5, sandbox = workspace-write
   - `vgflow-executor.toml` — model = gpt-5.4-mini, sandbox = workspace-write
   - `vgflow-classifier.toml` — model = gpt-5.4-nano (or gpt-5-nano), sandbox = read-only
3. **Build a `codex_spawn` shell helper** that wraps `codex exec` with: timeout, model selection, `--output-last-message`, error handling, JSON parsing.
4. **Port one skill end-to-end** (e.g., scope round dimension) to verify the pattern works before porting all.
5. **Add CI smoke test** that runs the ported skill against a fixture and asserts output schema.

---

## Showstoppers (things that fundamentally cannot work today)

### Hard blockers — none

There is **no fundamental capability gap** between Claude Code's `Task` tool and Codex's `spawn_agent` + recursive `codex exec` combo. Both can:
- Spawn isolated-context children
- Pass a self-contained prompt
- Get a single message back
- Run in parallel
- Pin a specific model

### Soft blockers (known bugs — workarounds exist)

1. **Issue [#16548](https://github.com/openai/codex/issues/16548) — `spawn_agent` ignores model parameter.** Workaround: use TOML-pinned models or recursive `codex exec`. Cost: more verbose configuration.

2. **Issue [#15451](https://github.com/openai/codex/issues/15451) — `--output-schema` silently dropped when MCP servers active.** Workaround: disable MCP for structured-output runs, OR don't rely on schema (parse plain text). Cost: VGFlow can't use schemas for any flow that needs MCP tools (Penboard/Pencil). Materially affects design-fidelity flows.

3. **Issue [#14343](https://github.com/openai/codex/issues/14343) — `codex exec resume` doesn't accept `--output-schema`.** Workaround: don't resume sessions for structured-output flows; do them as fresh `codex exec`. Cost: lose conversation memory in those flows.

### Operational caveats (not bugs but constraints)

- **Higher token cost.** OpenAI documents this explicitly: "Because each subagent does its own model and tool work, subagent workflows consume more tokens than comparable single-agent runs." Plan VGFlow Codex runs to be ~1.3-1.8× the token budget of equivalent Claude runs.
- **No hard `codex exec` timeout.** Wrap with shell `timeout`. Don't trust the CLI to bound itself.
- **Sandbox mode propagation.** Recursive `codex exec` inherits parent's sandbox; if parent is `read-only`, child can't write. Plan sandbox modes per-skill explicitly.
- **`max_depth = 1` default.** If VGFlow expects 2+ levels of sub-agent nesting (orchestrator → planner → executor), raise this in `~/.codex/config.toml` — but understand it's fan-out risk.
- **gpt-5.5 just shipped to API on Apr 24.** Some regions/orgs may still see "model not found" until the rollout completes. Have a `--model gpt-5.4` fallback path.

---

## Sources

- [Codex CLI Reference](https://developers.openai.com/codex/cli/reference) — official flag list
- [Codex Subagents](https://developers.openai.com/codex/subagents) — subagent system docs
- [Codex Models](https://developers.openai.com/codex/models) — recommended models per task
- [Codex Configuration Reference](https://developers.openai.com/codex/config-reference) — `agents.*`, sandbox, MCP timeouts
- [Codex Non-interactive Mode](https://developers.openai.com/codex/noninteractive) — `codex exec` behavior, `--output-schema`
- [Codex MCP](https://developers.openai.com/codex/mcp) — MCP client and server config
- [Codex Agents SDK guide](https://developers.openai.com/codex/guides/agents-sdk) — `codex mcp-server`, `codex` and `codex-reply` tool schemas
- [Codex Agent Skills](https://developers.openai.com/codex/skills) — SKILL.md format
- [Codex Slash Commands](https://developers.openai.com/codex/cli/slash-commands) — `/agent`, `/model`, `/fork`, `/new`
- [Codex Best Practices](https://developers.openai.com/codex/learn/best-practices) — when (not) to use subagents
- [Codex Changelog](https://developers.openai.com/codex/changelog) — v0.122 (Apr 20), v0.124 (Apr 23), v0.125
- [OpenAI Pricing](https://developers.openai.com/api/docs/pricing) — verified gpt-5.5/5.4/5.3 token rates
- [GPT-5.5 model page](https://developers.openai.com/api/docs/models/gpt-5.5) — context window 1,050,000; max output 128,000
- [GPT-5.5 launch blog](https://openai.com/index/introducing-gpt-5-5/) — Apr 23 2026 launch
- [GPT-5.5 pricing breakdown](https://apidog.com/blog/gpt-5-5-pricing/) — confirmed pricing tiers
- [GPT-5-nano price/spec](https://blog.galaxy.ai/model/gpt-5-nano) — $0.05/$0.40, 400K context

GitHub issues (status verified via `gh issue view`):
- [#8962 (CLOSED)](https://github.com/openai/codex/issues/8962) — recursive codex exec officially endorsed
- [#16548 (OPEN)](https://github.com/openai/codex/issues/16548) — spawn_agent ignores model
- [#14866 (CLOSED)](https://github.com/openai/codex/issues/14866) — subagents stuck "awaiting instruction"
- [#15451 (CLOSED but unresolved)](https://github.com/openai/codex/issues/15451) — --output-schema dropped with MCP
- [#14343 (OPEN)](https://github.com/openai/codex/issues/14343) — --output-schema not in resume
- [#19370](https://github.com/openai/codex/issues/19370) — gpt-5.5 not usable in remote-project Codex App (CLI works)

Community references:
- [robert-glaser.de — Claude Skills in Codex CLI](https://www.robert-glaser.de/claude-skills-in-codex-cli/)
- [Simon Willison: Codex subagents announcement](https://simonwillison.net/2026/Mar/16/codex-subagents/)
- [Simon Willison: GPT-5.5 backdoor API](https://simonwillison.net/2026/Apr/23/gpt-5-5/)
- [Frank's Wiki: Multi-agent and sub-agent patterns in Codex](https://liviaerxin.github.io/blog/multi-agent-and-sub-agent-patterns-in-codex-practical-guide)
- [VoltAgent awesome-codex-subagents](https://github.com/VoltAgent/awesome-codex-subagents)
- [hexdocs Codex SDK subagents](https://hexdocs.pm/codex_sdk/10-subagents.html) — Elixir SDK reference

**Caveats on sources:** Several details (exact timeout defaults, `spawn_agent` full schema, recursion-with-MCP behavior) are documented inconsistently across the official docs. Where official docs were silent, this report cites third-party blog posts and explicitly flags lower confidence. The `spawn_agent` model-mismatch bug is reproducible per multiple GitHub issues — this is well-supported. The "codex can recursively call codex" claim is supported by an OpenAI maintainer's direct comment on issue #8962 — high confidence.
